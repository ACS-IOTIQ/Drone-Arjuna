"""
Auto-Connector unit tests
=========================
Covers app/modules/drone_control/auto_connector.py directly (not via the
HTTP API layer). This module had ZERO test coverage before this file.

Functions under test:
  _get_bridge_status    — com_bridge discovery HTTP call (urlopen), never raises
  _scan_linux_serial     — pyserial port enumeration -> candidate dicts
  _build_candidates      — ordered probe list (bridge first, then serial, then static)
  _connect_drone         — tries candidates in order via mavlink_manager.connect
  _get_unconnected_drones — DB query filtered by live mavlink_manager connections
  run_auto_connector     — the long-running background loop

Conventions follow test_drone_control_api.py's autoconnect tests:
  - mavlink_manager.connect is patched with unittest.mock.patch.object(..., new=AsyncMock(...))
  - mavlink_manager._connections is populated directly to simulate "already connected"
    (the module-level _reset_mavlink_state autouse fixture in conftest.py clears it
    before/after every test, so mutating it here is safe).
"""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.modules.drone_control import auto_connector as ac


# ══════════════════════════════════════════════════════════════════════
# _get_bridge_status
# ══════════════════════════════════════════════════════════════════════

def test_get_bridge_status_success():
    """Returns the parsed JSON body when the discovery endpoint responds."""
    fake_payload = {"connected": True, "active_port": "COM3", "tcp_port": 5762}

    class _FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return b'{"connected": true}'

    with patch("app.modules.drone_control.auto_connector.urlopen") as mock_urlopen, \
         patch("app.modules.drone_control.auto_connector.json.load", return_value=fake_payload) as mock_load:
        mock_urlopen.return_value = _FakeResponse()
        result = ac._get_bridge_status()

    assert result == fake_payload
    mock_urlopen.assert_called_once_with(ac.DISCOVERY_URL, timeout=1.0)
    mock_load.assert_called_once()


def test_get_bridge_status_bridge_not_running_returns_none():
    """Bridge process not up -> urlopen raises -> function swallows and returns None."""
    with patch("app.modules.drone_control.auto_connector.urlopen", side_effect=ConnectionRefusedError):
        result = ac._get_bridge_status()

    assert result is None


def test_get_bridge_status_bad_json_returns_none():
    """Any exception (timeout, malformed JSON, etc.) must never raise — returns None."""
    class _FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    with patch("app.modules.drone_control.auto_connector.urlopen", return_value=_FakeResponse()), \
         patch("app.modules.drone_control.auto_connector.json.load", side_effect=ValueError("bad json")):
        result = ac._get_bridge_status()

    assert result is None


# ══════════════════════════════════════════════════════════════════════
# _scan_linux_serial
# ══════════════════════════════════════════════════════════════════════

def test_scan_linux_serial_usb_device_tries_four_bauds():
    fake_port = SimpleNamespace(device="/dev/ttyUSB0", hwid="USB VID:PID=1234:5678")
    with patch(
        "app.modules.drone_control.auto_connector.serial.tools.list_ports.comports",
        return_value=[fake_port],
    ):
        candidates = ac._scan_linux_serial()

    assert len(candidates) == 4
    bauds = {c["baud_rate"] for c in candidates}
    assert bauds == {115200, 57600, 460800, 921600}
    assert all(c["transport"] == "serial" for c in candidates)
    assert all(c["serial_port"] == "/dev/ttyUSB0" for c in candidates)


def test_scan_linux_serial_non_usb_device_tries_two_bauds():
    fake_port = SimpleNamespace(device="/dev/ttyAMA0", hwid="")
    with patch(
        "app.modules.drone_control.auto_connector.serial.tools.list_ports.comports",
        return_value=[fake_port],
    ):
        candidates = ac._scan_linux_serial()

    assert len(candidates) == 2
    bauds = {c["baud_rate"] for c in candidates}
    assert bauds == {57600, 115200}


