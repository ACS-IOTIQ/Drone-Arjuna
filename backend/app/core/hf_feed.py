"""UDP ingestion for the vessel's NMEA position feed."""

import asyncio
import json
from typing import Any

import pynmea2
import redis.asyncio as aioredis
import structlog

POSITION_KEY = "vessel:position"
POSITION_TTL_SECONDS = 10
log = structlog.get_logger()


async def ingest_nmea(sentence: str, redis: Any) -> bool:
    """Parse a GGA sentence and cache its latitude/longitude for 10 seconds."""
    message = pynmea2.parse(sentence.strip())
    if message.sentence_type != "GGA":
        return False

    payload = json.dumps(
        {"lat": float(message.latitude), "lng": float(message.longitude)},
        separators=(",", ":"),
    )
    await redis.set(POSITION_KEY, payload, ex=POSITION_TTL_SECONDS)
    return True


class _NMEAProtocol(asyncio.DatagramProtocol):
    def __init__(self, redis: aioredis.Redis) -> None:
        self.redis = redis
        self._tasks: set[asyncio.Task] = set()

    def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:
        try:
            sentence = data.decode("ascii").strip()
        except UnicodeDecodeError:
            log.warning("hf_feed.invalid_encoding", source=addr)
            return

        task = asyncio.create_task(self._ingest(sentence, addr))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _ingest(self, sentence: str, addr: tuple[str, int]) -> None:
        try:
            await ingest_nmea(sentence, self.redis)
        except (pynmea2.ParseError, ValueError) as exc:
            log.warning("hf_feed.invalid_nmea", source=addr, error=str(exc))
        except Exception as exc:
            log.error("hf_feed.ingest_failed", source=addr, error=str(exc))


class HFFeedListener:
    """Own the UDP transport and Redis client used by the NMEA feed."""

    def __init__(self, redis_url: str, host: str, port: int) -> None:
        self.redis_url = redis_url
        self.host = host
        self.port = port
        self.redis: aioredis.Redis | None = None
        self.transport: asyncio.DatagramTransport | None = None

    async def start(self) -> None:
        self.redis = aioredis.from_url(
            self.redis_url, encoding="utf-8", decode_responses=True
        )
        loop = asyncio.get_running_loop()
        transport, _ = await loop.create_datagram_endpoint(
            lambda: _NMEAProtocol(self.redis), local_addr=(self.host, self.port)
        )
        self.transport = transport
        log.info("hf_feed.started", host=self.host, port=self.port)

    async def stop(self) -> None:
        if self.transport is not None:
            self.transport.close()
            self.transport = None
        if self.redis is not None:
            await self.redis.aclose()
            self.redis = None
        log.info("hf_feed.stopped")
