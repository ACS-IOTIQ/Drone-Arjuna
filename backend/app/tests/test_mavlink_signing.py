"""MAVLink 2 signing: signed frames accepted; unsigned / wrong-key frames dropped."""
import socket
import time

import app  # noqa: F401  (sets MAVLINK20 before pymavlink is imported)
import pytest
from pymavlink import mavutil

from app.config import Settings
from app.utils import mavlink_utils
from app.utils.mavlink_utils import _allow_unsigned, apply_signing

KEY = bytes.fromhex("11" * 32)
OTHER_KEY = bytes.fromhex("22" * 32)


def _free_udp_port() -> int:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _roundtrip(rx_key, tx_key) -> bool:
    port = _free_udp_port()
    rx = mavutil.mavlink_connection(f"udpin:127.0.0.1:{port}", source_system=255)
    tx = mavutil.mavlink_connection(f"udpout:127.0.0.1:{port}", source_system=1)
    if rx_key:
        rx.setup_signing(rx_key, sign_outgoing=True, allow_unsigned_callback=_allow_unsigned)
    if tx_key:
        tx.setup_signing(tx_key, sign_outgoing=True)
    try:
        for _ in range(3):
            tx.mav.heartbeat_send(mavutil.mavlink.MAV_TYPE_QUADROTOR,
                                  mavutil.mavlink.MAV_AUTOPILOT_ARDUPILOTMEGA, 0, 0, 0)
            time.sleep(0.05)
        return rx.recv_match(type="HEARTBEAT", blocking=True, timeout=1.0) is not None
    finally:
        rx.close()
        tx.close()


def test_app_forces_mavlink2():
    link = mavutil.mavlink_connection("udpout:127.0.0.1:14599", source_system=1)
    assert link.mavlink20() is True
    link.close()


def test_signed_frames_accepted():
    assert _roundtrip(KEY, KEY) is True


def test_unsigned_frames_rejected_when_signing_on():
    assert _roundtrip(KEY, None) is False


def test_wrong_key_rejected():
    assert _roundtrip(KEY, OTHER_KEY) is False


def test_radio_status_allowed_unsigned_but_not_other_messages():
    assert _allow_unsigned(None, mavutil.mavlink.MAVLINK_MSG_ID_RADIO_STATUS) is True
    assert _allow_unsigned(None, mavutil.mavlink.MAVLINK_MSG_ID_COMMAND_LONG) is False


def test_apply_signing_noop_without_key(monkeypatch):
    class _S:
        mavlink_signing_key = ""
    monkeypatch.setattr("app.config.get_settings", lambda: _S())
    assert apply_signing(object()) is False


def test_apply_signing_enables_with_key(monkeypatch):
    class _S:
        mavlink_signing_key = "11" * 32

    calls = {}

    class _Link:
        def setup_signing(self, key, **kw):
            calls["key"], calls["kw"] = key, kw

    monkeypatch.setattr("app.config.get_settings", lambda: _S())
    assert apply_signing(_Link()) is True
    assert calls["key"] == KEY and calls["kw"]["sign_outgoing"] is True


@pytest.mark.parametrize("bad", ["zz" * 32, "11" * 16, "11" * 33])
def test_config_rejects_malformed_signing_key(bad):
    with pytest.raises(ValueError):
        Settings(secret_key="k" * 40, minio_user="u_ok_1", minio_password="p_ok_12345",
                 mavlink_signing_key=bad, _env_file=None)