def test_scan_linux_serial_no_ports_returns_empty():
    with patch(
        "app.modules.drone_control.auto_connector.serial.tools.list_ports.comports",
        return_value=[],
    ):
        candidates = ac._scan_linux_serial()

    assert candidates == []


# ══════════════════════════════════════════════════════════════════════
# _build_candidates
# ══════════════════════════════════════════════════════════════════════

@pytest.fixture
def usb_on(monkeypatch):
    """AUTOCONNECT_USB=true — the legacy behaviour these tests describe."""
    monkeypatch.setattr(ac, "_usb_autoconnect_enabled", lambda: True)


def test_build_candidates_bridge_connected_is_first(usb_on):
    bridge = {"connected": True, "active_port": "COM5", "tcp_port": 5762, "baud": 115200}
    with patch(
        "app.modules.drone_control.auto_connector.serial.tools.list_ports.comports",
        return_value=[],
    ):
        candidates = ac._build_candidates(bridge)

    assert candidates[0]["transport"] == "tcp"
    assert candidates[0]["host"] == "host.docker.internal"
    assert candidates[0]["port"] == 5762
    assert candidates[0]["baud_rate"] == 115200
    assert "COM5" in candidates[0]["label"]
    # static fallback candidates still present after the bridge entry
    assert len(candidates) > 1


def test_build_candidates_bridge_none_no_bridge_entry(usb_on):
    with patch(
        "app.modules.drone_control.auto_connector.serial.tools.list_ports.comports",
        return_value=[],
    ):
        candidates = ac._build_candidates(None)

    # None of the candidates should be the bridge-derived tcp entry (label prefix "bridge:")
    assert all(not c["label"].startswith("bridge:") for c in candidates)
    # Static fallback list (2x tcp + 2x inbound udp) must still be present.
    # UDP 14560 is reserved for simulator -> external GCS broadcast and must
    # stay free for Mission Planner/QGC to bind on the host.
    assert len(candidates) == 4
    assert all(c["label"] != "udp:14560" for c in candidates)


def test_build_candidates_bridge_present_but_not_connected_no_bridge_entry(usb_on):
    bridge = {"connected": False}
    with patch(
        "app.modules.drone_control.auto_connector.serial.tools.list_ports.comports",
        return_value=[],
    ):
        candidates = ac._build_candidates(bridge)

    assert all(not c["label"].startswith("bridge:") for c in candidates)
    assert len(candidates) == 4
    assert all(c["label"] != "udp:14560" for c in candidates)


def test_build_candidates_includes_serial_scan_results(usb_on):
    fake_port = SimpleNamespace(device="/dev/ttyUSB0", hwid="USB")
    with patch(
        "app.modules.drone_control.auto_connector.serial.tools.list_ports.comports",
        return_value=[fake_port],
    ):
        candidates = ac._build_candidates(None)

    serial_candidates = [c for c in candidates if c["transport"] == "serial"]
    assert len(serial_candidates) == 4
    # static tcp/udp fallback list (4 entries) + 4 serial = 8
    assert len(candidates) == 8


# ── USB auto-connect is OFF by default: USB connects only when the operator asks ──

def test_usb_autoconnect_setting_defaults_off():
    with patch("app.config.get_settings", return_value=SimpleNamespace(autoconnect_usb=False)):
        assert ac._usb_autoconnect_enabled() is False
    with patch("app.config.get_settings", return_value=SimpleNamespace(autoconnect_usb=True)):
        assert ac._usb_autoconnect_enabled() is True


