"""UDP ingestion for the vessel's NMEA position feed."""

import asyncio
import ipaddress
import json
import math
import time
from typing import Any

import pynmea2
import redis.asyncio as aioredis
import structlog

POSITION_KEY = "vessel:position"
POSITION_TTL_SECONDS = 10
log = structlog.get_logger()


MAX_DATAGRAM_BYTES = 256      # NMEA 0183 sentences are <= 82 chars


def parse_allowed_sources(csv: str) -> list:
    """'10.0.0.5, 192.168.1.0/24' -> [ip_network, ...]. Empty = no restriction."""
    return [ipaddress.ip_network(p.strip(), strict=False) for p in csv.split(",") if p.strip()]


def source_allowed(ip: str, networks: list) -> bool:
    if not networks:
        return True
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return any(addr in net for net in networks)


def _distance_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6_371_000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(h))


async def _previous_position(redis: Any) -> dict | None:
    try:
        raw = await redis.get(POSITION_KEY)
        if isinstance(raw, (bytes, str)):
            prev = json.loads(raw)
            if isinstance(prev, dict) and "ts" in prev:
                return prev
    except Exception:
        pass
    return None


async def ingest_nmea(sentence: str, redis: Any, *, max_speed_ms: float | None = None,
                      now: float | None = None) -> bool:
    """
    Parse a GGA sentence and cache its latitude/longitude for 10 seconds.

    NMEA carries no authentication, and this position drives RTL home points,
    so a fix is only accepted when it is plausible: the receiver reports a GPS
    fix, coordinates are in range, and (if max_speed_ms is set) the move from
    the previous accepted position does not imply an impossible speed.
    """
    message = pynmea2.parse(sentence.strip())
    if message.sentence_type != "GGA":
        return False

    if int(message.gps_qual or 0) == 0:
        log.warning("hf_feed.rejected", reason="no_gps_fix")
        return False
    lat, lon = float(message.latitude), float(message.longitude)
    if not (-90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0):
        log.warning("hf_feed.rejected", reason="out_of_range")
        return False

    ts = time.time() if now is None else now
    if max_speed_ms:
        prev = await _previous_position(redis)
        if prev is not None:
            dt = ts - float(prev["ts"])
            if dt > 0 and _distance_m(float(prev["lat"]), float(prev["lng"]), lat, lon) / dt > max_speed_ms:
                log.warning("hf_feed.rejected", reason="implausible_jump", seconds=round(dt, 2))
                return False

    payload = json.dumps(
        {"lat": lat, "lng": lon, "lon": lon, "ts": ts},
        separators=(",", ":"),
    )
    await redis.set(POSITION_KEY, payload, ex=POSITION_TTL_SECONDS)
    return True


class _NMEAProtocol(asyncio.DatagramProtocol):
    def __init__(self, redis: aioredis.Redis, allowed_sources: list | None = None,
                 max_msgs_per_sec: int = 20, max_speed_ms: float | None = None) -> None:
        self.redis = redis
        self.allowed_sources = allowed_sources or []
        self.max_msgs_per_sec = max_msgs_per_sec
        self.max_speed_ms = max_speed_ms
        self._tasks: set[asyncio.Task] = set()
        self._window_start = 0.0
        self._window_count = 0

    def _rate_limited(self) -> bool:
        now = time.monotonic()
        if now - self._window_start >= 1.0:
            self._window_start, self._window_count = now, 0
        self._window_count += 1
        return self._window_count > self.max_msgs_per_sec

    def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:
        if not source_allowed(addr[0], self.allowed_sources):
            log.warning("hf_feed.source_not_allowed", source=addr)
            return
        if len(data) > MAX_DATAGRAM_BYTES or self._rate_limited():
            return
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
            await ingest_nmea(sentence, self.redis, max_speed_ms=self.max_speed_ms)
        except (pynmea2.ParseError, ValueError) as exc:
            log.warning("hf_feed.invalid_nmea", source=addr, error=str(exc))
        except Exception as exc:
            log.error("hf_feed.ingest_failed", source=addr, error=str(exc))


class HFFeedListener:
    """Own the UDP transport and Redis client used by the NMEA feed."""

    def __init__(self, redis_url: str, host: str, port: int, *,
                 allowed_sources: list | None = None, max_msgs_per_sec: int = 20,
                 max_speed_ms: float | None = None) -> None:
        self.redis_url = redis_url
        self.host = host
        self.port = port
        self.allowed_sources = allowed_sources or []
        self.max_msgs_per_sec = max_msgs_per_sec
        self.max_speed_ms = max_speed_ms
        self.redis: aioredis.Redis | None = None
        self.transport: asyncio.DatagramTransport | None = None

    async def start(self) -> None:
        self.redis = aioredis.from_url(
            self.redis_url, encoding="utf-8", decode_responses=True
        )
        loop = asyncio.get_running_loop()
        transport, _ = await loop.create_datagram_endpoint(
            lambda: _NMEAProtocol(self.redis, self.allowed_sources,
                                  self.max_msgs_per_sec, self.max_speed_ms),
            local_addr=(self.host, self.port),
        )
        self.transport = transport
        if not self.allowed_sources:
            log.warning("hf_feed.no_source_allowlist",
                        hint="set HF_FEED_ALLOWED_SOURCES_STR to the vessel/bridge address(es)")
        log.info("hf_feed.started", host=self.host, port=self.port,
                 allowed_sources=[str(n) for n in self.allowed_sources])

    async def stop(self) -> None:
        if self.transport is not None:
            self.transport.close()
            self.transport = None
        if self.redis is not None:
            await self.redis.aclose()
            self.redis = None
        log.info("hf_feed.stopped")
