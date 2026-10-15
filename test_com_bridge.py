"""
com_bridge.py unit tests
========================
Covers the standalone Windows serial->TCP MAVLink relay script at the repo
root. This module had ZERO test coverage before this file (it isn't part of
the backend package and isn't imported anywhere except invoked as a
subprocess, so it's outside backend/app/tests/ entirely).

com_bridge.py reads sys.argv at import time, so tests patch sys.argv before
importing it and import it fresh in a fixture (module import is cached, so a
session-scoped import with default args is enough here since no test needs
non-default CLI args).

Functions under test:
  SerialDevice.status()            — snapshot of connection + discovered ports
  SerialDevice.mark_disconnected() — resets state, closes serial handle
  SerialDevice.connect_forever()   — one iteration of the port-selection logic
  DiscoveryHandler.do_GET          — HTTP /ports endpoint
  pipe_serial_to_tcp               — serial -> socket forwarding loop
  pipe_tcp_to_serial               — socket -> serial forwarding loop
  handle_client                    — single-client gating + pipe wiring
"""
import importlib
import json
import sys
import threading
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture(scope="module")
def com_bridge():
    """Import com_bridge.py with default CLI args (no argv pollution)."""
    old_argv = sys.argv
    sys.argv = ["com_bridge.py"]
    try:
        import com_bridge as cb
        importlib.reload(cb)
        yield cb
    finally:
        sys.argv = old_argv


@pytest.fixture
def fresh_device(com_bridge):
    """A brand-new SerialDevice instance, independent of the module-level singleton."""
    return com_bridge.SerialDevice()


# ══════════════════════════════════════════════════════════════════════
# SerialDevice.status
# ══════════════════════════════════════════════════════════════════════

def test_status_disconnected_reports_no_active_port(com_bridge, fresh_device):
    with patch.object(
        com_bridge.serial.tools.list_ports, "comports", return_value=[]
    ):
        result = fresh_device.status()

    assert result["connected"] is False
    assert result["active_port"] is None
    assert result["description"] is None
    assert result["ports"] == []
    assert result["baud"] == com_bridge.BAUD


def test_status_connected_reports_active_port_and_open_serial(com_bridge, fresh_device):
    fake_serial = MagicMock()
    fake_serial.is_open = True
    fresh_device.serial = fake_serial
    fresh_device.port = "COM3"
    fresh_device.description = "USB Serial Device"

    with patch.object(
        com_bridge.serial.tools.list_ports, "comports", return_value=[]
    ):
        result = fresh_device.status()

    assert result["connected"] is True
    assert result["active_port"] == "COM3"
    assert result["description"] == "USB Serial Device"


def test_status_lists_available_ports_with_fallback_description(com_bridge, fresh_device):
    fake_port = SimpleNamespace(device="COM5", description="", hwid="USB VID:PID=1234")
    with patch.object(
        com_bridge.serial.tools.list_ports, "comports", return_value=[fake_port]
    ):
        result = fresh_device.status()

    assert result["ports"] == [
        {"port": "COM5", "desc": "COM5", "hwid": "USB VID:PID=1234"}
    ]


def test_status_reports_configured_tcp_port_when_not_yet_bound(com_bridge, fresh_device):
    result = fresh_device.status()
    assert result["tcp_port"] == com_bridge.TCP_PORT


def test_status_reports_actual_bound_tcp_port_once_set(com_bridge, fresh_device):
    fresh_device.tcp_port = 5764
    with patch.object(
        com_bridge.serial.tools.list_ports, "comports", return_value=[]
    ):
        result = fresh_device.status()

    assert result["tcp_port"] == 5764


# ══════════════════════════════════════════════════════════════════════
# SerialDevice.mark_disconnected
# ══════════════════════════════════════════════════════════════════════

def test_mark_disconnected_closes_serial_and_clears_state(fresh_device):
    fake_serial = MagicMock()
    fresh_device.serial = fake_serial
    fresh_device.port = "COM3"
    fresh_device.description = "USB Serial Device"

    fresh_device.mark_disconnected()

    fake_serial.close.assert_called_once()
    assert fresh_device.serial is None
    assert fresh_device.port is None
    assert fresh_device.description is None


