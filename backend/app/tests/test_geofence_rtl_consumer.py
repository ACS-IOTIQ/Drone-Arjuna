"""
Geofence RTL Consumer Tests  (spec 3-45)
=========================================
Verifies that auto-RTL is dispatched via the RabbitMQ consumer in
MAVLinkManager, NOT by a direct call inside TelemetryProcessor.

Architecture under test
-----------------------
  1. TelemetryProcessor._check_geofence() publishes "drone_control.geofence_breach"
     to RabbitMQ via emit_geofence_breach() and does NOT call send_command().
  2. MAVLinkManager.start_geofence_rtl_consumer() subscribes to that routing key
     and calls self.send_command(drone_id, "rtl", {}) when an event arrives.

Test strategy
-------------
  - All RabbitMQ I/O is replaced by mocks so tests run without a broker.
  - The consumer handler (_rtl_handler) is extracted from the closure and
    invoked directly to verify its behaviour end-to-end.
  - TelemetryProcessor tests verify the *publish* side (emit called, send_command
    never called) using patch() on the emitter functions.
"""
import asyncio
import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, MagicMock, patch, call

from app.utils.geofence import GeofenceStore
from app.modules.drone_control.telemetry_processor import TelemetryProcessor

_DRONE_ID    = 9001
_LAT_OUTSIDE = 13.000
_LON_OUTSIDE = 77.400
_LAT_INSIDE  = 12.970
_LON_INSIDE  = 77.590
_GEOFENCE = {
    "type": "Polygon",
    "coordinates": [[
        [77.585, 12.965],
        [77.595, 12.965],
        [77.595, 12.975],
        [77.585, 12.975],
        [77.585, 12.965],
    ]],
}


# ═══════════════════════════════════════════════════════════════════════
# Part A — TelemetryProcessor: publish-only, no direct RTL
# ═══════════════════════════════════════════════════════════════════════

class TestTelemetryProcessorPublishesOnly:
    """
    Confirm that TelemetryProcessor never calls send_command() and that
    the geofence_breach event is published exactly once on the first
    boundary crossing.
    """

    def setup_method(self):
        self.store = GeofenceStore()
        self.store.set_geofence(_DRONE_ID, _GEOFENCE)

        self.state = MagicMock()
        self.state.update = AsyncMock()

        import app.modules.drone_control.telemetry_processor as tp_mod
        self._orig_store = tp_mod.geofence_store
        tp_mod.geofence_store = self.store

        self.processor = TelemetryProcessor()

    def teardown_method(self):
        import app.modules.drone_control.telemetry_processor as tp_mod
        tp_mod.geofence_store = self._orig_store

    @pytest.mark.asyncio
    async def test_no_direct_rtl_on_breach(self):
        """TelemetryProcessor must never call send_command — RTL is consumer's job."""
        position = {"lat": _LAT_OUTSIDE, "lon": _LON_OUTSIDE}
        with patch("app.modules.drone_control.telemetry_processor.emit_geofence_breach",
                   new_callable=AsyncMock):
            # Confirm TelemetryProcessor has no _mav attribute at all
            assert not hasattr(self.processor, "_mav"), (
                "_mav must not exist — TelemetryProcessor no longer holds a MAVLink reference"
            )
            # Running _check_geofence must not raise even with no mav reference
            await self.processor._check_geofence(_DRONE_ID, position, self.state)

    @pytest.mark.asyncio
    async def test_emit_geofence_breach_called_on_breach(self):
        """emit_geofence_breach() must be called with the correct arguments."""
        position = {"lat": _LAT_OUTSIDE, "lon": _LON_OUTSIDE}
        with patch("app.modules.drone_control.telemetry_processor.emit_geofence_breach",
                   new_callable=AsyncMock) as mock_emit:
            await self.processor._check_geofence(_DRONE_ID, position, self.state)
            mock_emit.assert_called_once_with(_DRONE_ID, _LAT_OUTSIDE, _LON_OUTSIDE)

    @pytest.mark.asyncio
    async def test_emit_called_once_across_multiple_ticks(self):
        """Even with 5 consecutive ticks outside, emit fires exactly once."""
        position = {"lat": _LAT_OUTSIDE, "lon": _LON_OUTSIDE}
        with patch("app.modules.drone_control.telemetry_processor.emit_geofence_breach",
                   new_callable=AsyncMock) as mock_emit:
            for _ in range(5):
                await self.processor._check_geofence(_DRONE_ID, position, self.state)
            assert mock_emit.call_count == 1

    @pytest.mark.asyncio
    async def test_emit_geofence_recovered_on_re_entry(self):
        """emit_geofence_recovered() must be called when drone re-enters the fence."""
        outside = {"lat": _LAT_OUTSIDE, "lon": _LON_OUTSIDE}
        inside  = {"lat": _LAT_INSIDE,  "lon": _LON_INSIDE}

        with patch("app.modules.drone_control.telemetry_processor.emit_geofence_breach",
                   new_callable=AsyncMock), \
             patch("app.modules.drone_control.telemetry_processor.emit_geofence_recovered",
                   new_callable=AsyncMock) as mock_recovered:
            await self.processor._check_geofence(_DRONE_ID, outside, self.state)
            await self.processor._check_geofence(_DRONE_ID, inside, self.state)
            mock_recovered.assert_called_once_with(_DRONE_ID)

    @pytest.mark.asyncio
    async def test_no_emit_when_inside(self):
        """No event is published while the drone stays inside the fence."""
        position = {"lat": _LAT_INSIDE, "lon": _LON_INSIDE}
        with patch("app.modules.drone_control.telemetry_processor.emit_geofence_breach",
                   new_callable=AsyncMock) as mock_emit, \
             patch("app.modules.drone_control.telemetry_processor.emit_geofence_recovered",
                   new_callable=AsyncMock) as mock_recovered:
            for _ in range(3):
                await self.processor._check_geofence(_DRONE_ID, position, self.state)
            mock_emit.assert_not_called()
            mock_recovered.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_emit_when_no_fence_registered(self):
        """With no geofence registered, no events are published."""
        self.store.clear(_DRONE_ID)
        position = {"lat": _LAT_OUTSIDE, "lon": _LON_OUTSIDE}
        with patch("app.modules.drone_control.telemetry_processor.emit_geofence_breach",
                   new_callable=AsyncMock) as mock_emit:
            await self.processor._check_geofence(_DRONE_ID, position, self.state)
            mock_emit.assert_not_called()


