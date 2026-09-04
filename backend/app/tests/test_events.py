"""
Unit tests for app.core.events — RabbitMQ topic exchange publish/subscribe
helpers. aio_pika is fully mocked; no live RabbitMQ connection is made.
"""
import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import aio_pika
import pytest

from app.core import events


@pytest.fixture(autouse=True)
def _reset_module_state():
    """Each test starts with a clean slate for the module-level globals."""
    original = (events._connection, events._channel, events._exchange)
    yield
    events._connection, events._channel, events._exchange = original


class TestInitRabbitmq:
    async def test_successful_connect_sets_globals(self, monkeypatch):
        fake_connection = AsyncMock()
        fake_channel = AsyncMock()
        fake_exchange = AsyncMock()
        fake_connection.channel.return_value = fake_channel
        fake_channel.declare_exchange.return_value = fake_exchange

        with patch.object(aio_pika, "connect_robust", AsyncMock(return_value=fake_connection)):
            await events.init_rabbitmq()

        assert events._connection is fake_connection
        assert events._channel is fake_channel
        assert events._exchange is fake_exchange
        fake_channel.set_qos.assert_awaited_once_with(prefetch_count=100)

    async def test_retries_then_succeeds(self, monkeypatch):
        fake_connection = AsyncMock()
        fake_channel = AsyncMock()
        fake_exchange = AsyncMock()
        fake_connection.channel.return_value = fake_channel
        fake_channel.declare_exchange.return_value = fake_exchange

        attempts = {"count": 0}

        async def flaky_connect(*args, **kwargs):
            attempts["count"] += 1
            if attempts["count"] < 3:
                raise ConnectionError("not ready")
            return fake_connection

        with patch.object(aio_pika, "connect_robust", flaky_connect), \
             patch.object(events.asyncio, "sleep", AsyncMock()):
            await events.init_rabbitmq()

        assert attempts["count"] == 3
        assert events._exchange is fake_exchange

    async def test_all_attempts_fail_disables_exchange(self, monkeypatch):
        with patch.object(aio_pika, "connect_robust", AsyncMock(side_effect=ConnectionError("down"))), \
             patch.object(events.asyncio, "sleep", AsyncMock()):
            await events.init_rabbitmq()

        assert events._exchange is None


class TestCloseRabbitmq:
    async def test_closes_existing_connection(self):
        fake_connection = AsyncMock()
        events._connection = fake_connection

        await events.close_rabbitmq()

        fake_connection.close.assert_awaited_once()

    async def test_no_connection_is_a_noop(self):
        events._connection = None
        await events.close_rabbitmq()  # must not raise


class TestPublish:
    async def test_no_exchange_is_a_noop(self):
        events._exchange = None
        await events.publish("some.key", {"a": 1})  # must not raise

    async def test_publishes_json_message_with_routing_key(self):
        fake_exchange = AsyncMock()
        events._exchange = fake_exchange

        await events.publish("drone_control.telemetry_update", {"drone_id": 1})

        fake_exchange.publish.assert_awaited_once()
        args, kwargs = fake_exchange.publish.call_args
        message = args[0]
        assert kwargs["routing_key"] == "drone_control.telemetry_update"
        assert json.loads(message.body.decode()) == {"drone_id": 1}
        assert message.content_type == "application/json"

    async def test_publish_exception_is_swallowed(self):
        fake_exchange = AsyncMock()
        fake_exchange.publish.side_effect = RuntimeError("broker down")
        events._exchange = fake_exchange

        await events.publish("some.key", {"a": 1})  # must not raise


