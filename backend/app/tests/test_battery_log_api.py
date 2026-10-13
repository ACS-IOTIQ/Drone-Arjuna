"""
Battery log endpoint tests
==========================
GET /api/drone-control/telemetry/{drone_id}/battery-log

Battery % snapshots (one every ~2 minutes while a mission, simulated or live, is
running) read from the TimescaleDB `battery_snapshots` table. The telemetry DB
session is replaced through `app.dependency_overrides[get_ts_db]` with a recorder,
the same technique test_telemetry_endpoints.py uses for /history.

Covers:
  - response shape and ordering (as returned by the query, oldest first)
  - empty result, null mission_id
  - the query: right table, drone filter, time window, ascending order
  - default window = last 24 h; start/end overrides, partial overrides
  - validation: non-integer drone id, unparseable timestamps -> 422
  - no drone-existence check (a drone with no snapshots just returns [])
  - RBAC: VIEWER and above; unauthenticated -> 401
"""
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import AsyncClient

from app.database import get_ts_db as _get_ts_db

URL = "/api/drone-control/telemetry/{}/battery-log"


def _auth(user, make_token) -> dict:
    return {"Authorization": f"Bearer {make_token(user.id, user.role)}"}


T0 = datetime(2026, 10, 10, 9, 0, 0, tzinfo=timezone.utc)


def _row(minutes, pct, mission_id=None):
    return {"recorded_at": T0 + timedelta(minutes=minutes), "battery_pct": pct, "mission_id": mission_id}


@pytest.fixture
def ts(client):
    """Install a fake telemetry session; returns an object to set rows / inspect the query."""
    from app.main import app

    state = MagicMock()
    state.rows = []
    result = MagicMock()
    result.mappings.return_value.all.side_effect = lambda: list(state.rows)
    session = AsyncMock()
    session.execute = AsyncMock(return_value=result)
    state.session = session

    async def _override():
        yield session

    app.dependency_overrides[_get_ts_db] = _override
    try:
        yield state
    finally:
        app.dependency_overrides.pop(_get_ts_db, None)


def _query(state):
    """(sql text, bound params) of the single query the endpoint ran."""
    (stmt, params), _ = state.session.execute.await_args
    return str(stmt), params


# ══════════════════════════════════════════════════════════════════════
# Response
# ══════════════════════════════════════════════════════════════════════

async def test_returns_snapshots_in_the_order_the_query_gives(
    client: AsyncClient, viewer_user, make_token, ts
):
    ts.rows = [_row(0, 96, 4), _row(2, 94, 4), _row(4, 91, 4)]
    r = await client.get(URL.format(3), headers=_auth(viewer_user, make_token))
    assert r.status_code == 200, r.text
    body = r.json()
    assert [p["battery_remaining_pct"] for p in body] == [96, 94, 91]
    assert [p["timestamp"] for p in body] == sorted(p["timestamp"] for p in body)


async def test_each_point_has_exactly_the_fields_the_chart_reads(
    client: AsyncClient, viewer_user, make_token, ts
):
    ts.rows = [_row(0, 88, 12)]
    r = await client.get(URL.format(3), headers=_auth(viewer_user, make_token))
    point = r.json()[0]
    assert set(point) == {"timestamp", "battery_remaining_pct", "mission_id"}
    assert point["mission_id"] == 12
    assert point["timestamp"].startswith("2026-10-10T09:00:00")


async def test_snapshot_outside_a_mission_has_null_mission_id(
    client: AsyncClient, viewer_user, make_token, ts
):
    ts.rows = [_row(0, 70, None)]
    r = await client.get(URL.format(3), headers=_auth(viewer_user, make_token))
    assert r.json()[0]["mission_id"] is None


async def test_no_snapshots_is_an_empty_list_not_404(
    client: AsyncClient, viewer_user, make_token, ts
):
    r = await client.get(URL.format(999_999), headers=_auth(viewer_user, make_token))
    assert r.status_code == 200
    assert r.json() == []


# ══════════════════════════════════════════════════════════════════════
# The query
# ══════════════════════════════════════════════════════════════════════

async def test_query_reads_battery_snapshots_for_the_requested_drone(
    client: AsyncClient, viewer_user, make_token, ts
):
    await client.get(URL.format(42), headers=_auth(viewer_user, make_token))
    sql, params = _query(ts)
    assert "battery_snapshots" in sql
    assert "telemetry_history" not in sql and "telemetry_gauges" not in sql
    assert "drone_id = :drone_id" in sql
    assert "BETWEEN :start AND :end" in sql
    assert "ORDER BY recorded_at ASC" in sql
    assert params["drone_id"] == 42


