"""
MAVLinkBroadcaster Unit Tests
=============================
Dedicated coverage for app/modules/drone_control/mavlink_broadcaster.py.

Prior to this file, mavlink_broadcaster.py had zero direct test coverage
(it is only invoked incidentally as a side effect of telemetry_processor
tests, and even there its `send()` is what's exercised, if at all).

These tests cover:
  - registering a drone link lazily on first send() (_get_link)
  - removing a drone (remove()) closing the link and clearing handlers
  - sending telemetry to a registered "listener" (the underlying MAVLink
    link's mav.*_send methods act as the outbound sink here — there is
    no separate listener registry, the UDP link itself is the sink)
  - the command_handler hook: set_command_handler / clear_command_handler,
    and _handle_incoming dispatching set_home / arm_disarm actions
  - graceful no-op behaviour when no handler is registered, and when the
    link can't be opened / send fails (fire-and-forget contract)
"""
import pytest
from unittest.mock import MagicMock, patch

from app.modules.drone_control.mavlink_broadcaster import MAVLinkBroadcaster
from pymavlink import mavutil

_DRONE_ID = 55
_SYS_ID = 3


@pytest.fixture
def fake_link():
    """A MagicMock standing in for the object mavutil.mavlink_connection() returns."""
    link = MagicMock()
    link.mav = MagicMock()
    link.recv_match = MagicMock(return_value=None)  # no incoming traffic by default
    return link


@pytest.fixture
def broadcaster():
    return MAVLinkBroadcaster(target="127.0.0.1:14560")


# ═══════════════════════════════════════════════════════════════════════
# Link registration / removal
# ═══════════════════════════════════════════════════════════════════════

class TestLinkLifecycle:

    def test_get_link_opens_and_caches_link(self, broadcaster, fake_link):
        with patch("app.modules.drone_control.mavlink_broadcaster.mavutil.mavlink_connection",
                   return_value=fake_link) as mock_conn:
            link1 = broadcaster._get_link(_DRONE_ID, _SYS_ID)
            link2 = broadcaster._get_link(_DRONE_ID, _SYS_ID)

            assert link1 is fake_link
            assert link2 is fake_link
            # Only opened once — second call hits the cache
            mock_conn.assert_called_once()
            _, kwargs = mock_conn.call_args
            assert kwargs["source_system"] == _SYS_ID
            assert kwargs["source_component"] == 1

    def test_get_link_uses_configured_target(self, broadcaster, fake_link):
        with patch("app.modules.drone_control.mavlink_broadcaster.mavutil.mavlink_connection",
                   return_value=fake_link) as mock_conn:
            broadcaster._get_link(_DRONE_ID, _SYS_ID)
            args, _ = mock_conn.call_args
            assert args[0] == "udpout:127.0.0.1:14560"

    def test_get_link_returns_none_and_does_not_raise_on_failure(self, broadcaster):
        """If mavutil.mavlink_connection raises, _get_link must swallow it and return None."""
        with patch("app.modules.drone_control.mavlink_broadcaster.mavutil.mavlink_connection",
                   side_effect=OSError("port in use")):
            link = broadcaster._get_link(_DRONE_ID, _SYS_ID)
            assert link is None

    def test_remove_closes_link_and_clears_bookkeeping(self, broadcaster, fake_link):
        with patch("app.modules.drone_control.mavlink_broadcaster.mavutil.mavlink_connection",
                   return_value=fake_link):
            broadcaster._get_link(_DRONE_ID, _SYS_ID)
        broadcaster.set_command_handler(_DRONE_ID, MagicMock())
        broadcaster._last_heartbeat[_DRONE_ID] = 123.0

        broadcaster.remove(_DRONE_ID)

        fake_link.close.assert_called_once()
        assert _DRONE_ID not in broadcaster._links
        assert _DRONE_ID not in broadcaster._last_heartbeat
        assert _DRONE_ID not in broadcaster._command_handlers

    def test_remove_unknown_drone_is_noop(self, broadcaster):
        """Removing a drone that was never registered must not raise."""
        broadcaster.remove(9999)

    def test_remove_swallows_close_exception(self, broadcaster, fake_link):
        fake_link.close.side_effect = RuntimeError("already closed")
        with patch("app.modules.drone_control.mavlink_broadcaster.mavutil.mavlink_connection",
                   return_value=fake_link):
            broadcaster._get_link(_DRONE_ID, _SYS_ID)
        broadcaster.remove(_DRONE_ID)  # must not raise