def test_mark_disconnected_swallows_close_errors(fresh_device):
    """A serial handle that raises on close() must not propagate — the port may
    already be physically unplugged."""
    fake_serial = MagicMock()
    fake_serial.close.side_effect = OSError("device gone")
    fresh_device.serial = fake_serial

    fresh_device.mark_disconnected()  # must not raise

    assert fresh_device.serial is None


def test_mark_disconnected_noop_when_already_disconnected(fresh_device):
    fresh_device.mark_disconnected()  # must not raise
    assert fresh_device.serial is None


# ══════════════════════════════════════════════════════════════════════
# SerialDevice.connect_forever — one iteration of the selection logic
# ══════════════════════════════════════════════════════════════════════

def _run_one_iteration(com_bridge, device, ports, requested="auto", connect_side_effect=None):
    """connect_forever() is an infinite loop; run it until one connect attempt
    (or one wait cycle) happens, then break out via a controlled side effect
    on time.sleep."""
    call_count = {"n": 0}

    def fake_sleep(_seconds):
        call_count["n"] += 1
        raise StopIteration()

    with patch.object(com_bridge, "REQUESTED_PORT", requested), \
         patch.object(com_bridge.serial.tools.list_ports, "comports", return_value=ports), \
         patch.object(com_bridge.time, "sleep", side_effect=fake_sleep), \
         patch.object(
             com_bridge.serial, "Serial",
             side_effect=connect_side_effect if connect_side_effect else MagicMock(),
         ) as mock_serial_ctor:
        with pytest.raises(StopIteration):
            device.connect_forever()

    return mock_serial_ctor


def test_connect_forever_prefers_usb_hwid_port(com_bridge, fresh_device):
    usb_port = SimpleNamespace(device="COM4", description="Pixhawk", hwid="USB VID:PID=1234")
    non_usb_port = SimpleNamespace(device="COM1", description="Onboard", hwid="")

    mock_ctor = _run_one_iteration(com_bridge, fresh_device, [non_usb_port, usb_port])

    mock_ctor.assert_called_once()  # open_serial() builds one unopened Serial
    opened = fresh_device.serial
    assert (opened.port, opened.baudrate) == ("COM4", com_bridge.BAUD)
    opened.open.assert_called_once()
    assert fresh_device.port == "COM4"
    assert fresh_device.description == "Pixhawk"


def test_connect_forever_honors_explicit_requested_port(com_bridge, fresh_device):
    wanted = SimpleNamespace(device="COM7", description="Requested", hwid="")
    other = SimpleNamespace(device="COM4", description="USB device", hwid="USB")

    mock_ctor = _run_one_iteration(
        com_bridge, fresh_device, [other, wanted], requested="COM7"
    )

    mock_ctor.assert_called_once()  # open_serial() builds one unopened Serial
    opened = fresh_device.serial
    assert (opened.port, opened.baudrate) == ("COM7", com_bridge.BAUD)
    opened.open.assert_called_once()


def test_connect_forever_falls_back_to_auto_when_requested_port_absent(com_bridge, fresh_device):
    only_port = SimpleNamespace(device="COM9", description="Fallback", hwid="USB")

    mock_ctor = _run_one_iteration(
        com_bridge, fresh_device, [only_port], requested="COM99"
    )

    mock_ctor.assert_called_once()  # open_serial() builds one unopened Serial
    opened = fresh_device.serial
    assert (opened.port, opened.baudrate) == ("COM9", com_bridge.BAUD)
    opened.open.assert_called_once()


def test_connect_forever_no_ports_available_waits_without_connecting(com_bridge, fresh_device):
    mock_ctor = _run_one_iteration(com_bridge, fresh_device, [])
    mock_ctor.assert_not_called()
    assert fresh_device.serial is None


def test_connect_forever_open_failure_leaves_device_disconnected(com_bridge, fresh_device):
    import serial as pyserial

    port = SimpleNamespace(device="COM4", description="Pixhawk", hwid="USB")
    mock_ctor = _run_one_iteration(
        com_bridge, fresh_device, [port],
        connect_side_effect=pyserial.SerialException("port busy"),
    )

    mock_ctor.assert_called_once()
    assert fresh_device.serial is None
    assert fresh_device.port is None