def test_usb_off_leaves_out_bridge_serial_and_bridge_backed_tcp(monkeypatch):
    monkeypatch.setattr(ac, "_usb_autoconnect_enabled", lambda: False)
    bridge = {"connected": True, "active_port": "COM5", "tcp_port": 5762, "baud": 460800}
    fake_port = SimpleNamespace(device="/dev/ttyUSB0", hwid="USB")
    with patch(
        "app.modules.drone_control.auto_connector.serial.tools.list_ports.comports",
        return_value=[fake_port],
    ):
        candidates = ac._build_candidates(bridge)

    assert all(not c["label"].startswith("bridge:") for c in candidates)
    assert all(c["transport"] != "serial" for c in candidates)
    # the Windows COM bridge's TCP ports are USB too — never probed in the background
    assert all(c["label"] not in ("tcp:host:5762", "tcp:host:5760") for c in candidates)
    # network (SITL / forwarded UDP) candidates are untouched
    assert {c["label"] for c in candidates} == {"udp:14550", "udp:14551"}


@pytest.mark.asyncio
@pytest.mark.parametrize("usb_enabled, expect_lookup", [(False, False), (True, True)])
async def test_cable_plug_in_triggers_a_connect_only_when_usb_autoconnect_is_on(
        monkeypatch, usb_enabled, expect_lookup):
    """A newly detected COM port must not start a background connect when USB auto-connect
    is off — it would hold the bridge's single client slot and block the operator's own
    Connect. The retry timer never elapses here, so the plug-in is the only possible trigger."""
    monkeypatch.setattr(ac, "_usb_autoconnect_enabled", lambda: usb_enabled)
    monkeypatch.setattr(ac, "STARTUP_DELAY", 0)
    monkeypatch.setattr(ac, "RETRY_INTERVAL", 1e12)
    monkeypatch.setattr(ac, "BRIDGE_POLL_INTERVAL", 0.01)
    plugged = {"connected": True, "active_port": "COM5", "tcp_port": 5762, "baud": 460800}
    monkeypatch.setattr(ac, "_get_bridge_status", lambda: plugged)
    get_unconnected = AsyncMock(return_value=[])
    monkeypatch.setattr(ac, "_get_unconnected_drones", get_unconnected)

    task = asyncio.create_task(ac.run_auto_connector(MagicMock()))
    await asyncio.sleep(0.3)
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)

    assert (get_unconnected.await_count > 0) is expect_lookup


# ══════════════════════════════════════════════════════════════════════
# _connect_drone
# ══════════════════════════════════════════════════════════════════════

_CANDIDATES = [
    {"transport": "tcp", "host": "h1", "port": 1, "serial_port": "/dev/ttyUSB0",
     "baud_rate": 57600, "label": "candidate-1"},
    {"transport": "tcp", "host": "h2", "port": 2, "serial_port": "/dev/ttyUSB0",
     "baud_rate": 57600, "label": "candidate-2"},
]


@pytest.mark.asyncio
async def test_connect_drone_success_all_candidates_probed_concurrently():
    """All candidates are probed concurrently (see _connect_drone docstring) —
    when every candidate succeeds, the first one to complete wins and every
    candidate still gets a real connect() attempt with the right kwargs."""
    with patch(
        "app.modules.drone_control.mavlink_manager.mavlink_manager.connect",
        new=AsyncMock(return_value=True),
    ) as mock_connect:
        result = await ac._connect_drone(1, "D1", _CANDIDATES)

    assert result is True
    assert mock_connect.await_count == len(_CANDIDATES)
    for _, kwargs in mock_connect.call_args_list:
        assert kwargs["drone_id"] == 1
        assert kwargs["call_sign"] == "D1"
        assert kwargs["heartbeat_timeout"] == ac.HEARTBEAT_TIMEOUT


@pytest.mark.asyncio
async def test_connect_drone_falls_through_to_second_candidate():
    """First candidate returns False, second succeeds — both must be tried."""
    mock_connect = AsyncMock(side_effect=[False, True])
    with patch(
        "app.modules.drone_control.mavlink_manager.mavlink_manager.connect",
        new=mock_connect,
    ):
        result = await ac._connect_drone(1, "D1", _CANDIDATES)

    assert result is True
    assert mock_connect.await_count == 2