# ═══════════════════════════════════════════════════════════════════════
# Command handler registration
# ═══════════════════════════════════════════════════════════════════════

class TestCommandHandlerRegistration:

    def test_set_command_handler_registers_callback(self, broadcaster):
        handler = MagicMock()
        broadcaster.set_command_handler(_DRONE_ID, handler)
        assert broadcaster._command_handlers[_DRONE_ID] is handler

    def test_clear_command_handler_removes_callback(self, broadcaster):
        handler = MagicMock()
        broadcaster.set_command_handler(_DRONE_ID, handler)
        broadcaster.clear_command_handler(_DRONE_ID)
        assert _DRONE_ID not in broadcaster._command_handlers

    def test_clear_command_handler_unknown_drone_is_noop(self, broadcaster):
        broadcaster.clear_command_handler(12345)  # never registered


# ═══════════════════════════════════════════════════════════════════════
# send() — telemetry relay to the outbound MAVLink link
# ═══════════════════════════════════════════════════════════════════════

class TestSend:

    _STATE = {
        "lat": 12.9716, "lon": 77.5946,
        "alt_msl": 800.0, "alt_agl": 50.0,
        "vx": 1.0, "vy": 0.0, "vz": 0.0, "heading": 90.0,
        "roll_deg": 1.0, "pitch_deg": 2.0, "yaw_deg": 3.0,
        "airspeed_ms": 10.0, "groundspeed_ms": 9.5,
        "throttle_pct": 50, "climb_rate_ms": 0.1,
        "cpu_load_pct": 12.0, "battery_voltage_v": 22.0,
        "battery_current_a": 5.0, "battery_remaining_pct": 80,
        "gps_fix_type": "3D Fix", "gps_hdop": 1.0, "gps_satellites": 9,
        "is_armed": True,
    }

    def test_send_with_no_listener_registered_does_not_error(self, broadcaster):
        """No link can be opened (nothing listening) — send() must be a silent no-op."""
        with patch("app.modules.drone_control.mavlink_broadcaster.mavutil.mavlink_connection",
                   side_effect=OSError("no listener")):
            broadcaster.send(_DRONE_ID, _SYS_ID, self._STATE)  # must not raise

    def test_send_sends_heartbeat_position_attitude_hud_sysstatus_gps(self, broadcaster, fake_link):
        with patch("app.modules.drone_control.mavlink_broadcaster.mavutil.mavlink_connection",
                   return_value=fake_link):
            broadcaster.send(_DRONE_ID, _SYS_ID, self._STATE)

        fake_link.mav.heartbeat_send.assert_called_once()
        fake_link.mav.global_position_int_send.assert_called_once()
        fake_link.mav.attitude_send.assert_called_once()
        fake_link.mav.vfr_hud_send.assert_called_once()
        fake_link.mav.sys_status_send.assert_called_once()
        fake_link.mav.gps_raw_int_send.assert_called_once()

    def test_send_heartbeat_reflects_armed_state(self, broadcaster, fake_link):
        with patch("app.modules.drone_control.mavlink_broadcaster.mavutil.mavlink_connection",
                   return_value=fake_link):
            broadcaster.send(_DRONE_ID, _SYS_ID, {**self._STATE, "is_armed": True})
        args = fake_link.mav.heartbeat_send.call_args[0]
        assert args[2] == mavutil.mavlink.MAV_MODE_FLAG_SAFETY_ARMED

    def test_send_heartbeat_reflects_disarmed_state(self, broadcaster, fake_link):
        with patch("app.modules.drone_control.mavlink_broadcaster.mavutil.mavlink_connection",
                   return_value=fake_link):
            broadcaster.send(_DRONE_ID, _SYS_ID, {**self._STATE, "is_armed": False})
        args = fake_link.mav.heartbeat_send.call_args[0]
        assert args[2] == 0

    def test_send_throttles_heartbeat_to_1hz(self, broadcaster, fake_link):
        """A second send() within the same second must not re-send HEARTBEAT."""
        with patch("app.modules.drone_control.mavlink_broadcaster.mavutil.mavlink_connection",
                   return_value=fake_link):
            broadcaster.send(_DRONE_ID, _SYS_ID, self._STATE)
            broadcaster.send(_DRONE_ID, _SYS_ID, self._STATE)

        assert fake_link.mav.heartbeat_send.call_count == 1
        # Position etc. still sent every call
        assert fake_link.mav.global_position_int_send.call_count == 2

    def test_send_missing_state_fields_uses_defaults_and_does_not_raise(self, broadcaster, fake_link):
        """An incomplete state dict must fall back to defaults, never KeyError."""
        with patch("app.modules.drone_control.mavlink_broadcaster.mavutil.mavlink_connection",
                   return_value=fake_link):
            broadcaster.send(_DRONE_ID, _SYS_ID, {})  # empty state
        fake_link.mav.global_position_int_send.assert_called_once()

    def test_send_swallows_exceptions_from_link(self, broadcaster, fake_link):
        """If the underlying mav.*_send raises, send() must log and not propagate."""
        fake_link.mav.global_position_int_send.side_effect = RuntimeError("socket gone")
        with patch("app.modules.drone_control.mavlink_broadcaster.mavutil.mavlink_connection",
                   return_value=fake_link):
            broadcaster.send(_DRONE_ID, _SYS_ID, self._STATE)  # must not raise

    def test_send_drains_incoming_commands_before_sending(self, broadcaster, fake_link):
        fake_link.recv_match = MagicMock(return_value=None)
        with patch("app.modules.drone_control.mavlink_broadcaster.mavutil.mavlink_connection",
                   return_value=fake_link):
            broadcaster.send(_DRONE_ID, _SYS_ID, self._STATE)
        fake_link.recv_match.assert_called_with(blocking=False)


