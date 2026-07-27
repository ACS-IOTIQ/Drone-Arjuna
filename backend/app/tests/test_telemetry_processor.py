"""
TelemetryProcessor Unit Tests
=============================
Dedicated coverage for app/modules/drone_control/telemetry_processor.py's
own core responsibility: parsing MAVLink messages into clean telemetry
dicts, dispatching COMMAND_ACK to the CommandController, relaying state
to the mavlink_broadcaster, and its geofence-check helper in isolation.

Previously this module was only incidentally exercised through the
geofence test files (test_geofence.py, test_geofence_breach_detection.py,
test_geofence_rtl_consumer.py), which focus on breach/recovery behaviour
rather than the per-message-type parsing logic. These tests fill that gap.
"""
import math
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.modules.drone_control.telemetry_processor import TelemetryProcessor
from app.utils.geofence import GeofenceStore

pytestmark = pytest.mark.asyncio

_DRONE_ID = 4242


# ── Fake MAVLink message helpers ────────────────────────────────────────
# Simple attribute-bag classes mirroring the pattern already used in
# test_geofence.py's _PosMsg / _AttMsg fakes.

class _FakeMsg:
    """Base fake MAVLink message: get_type() + get_srcSystem() + arbitrary attrs."""
    _type = "UNKNOWN"
    _src_system = 1

    def get_type(self):
        return self._type

    def get_srcSystem(self):
        return self._src_system


def _make_msg(msg_type, src_system=1, **attrs):
    msg = _FakeMsg()
    msg._type = msg_type
    msg._src_system = src_system
    for k, v in attrs.items():
        setattr(msg, k, v)
    return msg


@pytest.fixture
def processor():
    return TelemetryProcessor()


@pytest.fixture
def state():
    """Mock StateManager recording update() calls and returning a state dict."""
    s = MagicMock()
    s.update = AsyncMock()
    s.get = MagicMock(return_value={"is_armed": False})
    return s


@pytest.fixture(autouse=True)
def _mock_broadcaster():
    """
    process() relays every parsed update to mavlink_broadcaster.send().
    Mock it out so these unit tests never touch a real UDP socket and so
    we can assert on the relay call itself where relevant.
    """
    with patch(
        "app.modules.drone_control.telemetry_processor.mavlink_broadcaster"
    ) as mock_broadcaster:
        mock_broadcaster.send = MagicMock()
        yield mock_broadcaster


# ═══════════════════════════════════════════════════════════════════════
# Per-message-type parsing — direct handler unit tests
# ═══════════════════════════════════════════════════════════════════════

class TestHandlePosition:
    def test_parses_global_position_int(self, processor):
        msg = _make_msg(
            "GLOBAL_POSITION_INT",
            lat=int(12.9716 * 1e7),
            lon=int(77.5946 * 1e7),
            alt=825_000,          # mm
            relative_alt=100_000,  # mm
            hdg=9000,             # centidegrees
            vx=150, vy=-50, vz=25,  # cm/s
        )
        result = processor._handle_position(msg)
        assert result["lat"] == pytest.approx(12.9716)
        assert result["lon"] == pytest.approx(77.5946)
        assert result["alt_msl"] == pytest.approx(825.0)
        assert result["alt_agl"] == pytest.approx(100.0)
        assert result["heading"] == pytest.approx(90.0)
        assert result["vx"] == pytest.approx(1.5)
        assert result["vy"] == pytest.approx(-0.5)
        assert result["vz"] == pytest.approx(0.25)

    def test_missing_field_raises_attribute_error(self, processor):
        """A malformed GLOBAL_POSITION_INT missing a required field must
        surface as an AttributeError rather than silently parsing wrong data."""
        msg = _make_msg("GLOBAL_POSITION_INT", lat=0, lon=0)  # alt etc. missing
        with pytest.raises(AttributeError):
            processor._handle_position(msg)


class TestHandleAttitude:
    def test_parses_attitude_radians_to_degrees(self, processor):
        msg = _make_msg(
            "ATTITUDE",
            roll=math.radians(10.0),
            pitch=math.radians(-5.0),
            yaw=math.radians(180.0),
            rollspeed=0.1, pitchspeed=0.2, yawspeed=0.3,
        )
        result = processor._handle_attitude(msg)
        assert result["roll_deg"] == pytest.approx(10.0)
        assert result["pitch_deg"] == pytest.approx(-5.0)
        assert result["yaw_deg"] == pytest.approx(180.0)
        assert result["rollspeed"] == pytest.approx(0.1)
        assert result["pitchspeed"] == pytest.approx(0.2)
        assert result["yawspeed"] == pytest.approx(0.3)


class TestHandleVfrHud:
    def test_parses_vfr_hud(self, processor):
        msg = _make_msg(
            "VFR_HUD",
            airspeed=12.5, groundspeed=11.0, climb=0.8, throttle=65,
        )
        result = processor._handle_vfr_hud(msg)
        assert result == {
            "airspeed_ms": 12.5,
            "groundspeed_ms": 11.0,
            "climb_rate_ms": 0.8,
            "throttle_pct": 65,
        }


