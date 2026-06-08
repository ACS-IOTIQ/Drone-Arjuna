"""
RabbitMQ event bus — publish/subscribe helpers.
All inter-module communication goes through topic exchanges.

Exchange: dronearjuna.events
Routing key pattern: module.event_name  e.g. drone_control.telemetry_update
"""
import asyncio
import json
import structlog
from typing import Callable
import aio_pika
from aio_pika import ExchangeType
from app.config import get_settings

log = structlog.get_logger()
cfg = get_settings()

_connection: aio_pika.RobustConnection | None = None
_channel: aio_pika.Channel | None = None
_exchange: aio_pika.Exchange | None = None

EXCHANGE_NAME = "dronearjuna.events"


async def init_rabbitmq():
    global _connection, _channel, _exchange
    try:
        _connection = await aio_pika.connect_robust(cfg.rabbitmq_url)
        _channel = await _connection.channel()
        await _channel.set_qos(prefetch_count=100)
        _exchange = await _channel.declare_exchange(
            EXCHANGE_NAME, ExchangeType.TOPIC, durable=True
        )
        log.info("RabbitMQ connected", exchange=EXCHANGE_NAME)
    except Exception as e:
        log.warning("RabbitMQ unavailable — event publishing disabled", error=str(e))
        _exchange = None


async def close_rabbitmq():
    global _connection
    if _connection:
        await _connection.close()


async def publish(routing_key: str, payload: dict):
    """
    Publish a JSON event to the topic exchange.
    Silently drops if RabbitMQ is not connected (graceful degradation).
    """
    if _exchange is None:
        return
    try:
        await _exchange.publish(
            aio_pika.Message(
                body=json.dumps(payload).encode(),
                content_type="application/json",
                delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
            ),
            routing_key=routing_key,
        )
    except Exception as e:
        log.warning("Event publish failed", key=routing_key, error=str(e))


async def subscribe(routing_key_pattern: str, queue_name: str, handler: Callable):
    """
    Subscribe to events matching routing_key_pattern.
    handler receives (dict) — the decoded JSON payload.
    """
    if _channel is None:
        log.warning("Cannot subscribe — RabbitMQ not connected")
        return

    queue = await _channel.declare_queue(queue_name, durable=True)
    exchange = await _channel.declare_exchange(
        EXCHANGE_NAME, ExchangeType.TOPIC, durable=True
    )
    await queue.bind(exchange, routing_key=routing_key_pattern)

    async def _process(msg: aio_pika.IncomingMessage):
        async with msg.process():
            try:
                data = json.loads(msg.body)
                await handler(data)
            except Exception as e:
                log.error("Event handler error", error=str(e))

    await queue.consume(_process)
    log.info("Subscribed to events", pattern=routing_key_pattern, queue=queue_name)


# ── Convenience publishers used by modules ─────────────────────────

async def emit_telemetry_update(drone_id: int, state: dict):
    await publish("drone_control.telemetry_update", {"drone_id": drone_id, **state})

async def emit_drone_connected(drone_id: int, call_sign: str):
    await publish("drone_control.connected", {"drone_id": drone_id, "call_sign": call_sign})

async def emit_drone_disconnected(drone_id: int):
    await publish("drone_control.disconnected", {"drone_id": drone_id})

async def emit_mission_status(mission_id: int, status: str):
    await publish("drone_flight.mission_status", {"mission_id": mission_id, "status": status})

async def emit_health_alert(drone_id: int, alert_type: str, value: float):
    await publish("drone_control.health_alert", {
        "drone_id": drone_id, "alert_type": alert_type, "value": value,
    })