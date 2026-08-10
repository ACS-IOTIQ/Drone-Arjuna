"""
Fleet Assignment API tests
==========================
POST /api/flight/assign-fleet

Covers:
  - RBAC: VIEWER blocked, unauthenticated blocked
  - 400 when no connected drones / no targets
  - Classical (OR-Tools) happy path — exact, feasible, correct solver label
  - Quantum (QAOA on Qiskit Aer) happy path — feasible, correct solver label
  - drone_instance_ids filters which live drones are considered

Live drone positions come from mavlink_manager.state (an in-memory hot
cache), not the DB, so tests seed it directly rather than going through
a real MAVLink connection.
"""
import pytest_asyncio
from httpx import AsyncClient

from app.modules.drone_control.mavlink_manager import mavlink_manager

_TARGETS = [
    {"id": "T1", "lat": 17.40, "lon": 78.50},
    {"id": "T2", "lat": 17.36, "lon": 78.46},
]


@pytest_asyncio.fixture
async def two_connected_drones():
    """Seeds the live telemetry hot-cache with two connected drones."""
    ids = [501, 502]
    positions = [(17.38, 78.48), (17.34, 78.44)]
    for did, (lat, lon) in zip(ids, positions):
        mavlink_manager.state.init_drone(did, f"DRN-{did}")
        await mavlink_manager.state.update(did, {"lat": lat, "lon": lon, "connected": True})
    yield ids
    for did in ids:
        mavlink_manager.state.remove_drone(did)


# ══════════════════════════════════════════════════════════════════════
# RBAC / auth
# ══════════════════════════════════════════════════════════════════════

async def test_assign_fleet_unauthenticated_401(client: AsyncClient):
    resp = await client.post("/api/flight/assign-fleet", json={"targets": _TARGETS})
    assert resp.status_code == 401


async def test_assign_fleet_viewer_403(client: AsyncClient, viewer_user, make_token):
    token = make_token(viewer_user.id, viewer_user.role)
    resp = await client.post(
        "/api/flight/assign-fleet",
        json={"targets": _TARGETS},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403


# ══════════════════════════════════════════════════════════════════════
# Validation
# ══════════════════════════════════════════════════════════════════════

async def test_assign_fleet_no_connected_drones_400(
    client: AsyncClient, flight_controller_user, make_token
):
    """No drones in the live state cache → 400, not a 500."""
    token = make_token(flight_controller_user.id, flight_controller_user.role)
    resp = await client.post(
        "/api/flight/assign-fleet",
        json={"targets": _TARGETS},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 400


async def test_assign_fleet_no_targets_400(
    client: AsyncClient, flight_controller_user, two_connected_drones, make_token
):
    token = make_token(flight_controller_user.id, flight_controller_user.role)
    resp = await client.post(
        "/api/flight/assign-fleet",
        json={"targets": []},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 400


# ══════════════════════════════════════════════════════════════════════
# Classical solver (default)
# ══════════════════════════════════════════════════════════════════════

async def test_assign_fleet_classical_200(
    client: AsyncClient, flight_controller_user, two_connected_drones, make_token
):
    token = make_token(flight_controller_user.id, flight_controller_user.role)
    resp = await client.post(
        "/api/flight/assign-fleet",
        json={"targets": _TARGETS},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["solver"] == "OR-Tools"
    assert body["all_feasible"] is True
    assert body["num_subproblems"] == 1
    assigned_targets = {a["target_id"] for a in body["assignments"]}
    assert assigned_targets == {"T1", "T2"}


async def test_assign_fleet_drone_filter(
    client: AsyncClient, flight_controller_user, two_connected_drones, make_token
):
    """drone_instance_ids restricts the live fleet considered for assignment."""
    token = make_token(flight_controller_user.id, flight_controller_user.role)
    only_first = two_connected_drones[0]
    resp = await client.post(
        "/api/flight/assign-fleet",
        json={"drone_instance_ids": [only_first], "targets": _TARGETS},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert all(a["drone_instance_id"] == only_first for a in body["assignments"])


# ══════════════════════════════════════════════════════════════════════
# Quantum solver (opt-in, QAOA on Qiskit Aer)
# ══════════════════════════════════════════════════════════════════════

async def test_assign_fleet_quantum_200(
    client: AsyncClient, flight_controller_user, two_connected_drones, make_token
):
    """use_quantum=True runs real QAOA circuits and returns a feasible assignment."""
    token = make_token(flight_controller_user.id, flight_controller_user.role)
    resp = await client.post(
        "/api/flight/assign-fleet",
        json={"targets": [_TARGETS[0]], "use_quantum": True, "qubit_budget": 12},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["solver"] == "QAOA (Aer)"
    assert body["all_feasible"] is True
    assert len(body["assignments"]) == 1
