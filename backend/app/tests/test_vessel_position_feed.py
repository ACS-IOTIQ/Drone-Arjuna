"""
Unit tests for app.modules.drone_control.vessel_position_feed.

Covers:
  - vessel system-id range checks (is_vessel_sys_id)
  - system_id -> vessel PK map loading
  - register_update_callback wiring
  - handle_position_message: unit conversion, heading sentinel handling,
    speed calculation, unknown system_id short-circuit, and DB callback
    error swallowing.
"""
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.modules.drone_control import vessel_position_feed as vpf


@pytest.fixture(autouse=True)
def _reset_module_state():
    """Ensure module-level globals don't leak between tests."""
    vpf._vessel_sys_id_map.clear()
    vpf._position_update_cb = None
    yield
    vpf._vessel_sys_id_map.clear()
    vpf._position_update_cb = None


def _make_msg(lat, lon, hdg, vx, vy):
    return SimpleNamespace(lat=lat, lon=lon, hdg=hdg, vx=vx, vy=vy)


# ── is_vessel_sys_id ──────────────────────────────────────────────────────────

def test_is_vessel_sys_id_within_range():
    assert vpf.is_vessel_sys_id(200) is True
    assert vpf.is_vessel_sys_id(239) is True
    assert vpf.is_vessel_sys_id(220) is True


def test_is_vessel_sys_id_outside_range():
    assert vpf.is_vessel_sys_id(199) is False
    assert vpf.is_vessel_sys_id(240) is False
    assert vpf.is_vessel_sys_id(1) is False
    assert vpf.is_vessel_sys_id(255) is False


# ── load_vessel_map / register_update_callback ───────────────────────────────

def test_load_vessel_map_populates_and_replaces_mapping():
    vpf.load_vessel_map({200: 1, 201: 2})
    assert vpf._vessel_sys_id_map == {200: 1, 201: 2}

    # Loading again should clear stale entries, not merge.
    vpf.load_vessel_map({205: 6})
    assert vpf._vessel_sys_id_map == {205: 6}


def test_register_update_callback_sets_module_global():
    cb = AsyncMock()
    vpf.register_update_callback(cb)
    assert vpf._position_update_cb is cb


# ── handle_position_message ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_handle_position_message_unknown_system_id_is_noop():
    cb = AsyncMock()
    vpf.register_update_callback(cb)
    vpf.load_vessel_map({200: 1})

    msg = _make_msg(lat=480703800, lon=113100000, hdg=1800, vx=0, vy=0)
    await vpf.handle_position_message(999, msg)

    cb.assert_not_awaited()


@pytest.mark.asyncio
async def test_handle_position_message_no_callback_registered_does_not_raise():
    vpf.load_vessel_map({200: 1})
    msg = _make_msg(lat=480703800, lon=113100000, hdg=1800, vx=0, vy=0)

    # Should simply return without a registered callback and without error.
    await vpf.handle_position_message(200, msg)


@pytest.mark.asyncio
async def test_handle_position_message_converts_units_and_invokes_callback():
    cb = AsyncMock()
    vpf.register_update_callback(cb)
    vpf.load_vessel_map({200: 1})

    # lat/lon in degrees * 1e7; hdg in centidegrees; vx/vy in cm/s.
    msg = _make_msg(lat=480703800, lon=113100000, hdg=1800, vx=300, vy=400)
    await vpf.handle_position_message(200, msg)

    cb.assert_awaited_once()
    vessel_pk, lat, lon, heading, speed_kts = cb.await_args.args
    assert vessel_pk == 1
    assert lat == pytest.approx(48.07038)
    assert lon == pytest.approx(11.31)
    assert heading == pytest.approx(18.0)

    # vx=3 m/s, vy=4 m/s -> speed_ms = 5.0 -> knots = 5 * 1.94384
    assert speed_kts == pytest.approx(5 * 1.94384)


@pytest.mark.asyncio
async def test_handle_position_message_heading_sentinel_is_none():
    cb = AsyncMock()
    vpf.register_update_callback(cb)
    vpf.load_vessel_map({201: 2})

    msg = _make_msg(lat=1, lon=1, hdg=65535, vx=0, vy=0)
    await vpf.handle_position_message(201, msg)

    cb.assert_awaited_once()
    _, _, _, heading, _ = cb.await_args.args
    assert heading is None


@pytest.mark.asyncio
async def test_handle_position_message_zero_velocity_gives_zero_speed():
    cb = AsyncMock()
    vpf.register_update_callback(cb)
    vpf.load_vessel_map({202: 3})

    msg = _make_msg(lat=1, lon=1, hdg=0, vx=0, vy=0)
    await vpf.handle_position_message(202, msg)

    _, _, _, _, speed_kts = cb.await_args.args
    assert speed_kts == pytest.approx(0.0)


@pytest.mark.asyncio
async def test_handle_position_message_callback_exception_is_swallowed():
    cb = AsyncMock(side_effect=RuntimeError("db down"))
    vpf.register_update_callback(cb)
    vpf.load_vessel_map({203: 4})

    msg = _make_msg(lat=1, lon=1, hdg=0, vx=0, vy=0)

    # Should not propagate the exception raised inside the callback.
    await vpf.handle_position_message(203, msg)
    cb.assert_awaited_once()


@pytest.mark.asyncio
async def test_handle_position_message_maps_correct_vessel_pk_from_boundary_ids():
    cb = AsyncMock()
    vpf.register_update_callback(cb)
    vpf.load_vessel_map({200: 1, 239: 40})

    msg = _make_msg(lat=1, lon=1, hdg=0, vx=0, vy=0)

    await vpf.handle_position_message(200, msg)
    assert cb.await_args.args[0] == 1

    await vpf.handle_position_message(239, msg)
    assert cb.await_args.args[0] == 40