class TestHandleSysStatus:
    def test_parses_sys_status(self, processor):
        msg = _make_msg(
            "SYS_STATUS",
            voltage_battery=22200,  # mV
            current_battery=1500,  # centi-amps
            battery_remaining=77,
            load=350,               # per-mille
        )
        result = processor._handle_sys_status(msg)
        assert result["battery_voltage_v"] == pytest.approx(22.2)
        assert result["battery_current_a"] == pytest.approx(15.0)
        assert result["battery_remaining_pct"] == 77
        assert result["cpu_load_pct"] == pytest.approx(35.0)


class TestHandleGps:
    def test_parses_gps_raw_int(self, processor):
        msg = _make_msg(
            "GPS_RAW_INT",
            fix_type=3, satellites_visible=11, eph=120,
        )
        result = processor._handle_gps(msg)
        assert result["gps_fix_type"] == "3D fix"
        assert result["gps_satellites"] == 11
        assert result["gps_hdop"] == pytest.approx(1.2)

    def test_unknown_fix_type_still_parses(self, processor):
        msg = _make_msg("GPS_RAW_INT", fix_type=99, satellites_visible=0, eph=9999)
        result = processor._handle_gps(msg)
        assert "Unknown" in result["gps_fix_type"]


class TestHandleHeartbeat:
    def test_parses_heartbeat_armed(self, processor):
        from pymavlink import mavutil
        msg = _make_msg(
            "HEARTBEAT",
            custom_mode=4,  # GUIDED for ArduCopter
            autopilot=mavutil.mavlink.MAV_AUTOPILOT_ARDUPILOTMEGA,
            type=mavutil.mavlink.MAV_TYPE_QUADROTOR,
            base_mode=mavutil.mavlink.MAV_MODE_FLAG_SAFETY_ARMED,
            system_status=4,
        )
        result = processor._handle_heartbeat(msg)
        assert result["flight_mode"] == "GUIDED"
        assert result["is_armed"] is True
        assert result["system_status"] == 4

    def test_parses_heartbeat_disarmed(self, processor):
        from pymavlink import mavutil
        msg = _make_msg(
            "HEARTBEAT",
            custom_mode=0,
            autopilot=mavutil.mavlink.MAV_AUTOPILOT_ARDUPILOTMEGA,
            type=mavutil.mavlink.MAV_TYPE_QUADROTOR,
            base_mode=0,
            system_status=3,
        )
        result = processor._handle_heartbeat(msg)
        assert result["flight_mode"] == "STABILIZE"
        assert result["is_armed"] is False


class TestHandleRc:
    def test_parses_rc_channels_rssi(self, processor):
        msg = _make_msg("RC_CHANNELS", rssi=254)
        result = processor._handle_rc(msg)
        assert result == {"rssi": 100}

    def test_unknown_rssi_255_maps_to_zero(self, processor):
        msg = _make_msg("RC_CHANNELS", rssi=255)
        result = processor._handle_rc(msg)
        assert result == {"rssi": 0}


class TestHandleBattery:
    def test_parses_battery_status_valid(self, processor):
        msg = _make_msg("BATTERY_STATUS", battery_remaining=42)
        result = processor._handle_battery(msg)
        assert result == {"battery_remaining_pct": 42}

    def test_negative_battery_remaining_becomes_none(self, processor):
        """battery_remaining == -1 means 'unknown' per MAVLink spec."""
        msg = _make_msg("BATTERY_STATUS", battery_remaining=-1)
        result = processor._handle_battery(msg)
        assert result == {"battery_remaining_pct": None}


# ═══════════════════════════════════════════════════════════════════════
# process() dispatch — routing, state updates, broadcaster relay
# ═══════════════════════════════════════════════════════════════════════