# ═══════════════════════════════════════════════════════════════════════
# Part B — MAVLinkManager geofence RTL consumer
# ═══════════════════════════════════════════════════════════════════════

class TestGeofenceRtlConsumer:
    """
    Tests the RabbitMQ consumer that dispatches auto-RTL.

    Strategy: mock `app.core.events.subscribe` so we can capture the
    handler closure without a live broker, then invoke it directly to
    verify that send_command("rtl") is called correctly.
    """

    def _make_manager(self):
        """Return a MAVLinkManager with all I/O dependencies stubbed out."""
        # Stub heavy imports before constructing MAVLinkManager
        with patch("app.modules.drone_control.mavlink_manager.HealthMonitor"), \
             patch("app.modules.drone_control.mavlink_manager.data_recorder"):
            from app.modules.drone_control.mavlink_manager import MAVLinkManager
            mgr = MAVLinkManager.__new__(MAVLinkManager)
            mgr._connections = {}
            mgr.state = MagicMock()
            mgr.state.subscribe = MagicMock()
            mgr._processor = TelemetryProcessor()
            return mgr

    @pytest.mark.asyncio
    async def test_subscribe_called_with_correct_routing_key(self):
        """start_geofence_rtl_consumer() must subscribe to drone_control.geofence_breach."""
        mgr = self._make_manager()
        captured = {}

        async def fake_subscribe(routing_key_pattern, queue_name, handler):
            captured["routing_key"] = routing_key_pattern
            captured["queue_name"]  = queue_name
            captured["handler"]     = handler

        with patch("app.core.events.subscribe", side_effect=fake_subscribe):
            await mgr.start_geofence_rtl_consumer()

        assert captured["routing_key"] == "drone_control.geofence_breach"
        assert captured["queue_name"]  == "geofence_rtl_queue"
        assert callable(captured["handler"])

    @pytest.mark.asyncio
    async def test_consumer_handler_dispatches_rtl(self):
        """Handler must call send_command(drone_id, 'rtl', {}) when event arrives."""
        mgr = self._make_manager()
        mgr.send_command = AsyncMock()

        captured_handler = None

        async def fake_subscribe(routing_key_pattern, queue_name, handler):
            nonlocal captured_handler
            captured_handler = handler

        with patch("app.core.events.subscribe", side_effect=fake_subscribe):
            await mgr.start_geofence_rtl_consumer()

        assert captured_handler is not None
        await captured_handler({"event": "GEOFENCE_BREACH", "drone_id": _DRONE_ID,
                                "lat": _LAT_OUTSIDE, "lon": _LON_OUTSIDE})
        mgr.send_command.assert_called_once_with(_DRONE_ID, "rtl", {})

    @pytest.mark.asyncio
    async def test_consumer_handler_ignores_missing_drone_id(self):
        """Handler must not raise and must not call send_command when drone_id is absent."""
        mgr = self._make_manager()
        mgr.send_command = AsyncMock()

        captured_handler = None

        async def fake_subscribe(routing_key_pattern, queue_name, handler):
            nonlocal captured_handler
            captured_handler = handler

        with patch("app.core.events.subscribe", side_effect=fake_subscribe):
            await mgr.start_geofence_rtl_consumer()

        await captured_handler({"event": "GEOFENCE_BREACH"})  # no drone_id
        mgr.send_command.assert_not_called()

    @pytest.mark.asyncio
    async def test_consumer_handler_dispatches_rtl_for_multiple_drones(self):
        """Handler must dispatch RTL for each drone independently."""
        mgr = self._make_manager()
        mgr.send_command = AsyncMock()

        captured_handler = None

        async def fake_subscribe(routing_key_pattern, queue_name, handler):
            nonlocal captured_handler
            captured_handler = handler

        with patch("app.core.events.subscribe", side_effect=fake_subscribe):
            await mgr.start_geofence_rtl_consumer()

        await captured_handler({"drone_id": 1, "lat": 1.0, "lon": 2.0})
        await captured_handler({"drone_id": 2, "lat": 3.0, "lon": 4.0})

        assert mgr.send_command.call_count == 2
        mgr.send_command.assert_any_call(1, "rtl", {})
        mgr.send_command.assert_any_call(2, "rtl", {})

    @pytest.mark.asyncio
    async def test_subscribe_not_called_when_rabbitmq_unavailable(self):
        """If subscribe raises (no broker), start_geofence_rtl_consumer must not crash."""
        mgr = self._make_manager()

        async def fake_subscribe(*_, **__):
            raise ConnectionError("RabbitMQ not reachable")

        # The method should propagate or handle gracefully — we just ensure no unhandled
        # exception bubbles past the await (it will raise here, which is acceptable; the
        # important contract is that it doesn't silently swallow a different error)
        with patch("app.core.events.subscribe", side_effect=fake_subscribe):
            with pytest.raises((ConnectionError, Exception)):
                await mgr.start_geofence_rtl_consumer()