async def test_default_window_is_the_last_24_hours(
    client: AsyncClient, viewer_user, make_token, ts
):
    before = datetime.now(timezone.utc)
    await client.get(URL.format(3), headers=_auth(viewer_user, make_token))
    after = datetime.now(timezone.utc)
    _, params = _query(ts)
    assert params["end"].tzinfo is not None
    assert before <= params["end"] <= after
    assert params["end"] - params["start"] == timedelta(hours=24)


async def test_explicit_start_and_end_are_used_as_given(
    client: AsyncClient, viewer_user, make_token, ts
):
    r = await client.get(
        URL.format(3),
        params={"start": "2026-10-09T00:00:00+00:00", "end": "2026-10-09T06:00:00+00:00"},
        headers=_auth(viewer_user, make_token),
    )
    assert r.status_code == 200, r.text
    _, params = _query(ts)
    assert params["start"] == datetime(2026, 10, 9, 0, 0, tzinfo=timezone.utc)
    assert params["end"] == datetime(2026, 10, 9, 6, 0, tzinfo=timezone.utc)


async def test_only_end_given_start_is_24_hours_before_it(
    client: AsyncClient, viewer_user, make_token, ts
):
    await client.get(URL.format(3), params={"end": "2026-10-09T12:00:00+00:00"},
                     headers=_auth(viewer_user, make_token))
    _, params = _query(ts)
    assert params["end"] == datetime(2026, 10, 9, 12, 0, tzinfo=timezone.utc)
    assert params["start"] == datetime(2026, 10, 8, 12, 0, tzinfo=timezone.utc)


async def test_only_start_given_end_is_now(
    client: AsyncClient, viewer_user, make_token, ts
):
    start = datetime.now(timezone.utc) - timedelta(hours=3)
    before = datetime.now(timezone.utc)
    await client.get(URL.format(3), params={"start": start.isoformat()},
                     headers=_auth(viewer_user, make_token))
    _, params = _query(ts)
    assert params["start"] == start
    assert params["end"] >= before


async def test_timestamp_without_timezone_is_accepted(
    client: AsyncClient, viewer_user, make_token, ts
):
    r = await client.get(URL.format(3), params={"start": "2026-10-09T00:00:00"},
                         headers=_auth(viewer_user, make_token))
    assert r.status_code == 200


async def test_query_is_parameterised_not_interpolated(
    client: AsyncClient, viewer_user, make_token, ts
):
    await client.get(URL.format(5), headers=_auth(viewer_user, make_token))
    sql, params = _query(ts)
    assert "5" not in sql.replace("battery_snapshots", "")          # the id is a bind parameter
    assert {"drone_id", "start", "end"} == set(params)


# ══════════════════════════════════════════════════════════════════════
# Validation
# ══════════════════════════════════════════════════════════════════════

async def test_non_integer_drone_id_is_422(client: AsyncClient, viewer_user, make_token, ts):
    r = await client.get(URL.format("abc"), headers=_auth(viewer_user, make_token))
    assert r.status_code == 422
    ts.session.execute.assert_not_awaited()


@pytest.mark.parametrize("param", ["start", "end"])
@pytest.mark.parametrize("bad", ["yesterday", "2026-13-45T00:00:00Z", "not-a-date", "12345abc"])
async def test_unparseable_timestamp_is_422(
    client: AsyncClient, viewer_user, make_token, ts, param, bad
):
    r = await client.get(URL.format(3), params={param: bad}, headers=_auth(viewer_user, make_token))
    assert r.status_code == 422
    ts.session.execute.assert_not_awaited()


# ══════════════════════════════════════════════════════════════════════
# RBAC
# ══════════════════════════════════════════════════════════════════════

async def test_unauthenticated_401(client: AsyncClient, ts):
    r = await client.get(URL.format(3))
    assert r.status_code == 401
    ts.session.execute.assert_not_awaited()                          # auth fires before any DB access


async def test_viewer_allowed(client: AsyncClient, viewer_user, make_token, ts):
    assert (await client.get(URL.format(3), headers=_auth(viewer_user, make_token))).status_code == 200


async def test_flight_controller_allowed(client: AsyncClient, flight_controller_user, make_token, ts):
    r = await client.get(URL.format(3), headers=_auth(flight_controller_user, make_token))
    assert r.status_code == 200


async def test_admin_allowed(client: AsyncClient, admin_user, make_token, ts):
    assert (await client.get(URL.format(3), headers=_auth(admin_user, make_token))).status_code == 200


async def test_intelligence_analyst_is_outside_the_viewer_hierarchy(
    client: AsyncClient, intelligence_analyst_user, make_token, ts
):
    """INTELLIGENCE_ANALYST is a specialist role and not part of the VIEWER+ hierarchy."""
    r = await client.get(URL.format(3), headers=_auth(intelligence_analyst_user, make_token))
    assert r.status_code == 403