def test_connect_forever_already_connected_skips_rescan(com_bridge, fresh_device):
    fake_serial = MagicMock()
    fake_serial.is_open = True
    fresh_device.serial = fake_serial

    with patch.object(com_bridge.time, "sleep", side_effect=StopIteration()) as mock_sleep, \
         patch.object(com_bridge.serial.tools.list_ports, "comports") as mock_comports:
        with pytest.raises(StopIteration):
            fresh_device.connect_forever()

    mock_comports.assert_not_called()
    mock_sleep.assert_called_once_with(1)


# ══════════════════════════════════════════════════════════════════════
# DiscoveryHandler.do_GET
# ══════════════════════════════════════════════════════════════════════

def _make_handler(com_bridge, path, client_ip="127.0.0.1"):
    """Build a DiscoveryHandler instance without running BaseHTTPRequestHandler's
    socket-driven __init__ (there's no real connection here)."""
    handler = com_bridge.DiscoveryHandler.__new__(com_bridge.DiscoveryHandler)
    handler.path = path
    handler.client_address = (client_ip, 50000)
    handler.send_response = MagicMock()
    handler.send_header = MagicMock()
    handler.end_headers = MagicMock()
    handler.send_error = MagicMock()
    handler.wfile = MagicMock()
    return handler


def test_do_get_ports_returns_json_status(com_bridge):
    handler = _make_handler(com_bridge, "/ports")
    fake_status = {"connected": False, "ports": []}

    with patch.object(com_bridge.device, "status", return_value=fake_status):
        handler.do_GET()

    handler.send_response.assert_called_once_with(200)
    handler.send_header.assert_any_call("Content-Type", "application/json")
    written = handler.wfile.write.call_args[0][0]
    assert json.loads(written) == fake_status


def test_do_get_unknown_path_returns_404(com_bridge):
    handler = _make_handler(com_bridge, "/nope")

    handler.do_GET()

    handler.send_error.assert_called_once_with(404)
    handler.wfile.write.assert_not_called()


# ══════════════════════════════════════════════════════════════════════
# pipe_serial_to_tcp / pipe_tcp_to_serial
# ══════════════════════════════════════════════════════════════════════

def test_pipe_serial_to_tcp_forwards_data_until_stopped(com_bridge):
    ser = MagicMock()
    sock = MagicMock()
    stop = threading.Event()

    ser.read.side_effect = [b"\x01\x02", lambda: stop.set() or b""]
    # side_effect items that are callables aren't auto-invoked by Mock, so
    # drive the loop explicitly instead.
    calls = {"n": 0}

    def fake_read(_size):
        calls["n"] += 1
        if calls["n"] == 1:
            return b"\x01\x02"
        stop.set()
        return b""

    ser.read.side_effect = fake_read

    com_bridge.pipe_serial_to_tcp(ser, sock, stop)

    sock.sendall.assert_called_once_with(b"\x01\x02")
    assert stop.is_set()


def test_pipe_serial_to_tcp_serial_exception_marks_disconnected_and_stops(com_bridge):
    ser = MagicMock()
    ser.read.side_effect = com_bridge.serial.SerialException("unplugged")
    sock = MagicMock()
    stop = threading.Event()

    with patch.object(com_bridge.device, "mark_disconnected") as mock_mark:
        com_bridge.pipe_serial_to_tcp(ser, sock, stop)

    mock_mark.assert_called_once()
    assert stop.is_set()


def test_pipe_serial_to_tcp_socket_closed_stops_without_marking_disconnected(com_bridge):
    ser = MagicMock()
    ser.read.side_effect = OSError("client gone")
    sock = MagicMock()
    stop = threading.Event()

    with patch.object(com_bridge.device, "mark_disconnected") as mock_mark:
        com_bridge.pipe_serial_to_tcp(ser, sock, stop)

    mock_mark.assert_not_called()
    assert stop.is_set()