@pytest.mark.asyncio
async def test_connect_drone_exception_on_candidate_is_swallowed_and_retried():
    """A raised exception on one candidate must not abort — next candidate is tried."""
    mock_connect = AsyncMock(side_effect=[ConnectionRefusedError("nope"), True])
    with patch(
        "app.modules.drone_control.mavlink_manager.mavlink_manager.connect",
        new=mock_connect,
    ):
        result = await ac._connect_drone(1, "D1", _CANDIDATES)

    assert result is True
    assert mock_connect.await_count == 2


@pytest.mark.asyncio
async def test_connect_drone_all_candidates_fail_returns_false():
    with patch(
        "app.modules.drone_control.mavlink_manager.mavlink_manager.connect",
        new=AsyncMock(return_value=False),
    ) as mock_connect:
        result = await ac._connect_drone(1, "D1", _CANDIDATES)

    assert result is False
    assert mock_connect.await_count == len(_CANDIDATES)


@pytest.mark.asyncio
async def test_connect_drone_no_candidates_returns_false_without_calling_connect():
    with patch(
        "app.modules.drone_control.mavlink_manager.mavlink_manager.connect",
        new=AsyncMock(return_value=True),
    ) as mock_connect:
        result = await ac._connect_drone(1, "D1", [])

    assert result is False
    mock_connect.assert_not_awaited()


# ══════════════════════════════════════════════════════════════════════
# _get_unconnected_drones
# ══════════════════════════════════════════════════════════════════════

def _fake_session_factory(all_drones):
    """Build a session_factory() callable mimicking async_sessionmaker's contract."""

    class _FakeResult:
        def scalars(self):
            m = MagicMock()
            m.all.return_value = all_drones
            return m

    class _FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def execute(self, stmt):
            return _FakeResult()

    def _factory():
        return _FakeSession()

    return _factory


@pytest.mark.asyncio
async def test_get_unconnected_drones_excludes_live_connections():
    from app.modules.drone_control.mavlink_manager import mavlink_manager

    drone_connected = SimpleNamespace(id=1, call_sign="D1", status="active")
    drone_free = SimpleNamespace(id=2, call_sign="D2", status="active")

    fake_conn = MagicMock()
    fake_conn.connected = True
    mavlink_manager._connections[1] = fake_conn

    session_factory = _fake_session_factory([drone_connected, drone_free])
    result = await ac._get_unconnected_drones(session_factory)

    assert [d.id for d in result] == [2]


@pytest.mark.asyncio
async def test_get_unconnected_drones_skips_operator_disconnected(monkeypatch):
    """A deliberate Disconnect must not be undone by the background retry loop."""
    from app.modules.drone_control.mavlink_manager import mavlink_manager

    monkeypatch.setattr(mavlink_manager, "operator_disconnected", {2})
    drones = [SimpleNamespace(id=1, call_sign="D1", status="active"),
              SimpleNamespace(id=2, call_sign="D2", status="active")]

    result = await ac._get_unconnected_drones(_fake_session_factory(drones))

    assert [d.id for d in result] == [1]


@pytest.mark.asyncio
async def test_get_unconnected_drones_includes_stale_disconnected_entry():
    """A connection dict entry that exists but is marked connected=False still counts as unconnected."""
    from app.modules.drone_control.mavlink_manager import mavlink_manager

    drone = SimpleNamespace(id=3, call_sign="D3", status="active")
    stale_conn = MagicMock()
    stale_conn.connected = False
    mavlink_manager._connections[3] = stale_conn

    session_factory = _fake_session_factory([drone])
    result = await ac._get_unconnected_drones(session_factory)

    assert [d.id for d in result] == [3]


@pytest.mark.asyncio
async def test_get_unconnected_drones_no_drones_returns_empty():
    session_factory = _fake_session_factory([])
    result = await ac._get_unconnected_drones(session_factory)

    assert result == []


