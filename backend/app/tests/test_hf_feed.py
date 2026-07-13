import asyncio
import json
from unittest.mock import AsyncMock

import pynmea2
import pytest

from app.core.hf_feed import _NMEAProtocol, ingest_nmea


@pytest.mark.asyncio
async def test_ingest_gga_writes_position_with_ten_second_ttl():
    redis = AsyncMock()
    sentence = pynmea2.GGA(
        "GP", "GGA",
        ("123519", "4807.038", "N", "01131.000", "E", "1", "08", "0.9",
         "545.4", "M", "46.9", "M", "", ""),
    ).render(checksum=True)

    assert await ingest_nmea(sentence, redis) is True
    value = redis.set.await_args.args[1]
    position = json.loads(value)
    assert position["lat"] == pytest.approx(48.1173)
    assert position["lng"] == pytest.approx(11.5166667)
    redis.set.assert_awaited_once_with("vessel:position", value, ex=10)


@pytest.mark.asyncio
async def test_ingest_ignores_non_gga_sentence():
    redis = AsyncMock()
    sentence = pynmea2.RMC(
        "GP", "RMC",
        ("123519", "A", "4807.038", "N", "01131.000", "E", "0", "0",
         "230394", "", ""),
    ).render(checksum=True)

    assert await ingest_nmea(sentence, redis) is False
    redis.set.assert_not_awaited()


@pytest.mark.asyncio
async def test_ingest_gga_converts_south_and_west_to_negative_coordinates():
    redis = AsyncMock()
    sentence = pynmea2.GGA(
        "GP", "GGA",
        ("123519", "3351.000", "S", "15112.000", "W", "1", "07", "1.1",
         "12.0", "M", "", "M", "", ""),
    ).render(checksum=True)

    assert await ingest_nmea(sentence, redis) is True
    position = json.loads(redis.set.await_args.args[1])
    assert position["lat"] == pytest.approx(-33.85)
    assert position["lng"] == pytest.approx(-151.2)


@pytest.mark.asyncio
async def test_ingest_rejects_bad_checksum_without_writing_redis():
    redis = AsyncMock()
    sentence = (
        "$GPGGA,123519,4807.038,N,01131.000,E,1,08,0.9,"
        "545.4,M,46.9,M,,*00"
    )

    with pytest.raises(pynmea2.ChecksumError):
        await ingest_nmea(sentence, redis)

    redis.set.assert_not_awaited()


@pytest.mark.asyncio
async def test_udp_protocol_dispatches_gga_datagram_to_redis():
    redis = AsyncMock()
    protocol = _NMEAProtocol(redis)
    sentence = pynmea2.GGA(
        "GP", "GGA",
        ("123519", "4807.038", "N", "01131.000", "E", "1", "08", "0.9",
         "545.4", "M", "46.9", "M", "", ""),
    ).render(checksum=True)

    protocol.datagram_received(sentence.encode("ascii"), ("127.0.0.1", 50000))
    await asyncio.gather(*tuple(protocol._tasks))

    redis.set.assert_awaited_once()
    assert redis.set.await_args.args[0] == "vessel:position"
    assert redis.set.await_args.kwargs["ex"] == 10


@pytest.mark.asyncio
async def test_udp_protocol_drops_non_ascii_datagram():
    redis = AsyncMock()
    protocol = _NMEAProtocol(redis)

    protocol.datagram_received(b"\xff\xfe", ("127.0.0.1", 50000))
    await asyncio.sleep(0)

    assert not protocol._tasks
    redis.set.assert_not_awaited()