def test_pipe_tcp_to_serial_forwards_data_until_empty_recv(com_bridge):
    ser = MagicMock()
    sock = MagicMock()
    sock.recv.side_effect = [b"\xaa\xbb", b""]
    stop = threading.Event()

    com_bridge.pipe_tcp_to_serial(sock, ser, stop)

    ser.write.assert_called_once_with(b"\xaa\xbb")
    assert stop.is_set()


def test_pipe_tcp_to_serial_serial_exception_marks_disconnected(com_bridge):
    ser = MagicMock()
    ser.write.side_effect = com_bridge.serial.SerialException("write failed")
    sock = MagicMock()
    sock.recv.return_value = b"\x01"
    stop = threading.Event()

    with patch.object(com_bridge.device, "mark_disconnected") as mock_mark:
        com_bridge.pipe_tcp_to_serial(sock, ser, stop)

    mock_mark.assert_called_once()
    assert stop.is_set()


# ══════════════════════════════════════════════════════════════════════
# handle_client
# ══════════════════════════════════════════════════════════════════════

def test_handle_client_rejects_second_concurrent_client(com_bridge):
    com_bridge.device.active_client = True
    conn = MagicMock()

    try:
        com_bridge.handle_client(conn, ("127.0.0.1", 5000))
    finally:
        com_bridge.device.active_client = False

    conn.close.assert_called_once()


def test_handle_client_rejects_when_no_serial_connected(com_bridge):
    com_bridge.device.active_client = False
    com_bridge.device.serial = None
    conn = MagicMock()

    com_bridge.handle_client(conn, ("127.0.0.1", 5000))

    conn.close.assert_called_once()
    assert com_bridge.device.active_client is False


def test_handle_client_starts_pipe_threads_and_releases_lock_on_disconnect(com_bridge):
    fake_serial = MagicMock()
    fake_serial.is_open = True
    com_bridge.device.active_client = False
    com_bridge.device.serial = fake_serial
    com_bridge.device.port = "COM3"
    conn = MagicMock()

    started_threads = []

    class ImmediateThread:
        def __init__(self, target, args, daemon):
            self.target = target
            self.args = args
            started_threads.append(self)

        def start(self):
            # Simulate the pipe finishing instantly by setting the stop event.
            stop = self.args[2]
            stop.set()

    with patch.object(com_bridge.threading, "Thread", ImmediateThread):
        com_bridge.handle_client(conn, ("127.0.0.1", 5000))

    assert len(started_threads) == 2
    conn.close.assert_called_once()
    assert com_bridge.device.active_client is False


# ══════════════════════════════════════════════════════════════════════
# Client allow-list (BRIDGE_ALLOWED_CLIENTS)
# ══════════════════════════════════════════════════════════════════════

@pytest.fixture
def restricted(com_bridge):
    import ipaddress
    old = com_bridge.ALLOWED_CLIENTS
    com_bridge.ALLOWED_CLIENTS = [ipaddress.ip_network("192.168.65.0/24"),
                                  ipaddress.ip_network("127.0.0.0/8")]
    yield
    com_bridge.ALLOWED_CLIENTS = old


def test_default_allow_list_is_private_and_loopback_only(com_bridge):
    assert com_bridge.client_allowed("127.0.0.1")
    assert com_bridge.client_allowed("192.168.1.20")
    assert com_bridge.client_allowed("172.17.0.2")
    assert not com_bridge.client_allowed("8.8.8.8")
    assert not com_bridge.client_allowed("203.0.113.5")


def test_unparseable_address_is_refused(com_bridge):
    assert not com_bridge.client_allowed("not-an-ip")
    assert not com_bridge.client_allowed("")


def test_allow_list_can_be_narrowed(com_bridge, restricted):
    assert com_bridge.client_allowed("192.168.65.3")
    assert not com_bridge.client_allowed("192.168.1.20")


def test_ipv4_mapped_ipv6_uses_the_ipv4_rule(com_bridge, restricted):
    assert com_bridge.client_allowed("::ffff:192.168.65.3")
    assert not com_bridge.client_allowed("::ffff:10.1.1.1")