class TestSubscribe:
    async def test_no_channel_logs_and_returns(self):
        events._channel = None
        await events.subscribe("pattern.*", "queue1", AsyncMock())  # must not raise

    async def test_declares_queue_and_binds_exchange(self):
        fake_channel = AsyncMock()
        fake_queue = AsyncMock()
        fake_exchange = AsyncMock()
        fake_channel.declare_queue.return_value = fake_queue
        fake_channel.declare_exchange.return_value = fake_exchange
        events._channel = fake_channel

        handler = AsyncMock()
        await events.subscribe("drone_control.*", "my-queue", handler)

        fake_channel.declare_queue.assert_awaited_once_with("my-queue", durable=True)
        fake_queue.bind.assert_awaited_once_with(fake_exchange, routing_key="drone_control.*")
        fake_queue.consume.assert_awaited_once()

    async def test_process_wrapper_decodes_and_calls_handler(self):
        fake_channel = AsyncMock()
        fake_queue = AsyncMock()
        fake_exchange = AsyncMock()
        fake_channel.declare_queue.return_value = fake_queue
        fake_channel.declare_exchange.return_value = fake_exchange
        events._channel = fake_channel

        handler = AsyncMock()
        await events.subscribe("drone_control.*", "my-queue", handler)

        # Capture the _process callback passed to queue.consume
        process_callback = fake_queue.consume.call_args.args[0]

        fake_msg = MagicMock()
        fake_msg.body = json.dumps({"drone_id": 42}).encode()
        ctx_mgr = AsyncMock()
        ctx_mgr.__aenter__.return_value = None
        ctx_mgr.__aexit__.return_value = False
        fake_msg.process.return_value = ctx_mgr

        await process_callback(fake_msg)

        handler.assert_awaited_once_with({"drone_id": 42})

    async def test_process_wrapper_swallows_handler_exception(self):
        fake_channel = AsyncMock()
        fake_queue = AsyncMock()
        fake_exchange = AsyncMock()
        fake_channel.declare_queue.return_value = fake_queue
        fake_channel.declare_exchange.return_value = fake_exchange
        events._channel = fake_channel

        handler = AsyncMock(side_effect=RuntimeError("bad handler"))
        await events.subscribe("drone_control.*", "my-queue", handler)
        process_callback = fake_queue.consume.call_args.args[0]

        fake_msg = MagicMock()
        fake_msg.body = json.dumps({"drone_id": 42}).encode()
        ctx_mgr = AsyncMock()
        ctx_mgr.__aenter__.return_value = None
        ctx_mgr.__aexit__.return_value = False
        fake_msg.process.return_value = ctx_mgr

        await process_callback(fake_msg)  # must not raise


# ══════════════════════════════════════════════════════════════════
# Convenience publishers
# ══════════════════════════════════════════════════════════════════

class TestConveniencePublishers:
    async def _assert_published(self, coro, expected_key, expected_payload):
        fake_exchange = AsyncMock()
        events._exchange = fake_exchange
        await coro
        fake_exchange.publish.assert_awaited_once()
        args, kwargs = fake_exchange.publish.call_args
        assert kwargs["routing_key"] == expected_key
        assert json.loads(args[0].body.decode()) == expected_payload

    async def test_emit_telemetry_update(self):
        await self._assert_published(
            events.emit_telemetry_update(1, {"lat": 10.0}),
            "drone_control.telemetry_update",
            {"drone_id": 1, "lat": 10.0},
        )

    async def test_emit_drone_connected(self):
        await self._assert_published(
            events.emit_drone_connected(1, "ALPHA"),
            "drone_control.connected",
            {"drone_id": 1, "call_sign": "ALPHA"},
        )

    async def test_emit_drone_disconnected(self):
        await self._assert_published(
            events.emit_drone_disconnected(1),
            "drone_control.disconnected",
            {"drone_id": 1},
        )

    async def test_emit_mission_status(self):
        await self._assert_published(
            events.emit_mission_status(5, "executing"),
            "drone_flight.mission_status",
            {"mission_id": 5, "status": "executing"},
        )

    async def test_emit_health_alert(self):
        await self._assert_published(
            events.emit_health_alert(1, "low_battery", 12.5),
            "drone_control.health_alert",
            {"drone_id": 1, "alert_type": "low_battery", "value": 12.5},
        )

    async def test_emit_geofence_breach(self):
        await self._assert_published(
            events.emit_geofence_breach(1, 17.0, 78.0),
            "drone_control.geofence_breach",
            {"event": "GEOFENCE_BREACH", "drone_id": 1, "lat": 17.0, "lon": 78.0},
        )

    async def test_emit_geofence_recovered(self):
        await self._assert_published(
            events.emit_geofence_recovered(1),
            "drone_control.geofence_recovered",
            {"event": "GEOFENCE_RECOVERED", "drone_id": 1},
        )