# ══════════════════════════════════════════════════════════════════════
# run_auto_connector — the background loop
# ══════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_run_auto_connector_connects_unconnected_drone_then_stops():
    """
    First loop iteration: bridge reports cable just plugged in, one unconnected
    drone exists -> _connect_drone must be invoked for it. The loop is stopped
    by making the second asyncio.sleep call raise CancelledError, simulating
    the task being cancelled on app shutdown.
    """
    sleep_calls = []

    async def fake_sleep(seconds):
        sleep_calls.append(seconds)
        if len(sleep_calls) >= 2:
            raise asyncio.CancelledError()

    fake_drone = SimpleNamespace(id=7, call_sign="D7", status="active")
    fake_bridge = {"connected": True, "active_port": "COM3", "tcp_port": 5762}

    connect_mock = AsyncMock(return_value=True)
    unconnected_mock = AsyncMock(return_value=[fake_drone])

    with patch.object(ac.asyncio, "sleep", new=fake_sleep), \
         patch.object(ac, "_get_bridge_status", return_value=fake_bridge), \
         patch.object(ac, "_get_unconnected_drones", new=unconnected_mock), \
         patch.object(ac, "_connect_drone", new=connect_mock):
        await ac.run_auto_connector(session_factory=MagicMock())

    assert sleep_calls[0] == ac.STARTUP_DELAY
    unconnected_mock.assert_awaited_once()
    connect_mock.assert_awaited_once_with(7, "D7", connect_mock.call_args.args[2])


@pytest.mark.asyncio
async def test_run_auto_connector_no_drone_instances_skips_connect():
    """No drones in the DB at all -> _connect_drone is never called; loop must not crash."""
    sleep_calls = []

    async def fake_sleep(seconds):
        sleep_calls.append(seconds)
        if len(sleep_calls) >= 2:
            raise asyncio.CancelledError()

    fake_bridge = {"connected": True, "active_port": "COM3", "tcp_port": 5762}
    connect_mock = AsyncMock(return_value=True)
    unconnected_mock = AsyncMock(return_value=[])

    with patch.object(ac.asyncio, "sleep", new=fake_sleep), \
         patch.object(ac, "_get_bridge_status", return_value=fake_bridge), \
         patch.object(ac, "_get_unconnected_drones", new=unconnected_mock), \
         patch.object(ac, "_connect_drone", new=connect_mock):
        await ac.run_auto_connector(session_factory=MagicMock())

    connect_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_run_auto_connector_cycle_error_is_logged_and_loop_continues():
    """
    An unexpected exception inside the loop body (e.g. DB connection blip)
    must be caught, logged, and NOT propagate — the loop keeps running until
    cancelled on the following cycle.
    """
    sleep_calls = []

    async def fake_sleep(seconds):
        sleep_calls.append(seconds)
        if len(sleep_calls) >= 2:
            raise asyncio.CancelledError()

    with patch.object(ac.asyncio, "sleep", new=fake_sleep), \
         patch.object(ac, "_get_bridge_status", side_effect=RuntimeError("boom")):
        # Must not raise despite _get_bridge_status blowing up on every cycle.
        await ac.run_auto_connector(session_factory=MagicMock())

    assert len(sleep_calls) == 2


@pytest.mark.asyncio
async def test_run_auto_connector_cancelled_during_startup_delay_stops_cleanly():
    async def fake_sleep(seconds):
        raise asyncio.CancelledError()

    with patch.object(ac.asyncio, "sleep", new=fake_sleep):
        # Should return normally (CancelledError is only re-raised by the
        # try/except inside the while loop; a cancellation during the initial
        # startup sleep propagates up as a normal asyncio cancellation, which
        # is the expected behaviour for an asyncio.Task being cancelled).
        with pytest.raises(asyncio.CancelledError):
            await ac.run_auto_connector(session_factory=MagicMock())