def test_discovery_refuses_disallowed_client_without_leaking_ports(com_bridge, restricted):
    handler = _make_handler(com_bridge, "/ports", client_ip="10.9.9.9")
    handler.do_GET()
    handler.send_error.assert_called_once_with(403)
    handler.wfile.write.assert_not_called()


def test_mavlink_port_closes_connection_from_disallowed_client(com_bridge, restricted):
    conn = MagicMock()
    com_bridge.handle_client(conn, ("10.9.9.9", 41000))
    conn.close.assert_called_once()
    assert com_bridge.device.active_client is False


# ── Baud auto-detection (ELRS radio USB = 460800, SiK = 57600, USB-CDC = any) ──

_HB_V2 = bytes.fromhex("fd0900000001010000000000000000040303") + b"\x00\x00"
_HB_V1 = bytes.fromhex("fe09000101000000000000000403") + b"\x03\x00\x00"


def test_detects_mavlink2_heartbeat(com_bridge):
    assert com_bridge.looks_like_mavlink(b"\x00\x55" + _HB_V2)


def test_detects_mavlink1_heartbeat(com_bridge):
    assert com_bridge.looks_like_mavlink(b"noise" + _HB_V1)


@pytest.mark.parametrize("data", [b"", b"\x00" * 64, b"hello world 115200", b"\xfd\x09", bytes(range(0, 200, 7))])
def test_garbage_is_not_mavlink(com_bridge, data):
    assert not com_bridge.looks_like_mavlink(data)


def _fake_serial_factory(good_baud, opened):
    class FakeSerial:
        """Mimics pyserial's unopened-then-open() sequence and records line state at open."""
        def __init__(self):
            self.port = self.baudrate = self.timeout = self.write_timeout = None
            self.dtr = self.rts = True          # pyserial default: asserted
            self.closed = False
            self.is_open = False

        def open(self):
            self.is_open = True
            opened.append((self.baudrate, self.dtr, self.rts))

        def read(self, _n):
            return _HB_V2 if self.baudrate == good_baud else b"\x00\xff\x00"

        def close(self):
            self.closed = True
    return FakeSerial


def test_autobaud_finds_the_baud_that_carries_mavlink(com_bridge, monkeypatch):
    opened = []
    monkeypatch.setattr(com_bridge.serial, "Serial", _fake_serial_factory(57600, opened))
    monkeypatch.setattr(com_bridge, "AUTO_BAUD_LISTEN_S", 0.05)
    ser, baud = com_bridge.open_serial_autobaud("COM9")
    assert baud == 57600
    assert [b for b, _, _ in opened] == [460800, 115200, 57600]     # stopped at the first hit


def test_autobaud_holds_first_candidate_when_nothing_is_heard(com_bridge, monkeypatch):
    opened = []
    monkeypatch.setattr(com_bridge.serial, "Serial", _fake_serial_factory(None, opened))
    monkeypatch.setattr(com_bridge, "AUTO_BAUD_LISTEN_S", 0.02)
    ser, baud = com_bridge.open_serial_autobaud("COM9")
    assert baud == com_bridge.AUTO_BAUD_CANDIDATES[0] == 460800
    assert opened[-1][0] == 460800 and not ser.closed


def test_ports_open_with_dtr_and_rts_low(com_bridge, monkeypatch):
    """DTR/RTS drive reset/boot on CP210x ESP32-based radios: they must never be asserted on open."""
    opened = []
    monkeypatch.setattr(com_bridge.serial, "Serial", _fake_serial_factory(None, opened))
    com_bridge.open_serial("COM5", 460800)
    assert opened == [(460800, False, False)]


def test_autobaud_never_asserts_dtr_or_rts(com_bridge, monkeypatch):
    opened = []
    monkeypatch.setattr(com_bridge.serial, "Serial", _fake_serial_factory(115200, opened))
    monkeypatch.setattr(com_bridge, "AUTO_BAUD_LISTEN_S", 0.02)
    com_bridge.open_serial_autobaud("COM5")
    assert opened and all(dtr is False and rts is False for _, dtr, rts in opened)