class TestProcessDispatch:

    async def test_unhandled_message_type_is_ignored(self, processor, state, _mock_broadcaster):
        """A message type not present in _HANDLERS must be silently skipped."""
        msg = _make_msg("PARAM_VALUE")
        await processor.process(_DRONE_ID, msg, state)
        state.update.assert_not_called()
        _mock_broadcaster.send.assert_not_called()

    async def test_attitude_message_updates_state_and_broadcasts(self, processor, state, _mock_broadcaster):
        msg = _make_msg(
            "ATTITUDE", src_system=7,
            roll=0.0, pitch=0.0, yaw=0.0,
            rollspeed=0.0, pitchspeed=0.0, yawspeed=0.0,
        )
        await processor.process(_DRONE_ID, msg, state)
        state.update.assert_awaited_once()
        assert state.update.call_args[0][0] == _DRONE_ID
        _mock_broadcaster.send.assert_called_once()
        call_args = _mock_broadcaster.send.call_args[0]
        assert call_args[0] == _DRONE_ID

    async def test_broadcaster_relay_uses_message_source_system(self, processor, state, _mock_broadcaster):
        """send() must be called with msg.get_srcSystem(), not a hardcoded id."""
        msg = _make_msg(
            "VFR_HUD",
            airspeed=1.0, groundspeed=1.0, climb=0.0, throttle=0,
        )
        msg._src_system = 55
        await processor.process(_DRONE_ID, msg, state)
        _mock_broadcaster.send.assert_called_once_with(_DRONE_ID, 55, state.get.return_value)

    async def test_command_ack_routes_to_controller_and_skips_state(self, processor, state, _mock_broadcaster):
        """COMMAND_ACK must go straight to controller.handle_ack and never touch state."""
        controller = MagicMock()
        controller.handle_ack = MagicMock()
        msg = _make_msg("COMMAND_ACK", command=400, result=0)

        await processor.process(_DRONE_ID, msg, state, controller=controller)

        controller.handle_ack.assert_called_once_with(400, 0)
        state.update.assert_not_called()
        _mock_broadcaster.send.assert_not_called()

    async def test_command_ack_without_controller_is_noop(self, processor, state, _mock_broadcaster):
        """If no controller is supplied, COMMAND_ACK must not raise."""
        msg = _make_msg("COMMAND_ACK", command=400, result=0)
        await processor.process(_DRONE_ID, msg, state, controller=None)
        state.update.assert_not_called()

    async def test_global_position_int_triggers_geofence_check(self, processor, state, _mock_broadcaster):
        """Only GLOBAL_POSITION_INT should invoke the geofence check path."""
        msg = _make_msg(
            "GLOBAL_POSITION_INT",
            lat=int(1.0 * 1e7), lon=int(1.0 * 1e7),
            alt=0, relative_alt=0, hdg=0, vx=0, vy=0, vz=0,
        )
        with patch.object(processor, "_check_geofence", new=AsyncMock()) as mock_check:
            await processor.process(_DRONE_ID, msg, state)
            mock_check.assert_awaited_once()
            assert mock_check.call_args[0][0] == _DRONE_ID

    async def test_non_position_message_does_not_trigger_geofence_check(self, processor, state, _mock_broadcaster):
        msg = _make_msg("SYS_STATUS", voltage_battery=0, current_battery=0,
                         battery_remaining=0, load=0)
        with patch.object(processor, "_check_geofence", new=AsyncMock()) as mock_check:
            await processor.process(_DRONE_ID, msg, state)
            mock_check.assert_not_awaited()


# ═══════════════════════════════════════════════════════════════════════
# _check_geofence() in isolation (distinct from the broader integration
# scenarios in test_geofence*.py — here we only assert the pure decision
# logic using a real GeofenceStore instance, not the module singleton).
# ═══════════════════════════════════════════════════════════════════════

class TestCheckGeofenceIsolated:

    def setup_method(self):
        self.store = GeofenceStore()
        self.store.set_geofence(_DRONE_ID, {
            "type": "Polygon",
            "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]],
        })

        import app.modules.drone_control.telemetry_processor as tp_mod
        self._orig_store = tp_mod.geofence_store
        tp_mod.geofence_store = self.store

        self.processor = TelemetryProcessor()
        self.state = MagicMock()
        self.state.update = AsyncMock()

    def teardown_method(self):
        import app.modules.drone_control.telemetry_processor as tp_mod
        tp_mod.geofence_store = self._orig_store

    @pytest.mark.asyncio
    async def test_inside_fence_no_state_mutation(self):
        with patch("app.modules.drone_control.telemetry_processor.emit_geofence_breach",
                   new_callable=AsyncMock):
            await self.processor._check_geofence(_DRONE_ID, {"lat": 0.5, "lon": 0.5}, self.state)
            self.state.update.assert_not_called()

    @pytest.mark.asyncio
    async def test_outside_fence_mutates_state_with_breach_coords(self):
        with patch("app.modules.drone_control.telemetry_processor.emit_geofence_breach",
                   new_callable=AsyncMock):
            await self.processor._check_geofence(_DRONE_ID, {"lat": 5.0, "lon": 5.0}, self.state)
            update_data = self.state.update.call_args[0][1]
            assert update_data["geofence_breach"] is True
            assert update_data["breach_lat"] == 5.0
            assert update_data["breach_lon"] == 5.0

    @pytest.mark.asyncio
    async def test_no_registered_fence_returns_immediately(self):
        self.store.clear(_DRONE_ID)
        with patch("app.modules.drone_control.telemetry_processor.emit_geofence_breach",
                   new_callable=AsyncMock) as mock_emit:
            result = await self.processor._check_geofence(_DRONE_ID, {"lat": 5.0, "lon": 5.0}, self.state)
            assert result is None
            self.state.update.assert_not_called()
            mock_emit.assert_not_called()
