"""NMEA feed hardening (H-06): source allow-list, plausibility checks, rate limit."""
import asyncio
import json
import time
from unittest.mock import AsyncMock

import pynmea2
import pytest

from app.core.hf_feed import _NMEAProtocol, ingest_nmea, parse_allowed_sources, source_allowed


def _gga(lat="4807.038", ns="N", lon="01131.000", ew="E", qual="1"):
    return pynmea2.GGA(
        "GP", "GGA",
        ("123519", lat, ns, lon, ew, qual, "08", "0.9", "545.4", "M", "46.9", "M", "", ""),
    ).render(checksum=True)


def test_source_allowlist_matching():
    nets = parse_allowed_sources("10.0.0.5, 192.168.1.0/24")
    assert source_allowed("10.0.0.5", nets)
    assert source_allowed("192.168.1.77", nets)
    assert not source_allowed("10.0.0.6", nets)
    assert not source_allowed("not-an-ip", nets)
    assert source_allowed("8.8.8.8", [])          # empty list = unrestricted


async def test_datagram_from_unlisted_source_is_dropped():
    redis = AsyncMock()
    protocol = _NMEAProtocol(redis, allowed_sources=parse_allowed_sources("10.0.0.5"))
    protocol.datagram_received(_gga().encode(), ("203.0.113.9", 4000))
    await asyncio.sleep(0)
    assert not protocol._tasks
    redis.set.assert_not_awaited()


async def test_datagram_from_listed_source_is_accepted():
    redis = AsyncMock()
    protocol = _NMEAProtocol(redis, allowed_sources=parse_allowed_sources("10.0.0.5"))
    protocol.datagram_received(_gga().encode(), ("10.0.0.5", 4000))
    await asyncio.gather(*tuple(protocol._tasks))
    redis.set.assert_awaited_once()


async def test_oversized_datagram_is_dropped():
    redis = AsyncMock()
    protocol = _NMEAProtocol(redis)
    protocol.datagram_received(b"$" + b"A" * 1000, ("127.0.0.1", 4000))
    await asyncio.sleep(0)
    assert not protocol._tasks


async def test_rate_limit_drops_flood():
    redis = AsyncMock()
    protocol = _NMEAProtocol(redis, max_msgs_per_sec=3)
    for _ in range(10):
        protocol.datagram_received(_gga().encode(), ("127.0.0.1", 4000))
    await asyncio.gather(*tuple(protocol._tasks))
    assert redis.set.await_count == 3


async def test_no_gps_fix_is_rejected():
    redis = AsyncMock()
    assert await ingest_nmea(_gga(qual="0"), redis) is False
    redis.set.assert_not_awaited()


async def test_implausible_jump_is_rejected_and_normal_move_accepted():
    now = time.time()
    prev = json.dumps({"lat": 48.1173, "lng": 11.5167, "lon": 11.5167, "ts": now - 2})
    redis = AsyncMock()
    redis.get.return_value = prev
    far = _gga(lat="4907.038")           # ~111 km in 2 s: impossible for a vessel
    assert await ingest_nmea(far, redis, max_speed_ms=40.0, now=now) is False
    redis.set.assert_not_awaited()
    near = _gga(lat="4807.045")          # ~13 m in 2 s: fine
    assert await ingest_nmea(near, redis, max_speed_ms=40.0, now=now) is True


async def test_first_fix_without_history_is_accepted():
    redis = AsyncMock()                  # redis.get returns a Mock, i.e. no usable history
    assert await ingest_nmea(_gga(), redis, max_speed_ms=40.0) is True


async def test_payload_has_lon_for_home_point_updater():
    redis = AsyncMock()
    await ingest_nmea(_gga(), redis)
    pos = json.loads(redis.set.await_args.args[1])
    assert pos["lon"] == pos["lng"] and "ts" in pos