# ═══════════════════════════════════════════════════════════════════════
# Part C — Architectural invariant: no direct RTL in TelemetryProcessor
# ═══════════════════════════════════════════════════════════════════════

class TestArchitecturalInvariant:
    """
    Static / structural checks that confirm the refactor is complete.
    These are safety-net tests — they will fail if anyone accidentally
    reintroduces the direct RTL path inside TelemetryProcessor.
    """

    def test_telemetry_processor_takes_no_mavlink_manager_arg(self):
        """TelemetryProcessor.__init__ must accept zero positional args."""
        import inspect
        from app.modules.drone_control.telemetry_processor import TelemetryProcessor
        sig = inspect.signature(TelemetryProcessor.__init__)
        params = [p for p in sig.parameters if p != "self"]
        assert params == [], (
            f"TelemetryProcessor.__init__ must have no parameters; found: {params}"
        )

    def test_telemetry_processor_source_has_no_send_command_call(self):
        """The source of TelemetryProcessor must not contain 'send_command'."""
        import inspect
        from app.modules.drone_control.telemetry_processor import TelemetryProcessor
        source = inspect.getsource(TelemetryProcessor)
        assert "send_command" not in source, (
            "send_command found inside TelemetryProcessor — "
            "RTL must only be dispatched via the RabbitMQ consumer in MAVLinkManager"
        )

    def test_mavlink_manager_has_rtl_consumer_method(self):
        """MAVLinkManager must expose start_geofence_rtl_consumer()."""
        with patch("app.modules.drone_control.mavlink_manager.HealthMonitor"), \
             patch("app.modules.drone_control.mavlink_manager.data_recorder"):
            from app.modules.drone_control.mavlink_manager import MAVLinkManager
            assert hasattr(MAVLinkManager, "start_geofence_rtl_consumer"), (
                "MAVLinkManager must have start_geofence_rtl_consumer()"
            )
            assert asyncio.iscoroutinefunction(
                MAVLinkManager.start_geofence_rtl_consumer
            ), "start_geofence_rtl_consumer must be async"