# ═══════════════════════════════════════════════════════════════════════
# _handle_incoming — COMMAND_LONG dispatch to the registered handler
# ═══════════════════════════════════════════════════════════════════════

def _make_command_long(command, param1=0.0, param5=0.0, param6=0.0, param7=0.0):
    msg = MagicMock()
    msg.get_type.return_value = "COMMAND_LONG"
    msg.command = command
    msg.param1 = param1
    msg.param5 = param5
    msg.param6 = param6
    msg.param7 = param7
    return msg


class TestHandleIncomingCommands:

    def test_no_handler_registered_still_acks_command(self, broadcaster, fake_link):
        """With no command handler registered, unknown/actionable commands are still ack'd."""
        msg = _make_command_long(mavutil.mavlink.MAV_CMD_COMPONENT_ARM_DISARM, param1=1.0)
        broadcaster._handle_incoming(_DRONE_ID, fake_link, msg)
        fake_link.mav.command_ack_send.assert_called_once_with(
            msg.command, mavutil.mavlink.MAV_RESULT_ACCEPTED
        )

    def test_arm_disarm_dispatches_to_handler(self, broadcaster, fake_link):
        handler = MagicMock()
        broadcaster.set_command_handler(_DRONE_ID, handler)
        msg = _make_command_long(mavutil.mavlink.MAV_CMD_COMPONENT_ARM_DISARM, param1=1.0)

        broadcaster._handle_incoming(_DRONE_ID, fake_link, msg)

        handler.assert_called_once_with("arm", {})
        fake_link.mav.command_ack_send.assert_called_once()

    def test_disarm_dispatches_to_handler(self, broadcaster, fake_link):
        handler = MagicMock()
        broadcaster.set_command_handler(_DRONE_ID, handler)
        msg = _make_command_long(mavutil.mavlink.MAV_CMD_COMPONENT_ARM_DISARM, param1=0.0)

        broadcaster._handle_incoming(_DRONE_ID, fake_link, msg)

        handler.assert_called_once_with("disarm", {})

    def test_set_home_dispatches_to_handler_with_params(self, broadcaster, fake_link):
        handler = MagicMock()
        broadcaster.set_command_handler(_DRONE_ID, handler)
        msg = _make_command_long(
            mavutil.mavlink.MAV_CMD_DO_SET_HOME,
            param1=0.0, param5=12.5, param6=77.5, param7=100.0,
        )

        broadcaster._handle_incoming(_DRONE_ID, fake_link, msg)

        handler.assert_called_once_with("set_home", {
            "use_current": False, "lat": 12.5, "lon": 77.5, "alt": 100.0,
        })

    def test_set_home_use_current_flag(self, broadcaster, fake_link):
        handler = MagicMock()
        broadcaster.set_command_handler(_DRONE_ID, handler)
        msg = _make_command_long(mavutil.mavlink.MAV_CMD_DO_SET_HOME, param1=1.0)

        broadcaster._handle_incoming(_DRONE_ID, fake_link, msg)

        assert handler.call_args[0][1]["use_current"] is True

    def test_non_actionable_command_long_is_acked_as_noop(self, broadcaster, fake_link):
        """A COMMAND_LONG not in _ACTIONABLE_COMMANDS is still ack'd (no handler call)."""
        handler = MagicMock()
        broadcaster.set_command_handler(_DRONE_ID, handler)
        msg = _make_command_long(999999)  # not a recognized/actionable command id

        broadcaster._handle_incoming(_DRONE_ID, fake_link, msg)

        handler.assert_not_called()
        fake_link.mav.command_ack_send.assert_called_once_with(
            999999, mavutil.mavlink.MAV_RESULT_ACCEPTED
        )

    def test_non_command_long_message_is_ignored(self, broadcaster, fake_link):
        """Message types other than COMMAND_LONG must not trigger any ack or dispatch."""
        msg = MagicMock()
        msg.get_type.return_value = "HEARTBEAT"
        broadcaster._handle_incoming(_DRONE_ID, fake_link, msg)
        fake_link.mav.command_ack_send.assert_not_called()

    def test_handler_exception_does_not_prevent_ack(self, broadcaster, fake_link):
        """If the registered handler raises, the command must still be ack'd."""
        handler = MagicMock(side_effect=RuntimeError("simulator exploded"))
        broadcaster.set_command_handler(_DRONE_ID, handler)
        msg = _make_command_long(mavutil.mavlink.MAV_CMD_COMPONENT_ARM_DISARM, param1=1.0)

        broadcaster._handle_incoming(_DRONE_ID, fake_link, msg)  # must not raise

        fake_link.mav.command_ack_send.assert_called_once()

    def test_drain_commands_processes_multiple_then_stops(self, broadcaster, fake_link):
        """_drain_commands must loop until recv_match returns None."""
        msg1 = _make_command_long(mavutil.mavlink.MAV_CMD_COMPONENT_ARM_DISARM, param1=1.0)
        fake_link.recv_match.side_effect = [msg1, None]

        broadcaster._drain_commands(_DRONE_ID, fake_link)

        fake_link.mav.command_ack_send.assert_called_once()
        assert fake_link.recv_match.call_count == 2

    def test_drain_commands_swallows_recv_exceptions(self, broadcaster, fake_link):
        fake_link.recv_match.side_effect = RuntimeError("socket error")
        broadcaster._drain_commands(_DRONE_ID, fake_link)  # must not raise


# ═══════════════════════════════════════════════════════════════════════
# Module-level singleton sanity
# ═══════════════════════════════════════════════════════════════════════

def test_module_level_singleton_exists():
    from app.modules.drone_control.mavlink_broadcaster import mavlink_broadcaster
    assert isinstance(mavlink_broadcaster, MAVLinkBroadcaster)
