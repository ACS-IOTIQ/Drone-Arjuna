"""
CommandController Unit Tests
============================
Exercises CommandController's actual validation / dispatch / ack logic
directly, in isolation from the API layer (no HTTP, no DB, no real MAVLink).

Covers:
  - _validate(): arm / disarm / takeoff / set_mode / velocity / goto /
    emergency_stop rules
  - send(): denied path (no dispatch), successful no-ack command path,
    arm/disarm ack-collision guard
  - handle_ack(): resolves pending futures, no-op when nothing pending
  - get_history(): ordering + limit slicing
"""
import asyncio
import pytest
from unittest.mock import MagicMock

from pymavlink import mavutil

from app.modules.drone_control.command_controller import (
    CommandController,
    CommandResult,
    HISTORY_LIMIT,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_mav() -> MagicMock:
    """Fake pymavlink connection-like object."""
    mav = MagicMock()
    mav.target_system = 1
    mav.target_component = 1
    mav.mode_mapping.return_value = {
        "STABILIZE": 0, "GUIDED": 4, "AUTO": 3, "RTL": 6,
        "LAND": 9, "LOITER": 5, "ALT_HOLD": 2, "SMART_RTL": 21,
    }
    mav.mav = MagicMock()
    return mav


def _state(
    *,
    armed: bool = True,
    mode: str = "GUIDED",
    battery: int = 80,
    gps_fix: str = "3D Fix",
    sats: int = 10,
) -> dict:
    return {
        "is_armed": armed,
        "flight_mode": mode,
        "battery_remaining_pct": battery,
        "gps_fix_type": gps_fix,
        "gps_satellites": sats,
    }


def _make_controller(state: dict | None = None) -> tuple[CommandController, MagicMock, MagicMock]:
    mav = _make_mav()
    state_manager = MagicMock()
    state_manager.get.return_value = state if state is not None else _state()
    ctrl = CommandController(drone_id=1, mav=mav, state_manager=state_manager)
    return ctrl, mav, state_manager


# ── _validate: arm ────────────────────────────────────────────────────────────

class TestValidateArm:

    def test_arm_denied_when_already_armed(self):
        ctrl, _, _ = _make_controller(_state(armed=True))
        reason = ctrl._validate("arm", {})
        assert reason is not None
        assert "already armed" in reason

    def test_arm_denied_when_battery_low(self):
        ctrl, _, _ = _make_controller(_state(armed=False, battery=10))
        reason = ctrl._validate("arm", {})
        assert reason is not None
        assert "Battery too low" in reason

    def test_arm_denied_when_gps_insufficient_no_fix(self):
        ctrl, _, _ = _make_controller(_state(armed=False, gps_fix="No GPS", sats=10))
        reason = ctrl._validate("arm", {})
        assert reason is not None
        assert "Insufficient GPS" in reason

    def test_arm_denied_when_gps_insufficient_low_sats(self):
        ctrl, _, _ = _make_controller(_state(armed=False, gps_fix="3D Fix", sats=3))
        reason = ctrl._validate("arm", {})
        assert reason is not None
        assert "Insufficient GPS" in reason

    def test_arm_allowed_with_good_state(self):
        ctrl, _, _ = _make_controller(_state(armed=False, battery=80, gps_fix="3D Fix", sats=10))
        reason = ctrl._validate("arm", {})
        assert reason is None


# ── _validate: disarm ─────────────────────────────────────────────────────────

class TestValidateDisarm:

    def test_disarm_denied_when_already_disarmed(self):
        ctrl, _, _ = _make_controller(_state(armed=False))
        reason = ctrl._validate("disarm", {})
        assert reason is not None
        assert "already disarmed" in reason

    def test_disarm_allowed_when_armed(self):
        ctrl, _, _ = _make_controller(_state(armed=True, mode="LAND"))
        reason = ctrl._validate("disarm", {})
        assert reason is None

    def test_disarm_allowed_but_warns_in_unsafe_mode(self):
        """Disarm while armed in a non-safe mode is allowed (only logs a warning)."""
        ctrl, _, _ = _make_controller(_state(armed=True, mode="AUTO"))
        reason = ctrl._validate("disarm", {})
        assert reason is None


# ── _validate: takeoff ────────────────────────────────────────────────────────

class TestValidateTakeoff:

    def test_takeoff_denied_when_not_armed(self):
        ctrl, _, _ = _make_controller(_state(armed=False))
        reason = ctrl._validate("takeoff", {"altitude_m": 30})
        assert reason is not None
        assert "must be armed" in reason

    def test_takeoff_denied_altitude_zero(self):
        ctrl, _, _ = _make_controller(_state(armed=True))
        reason = ctrl._validate("takeoff", {"altitude_m": 0})
        assert reason is not None
        assert "between 1 and 500" in reason

    def test_takeoff_denied_altitude_negative(self):
        ctrl, _, _ = _make_controller(_state(armed=True))
        reason = ctrl._validate("takeoff", {"altitude_m": -5})
        assert reason is not None

    def test_takeoff_denied_altitude_too_high(self):
        ctrl, _, _ = _make_controller(_state(armed=True))
        reason = ctrl._validate("takeoff", {"altitude_m": 501})
        assert reason is not None
        assert "between 1 and 500" in reason

    def test_takeoff_denied_altitude_non_numeric(self):
        ctrl, _, _ = _make_controller(_state(armed=True))
        reason = ctrl._validate("takeoff", {"altitude_m": "not-a-number"})
        assert reason is not None
        assert "numeric" in reason

    def test_takeoff_allowed_with_valid_altitude(self):
        ctrl, _, _ = _make_controller(_state(armed=True))
        reason = ctrl._validate("takeoff", {"altitude_m": 30})
        assert reason is None


# ── _validate: set_mode ───────────────────────────────────────────────────────

class TestValidateSetMode:

    def test_set_mode_denied_for_unsupported_mode(self):
        ctrl, _, _ = _make_controller()
        reason = ctrl._validate("set_mode", {"mode": "NOT_A_REAL_MODE"})
        assert reason is not None
        assert "not supported" in reason

    def test_set_mode_denied_missing_mode(self):
        ctrl, _, _ = _make_controller()
        reason = ctrl._validate("set_mode", {})
        assert reason is not None
        assert "requires 'mode'" in reason

    def test_set_mode_allowed_for_supported_mode(self):
        ctrl, _, _ = _make_controller()
        reason = ctrl._validate("set_mode", {"mode": "RTL"})
        assert reason is None


# ── _validate: velocity ───────────────────────────────────────────────────────

class TestValidateVelocity:

    def test_velocity_denied_missing_vx(self):
        ctrl, _, _ = _make_controller()
        reason = ctrl._validate("velocity", {"vy": 1, "vz": 1})
        assert reason is not None
        assert "vx" in reason

    def test_velocity_denied_missing_vy(self):
        ctrl, _, _ = _make_controller()
        reason = ctrl._validate("velocity", {"vx": 1, "vz": 1})
        assert reason is not None
        assert "vy" in reason

    def test_velocity_denied_missing_vz(self):
        ctrl, _, _ = _make_controller()
        reason = ctrl._validate("velocity", {"vx": 1, "vy": 1})
        assert reason is not None
        assert "vz" in reason

    def test_velocity_denied_non_numeric(self):
        ctrl, _, _ = _make_controller()
        reason = ctrl._validate("velocity", {"vx": "fast", "vy": 1, "vz": 1})
        assert reason is not None
        assert "numeric" in reason

    def test_velocity_allowed_with_valid_values(self):
        ctrl, _, _ = _make_controller()
        reason = ctrl._validate("velocity", {"vx": 1.0, "vy": -1.0, "vz": 0})
        assert reason is None


# ── _validate: goto ───────────────────────────────────────────────────────────

class TestValidateGoto:

    def test_goto_denied_missing_lat(self):
        ctrl, _, _ = _make_controller()
        reason = ctrl._validate("goto", {"longitude": 77.5})
        assert reason is not None
        assert "latitude" in reason

    def test_goto_denied_missing_lon(self):
        ctrl, _, _ = _make_controller()
        reason = ctrl._validate("goto", {"latitude": 12.9})
        assert reason is not None
        assert "longitude" in reason

    def test_goto_denied_non_numeric(self):
        ctrl, _, _ = _make_controller()
        reason = ctrl._validate("goto", {"latitude": "north", "longitude": 77.5})
        assert reason is not None
        assert "numeric" in reason

    def test_goto_allowed_with_valid_coords(self):
        ctrl, _, _ = _make_controller()
        reason = ctrl._validate("goto", {"latitude": 12.9, "longitude": 77.5})
        assert reason is None

    def test_goto_allowed_with_short_key_names(self):
        ctrl, _, _ = _make_controller()
        reason = ctrl._validate("goto", {"lat": 12.9, "lon": 77.5})
        assert reason is None


# ── _validate: emergency_stop ─────────────────────────────────────────────────

class TestValidateEmergencyStop:

    def test_emergency_stop_always_allowed(self):
        ctrl, _, _ = _make_controller(_state(armed=False, battery=0, gps_fix="No GPS", sats=0))
        reason = ctrl._validate("emergency_stop", {})
        assert reason is None


# ── send(): denied path ───────────────────────────────────────────────────────

class TestSendDeniedPath:

    @pytest.mark.asyncio
    async def test_send_denied_appends_history_without_dispatch(self):
        ctrl, mav, _ = _make_controller(_state(armed=True))  # already armed
        record = await ctrl.send("arm", {})

        assert record.result == CommandResult.DENIED
        assert "already armed" in record.ack_message
        mav.mav.command_long_send.assert_not_called()
        mav.mav.set_mode_send.assert_not_called()

        history = ctrl.get_history()
        assert len(history) == 1
        assert history[0].result == CommandResult.DENIED


# ── send(): successful no-ack command ─────────────────────────────────────────

class TestSendNoAckSuccess:

    @pytest.mark.asyncio
    async def test_send_set_mode_success(self):
        ctrl, mav, _ = _make_controller()
        record = await ctrl.send("set_mode", {"mode": "RTL"})

        assert record.result == CommandResult.ACCEPTED
        mav.mav.set_mode_send.assert_called_once()

        history = ctrl.get_history()
        assert len(history) == 1
        assert history[0].command == "set_mode"
        assert history[0].result == CommandResult.ACCEPTED

    @pytest.mark.asyncio
    async def test_send_rtl_success(self):
        ctrl, mav, _ = _make_controller()
        record = await ctrl.send("rtl", {})

        assert record.result == CommandResult.ACCEPTED
        mav.mav.set_mode_send.assert_called_once()


# ── send(): arm/disarm ack-collision guard ────────────────────────────────────

class TestSendAckCollisionGuard:

    @pytest.mark.asyncio
    async def test_arm_denied_when_prior_ack_pending(self):
        ctrl, mav, _ = _make_controller(_state(armed=False))

        cmd_id = mavutil.mavlink.MAV_CMD_COMPONENT_ARM_DISARM
        loop = asyncio.get_event_loop()
        ctrl._pending[cmd_id] = loop.create_future()

        record = await ctrl.send("arm", {})

        assert record.result == CommandResult.DENIED
        assert "still awaiting acknowledgment" in record.ack_message
        mav.mav.command_long_send.assert_not_called()

        # Clean up the still-pending future to avoid a "never awaited" warning
        ctrl._pending.pop(cmd_id, None).cancel()

    @pytest.mark.asyncio
    async def test_disarm_denied_when_prior_arm_ack_pending(self):
        """arm and disarm share the same mavlink ack id, so one blocks the other."""
        ctrl, mav, _ = _make_controller(_state(armed=True))

        cmd_id = mavutil.mavlink.MAV_CMD_COMPONENT_ARM_DISARM
        loop = asyncio.get_event_loop()
        ctrl._pending[cmd_id] = loop.create_future()

        record = await ctrl.send("disarm", {})

        assert record.result == CommandResult.DENIED
        assert "still awaiting acknowledgment" in record.ack_message
        mav.mav.command_long_send.assert_not_called()

        ctrl._pending.pop(cmd_id, None).cancel()


# ── handle_ack() ───────────────────────────────────────────────────────────

class TestHandleAck:

    def test_handle_ack_resolves_pending_future_accepted(self):
        ctrl, _, _ = _make_controller()
        loop = asyncio.new_event_loop()
        try:
            fut = loop.create_future()
            cmd_id = mavutil.mavlink.MAV_CMD_COMPONENT_ARM_DISARM
            ctrl._pending[cmd_id] = fut

            ctrl.handle_ack(cmd_id, mavutil.mavlink.MAV_RESULT_ACCEPTED)

            assert fut.done()
            assert fut.result() == CommandResult.ACCEPTED
            assert cmd_id not in ctrl._pending
        finally:
            loop.close()

    def test_handle_ack_resolves_pending_future_failed(self):
        ctrl, _, _ = _make_controller()
        loop = asyncio.new_event_loop()
        try:
            fut = loop.create_future()
            cmd_id = mavutil.mavlink.MAV_CMD_NAV_TAKEOFF
            ctrl._pending[cmd_id] = fut

            ctrl.handle_ack(cmd_id, mavutil.mavlink.MAV_RESULT_FAILED)

            assert fut.done()
            assert fut.result() == CommandResult.FAILED
        finally:
            loop.close()

    def test_handle_ack_noop_when_nothing_pending(self):
        ctrl, _, _ = _make_controller()
        # Must not raise even though no future is registered for this id.
        ctrl.handle_ack(mavutil.mavlink.MAV_CMD_COMPONENT_ARM_DISARM,
                         mavutil.mavlink.MAV_RESULT_ACCEPTED)
        assert ctrl._pending == {}

    @pytest.mark.asyncio
    async def test_handle_ack_integrates_with_await_ack_for_arm(self):
        """
        End-to-end: send("arm") starts waiting on a Future; handle_ack()
        resolves it and send() returns with the corresponding result.
        """
        ctrl, mav, _ = _make_controller(_state(armed=False))

        async def _resolve_shortly():
            await asyncio.sleep(0.05)
            ctrl.handle_ack(mavutil.mavlink.MAV_CMD_COMPONENT_ARM_DISARM,
                             mavutil.mavlink.MAV_RESULT_ACCEPTED)

        resolver = asyncio.create_task(_resolve_shortly())
        record = await ctrl.send("arm", {})
        await resolver

        assert record.result == CommandResult.ACCEPTED
        mav.mav.command_long_send.assert_called_once()


# ── get_history() ─────────────────────────────────────────────────────────

class TestGetHistory:

    @pytest.mark.asyncio
    async def test_get_history_returns_most_recent_reversed(self):
        ctrl, _, _ = _make_controller()

        await ctrl.send("set_mode", {"mode": "RTL"})
        await ctrl.send("set_mode", {"mode": "LAND"})
        await ctrl.send("set_mode", {"mode": "LOITER"})

        history = ctrl.get_history(limit=2)
        assert len(history) == 2
        # Most recent first
        assert history[0].params["mode"] == "LOITER"
        assert history[1].params["mode"] == "LAND"

    def test_get_history_never_exceeds_history_limit(self):
        ctrl, _, _ = _make_controller()

        # Directly populate history beyond HISTORY_LIMIT via _append to
        # verify the truncation logic without dispatching real commands.
        from app.modules.drone_control.command_controller import CommandRecord

        for i in range(HISTORY_LIMIT + 10):
            ctrl._append(CommandRecord(drone_id=1, command="noop", params={"i": i}))

        assert len(ctrl._history) == HISTORY_LIMIT
        # Oldest entries should have been dropped (FIFO eviction)
        assert ctrl._history[0].params["i"] == 10
        assert ctrl._history[-1].params["i"] == HISTORY_LIMIT + 9

    def test_get_history_empty_initially(self):
        ctrl, _, _ = _make_controller()
        assert ctrl.get_history() == []
