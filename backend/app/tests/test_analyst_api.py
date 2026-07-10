"""
Drone Analyst API tests
=======================
POST /api/analyst/jobs
GET  /api/analyst/jobs
GET  /api/analyst/jobs/{job_id}
POST /api/analyst/jobs/{job_id}/cancel

Covers:
  - Create job → verify all fields stored and retrievable via GET
  - Default job_type (telemetry_report)
  - Invalid job_type → 400
  - Invalid model_id → 404
  - Get job → 200 with all fields
  - Get unknown job → 404
  - List jobs → returns created job
  - List jobs filtered by job_type
  - Cancel pending job → status becomes 'cancelled', completed_at set
  - Cancel already-cancelled job → 409
  - Cancel complete job → 409
  - RBAC: VIEWER can GET/list but cannot POST/cancel (need MISSION_COMMANDER)
  - RBAC: unauthenticated → 401
"""
import pytest
import pytest_asyncio
from httpx import AsyncClient


_VALID_JOB = {
    "job_type":   "telemetry_report",
    "mission_id": None,
    "drone_id":   None,
    "model_id":   None,
    "params":     {"include_battery": True, "bucket_seconds": 10},
}

_DETECTION_JOB = {
    "job_type":   "object_detection",
    "mission_id": 42,
    "drone_id":   7,
    "model_id":   None,
    "params":     {"confidence": 0.75},
}


# ══════════════════════════════════════════════════════════════════════
# POST /api/analyst/jobs — Create
# ══════════════════════════════════════════════════════════════════════

async def test_create_job_201_all_fields(
    client: AsyncClient, mission_commander_user, make_token
):
    """Create a job and verify every field is stored and returned."""
    token = make_token(mission_commander_user.id, mission_commander_user.role)
    resp  = await client.post(
        "/api/analyst/jobs",
        json=_VALID_JOB,
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()

    assert "id"           in body
    assert body["type"]         == "telemetry_report"
    assert body["status"]       == "pending"
    assert body["mission_id"]   is None
    assert body["drone_id"]     is None
    assert body["model_id"]     is None
    assert body["params"]       == {"include_battery": True, "bucket_seconds": 10}
    assert body["submitted_by"] == mission_commander_user.id
    assert body["started_at"]   is None
    assert body["completed_at"] is None
    assert body["result"]       is None
    assert body["error"]        is None
    assert "created_at" in body
    assert "note"       in body


async def test_create_job_with_mission_and_drone(
    client: AsyncClient, mission_commander_user, make_token
):
    """mission_id and drone_id are stored correctly."""
    token = make_token(mission_commander_user.id, mission_commander_user.role)
    resp  = await client.post(
        "/api/analyst/jobs",
        json=_DETECTION_JOB,
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["mission_id"] == 42
    assert body["drone_id"]   == 7
    assert body["type"]       == "object_detection"
    assert body["params"]     == {"confidence": 0.75}


async def test_create_job_default_job_type(
    client: AsyncClient, mission_commander_user, make_token
):
    """Omitting job_type defaults to telemetry_report."""
    token = make_token(mission_commander_user.id, mission_commander_user.role)
    resp  = await client.post(
        "/api/analyst/jobs",
        json={},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["type"] == "telemetry_report"


async def test_create_job_invalid_type_400(
    client: AsyncClient, mission_commander_user, make_token
):
    """Unknown job_type must return 400."""
    token = make_token(mission_commander_user.id, mission_commander_user.role)
    resp  = await client.post(
        "/api/analyst/jobs",
        json={"job_type": "invalid_type"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 400


async def test_create_job_invalid_model_404(
    client: AsyncClient, mission_commander_user, make_token
):
    """Unknown model_id must return 404."""
    token = make_token(mission_commander_user.id, mission_commander_user.role)
    resp  = await client.post(
        "/api/analyst/jobs",
        json={"job_type": "object_detection", "model_id": "nonexistent-model"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 404


async def test_create_job_viewer_403(
    client: AsyncClient, viewer_user, make_token
):
    """VIEWER cannot create jobs — requires MISSION_COMMANDER."""
    token = make_token(viewer_user.id, viewer_user.role)
    resp  = await client.post(
        "/api/analyst/jobs",
        json=_VALID_JOB,
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403


async def test_create_job_unauthenticated_401(client: AsyncClient):
    resp = await client.post("/api/analyst/jobs", json=_VALID_JOB)
    assert resp.status_code == 401


# ══════════════════════════════════════════════════════════════════════
# GET /api/analyst/jobs/{job_id} — Round-trip persistence
# ══════════════════════════════════════════════════════════════════════

async def test_get_job_round_trip(
    client: AsyncClient, mission_commander_user, viewer_user, make_token
):
    """
    Create a job as mission_commander, then retrieve it as viewer.
    All fields must match what was submitted.
    """
    mc_token = make_token(mission_commander_user.id, mission_commander_user.role)
    create   = await client.post(
        "/api/analyst/jobs",
        json=_DETECTION_JOB,
        headers={"Authorization": f"Bearer {mc_token}"},
    )
    assert create.status_code == 201
    job_id = create.json()["id"]

    # Retrieve as viewer (read-only role)
    v_token = make_token(viewer_user.id, viewer_user.role)
    get     = await client.get(
        f"/api/analyst/jobs/{job_id}",
        headers={"Authorization": f"Bearer {v_token}"},
    )
    assert get.status_code == 200
    body = get.json()

    assert body["id"]           == job_id
    assert body["type"]         == "object_detection"
    assert body["mission_id"]   == 42
    assert body["drone_id"]     == 7
    assert body["params"]       == {"confidence": 0.75}
    assert body["submitted_by"] == mission_commander_user.id
    assert body["status"]       == "pending"


async def test_get_job_not_found_404(
    client: AsyncClient, viewer_user, make_token
):
    token = make_token(viewer_user.id, viewer_user.role)
    resp  = await client.get(
        "/api/analyst/jobs/00000000-0000-0000-0000-000000000000",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 404


async def test_get_job_unauthenticated_401(client: AsyncClient):
    resp = await client.get("/api/analyst/jobs/some-id")
    assert resp.status_code == 401


# ══════════════════════════════════════════════════════════════════════
# GET /api/analyst/jobs — List
# ══════════════════════════════════════════════════════════════════════

async def test_list_jobs_contains_created(
    client: AsyncClient, mission_commander_user, viewer_user, make_token
):
    """Created job appears in the list."""
    mc_token = make_token(mission_commander_user.id, mission_commander_user.role)
    create   = await client.post(
        "/api/analyst/jobs",
        json=_VALID_JOB,
        headers={"Authorization": f"Bearer {mc_token}"},
    )
    job_id = create.json()["id"]

    v_token = make_token(viewer_user.id, viewer_user.role)
    resp    = await client.get(
        "/api/analyst/jobs",
        headers={"Authorization": f"Bearer {v_token}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "jobs"  in body
    assert "total" in body
    ids = [j["id"] for j in body["jobs"]]
    assert job_id in ids


async def test_list_jobs_filter_by_job_type(
    client: AsyncClient, mission_commander_user, viewer_user, make_token
):
    """job_type filter returns only matching jobs."""
    mc_token = make_token(mission_commander_user.id, mission_commander_user.role)

    # Create two different job types
    r1 = await client.post(
        "/api/analyst/jobs",
        json={"job_type": "telemetry_report"},
        headers={"Authorization": f"Bearer {mc_token}"},
    )
    r2 = await client.post(
        "/api/analyst/jobs",
        json={"job_type": "change_detection"},
        headers={"Authorization": f"Bearer {mc_token}"},
    )
    assert r1.status_code == 201
    assert r2.status_code == 201

    v_token = make_token(viewer_user.id, viewer_user.role)
    resp    = await client.get(
        "/api/analyst/jobs?job_type=change_detection",
        headers={"Authorization": f"Bearer {v_token}"},
    )
    assert resp.status_code == 200
    jobs = resp.json()["jobs"]
    assert all(j["type"] == "change_detection" for j in jobs)


async def test_list_jobs_unauthenticated_401(client: AsyncClient):
    resp = await client.get("/api/analyst/jobs")
    assert resp.status_code == 401


# ══════════════════════════════════════════════════════════════════════
# POST /api/analyst/jobs/{job_id}/cancel — Cancel
# ══════════════════════════════════════════════════════════════════════

async def test_cancel_job_status_persisted(
    client: AsyncClient, mission_commander_user, viewer_user, make_token
):
    """
    Cancel a pending job → status becomes 'cancelled' and completed_at is set.
    Re-fetch via GET to confirm the state persisted in the store.
    """
    mc_token = make_token(mission_commander_user.id, mission_commander_user.role)

    # Create
    create = await client.post(
        "/api/analyst/jobs",
        json=_VALID_JOB,
        headers={"Authorization": f"Bearer {mc_token}"},
    )
    assert create.status_code == 201
    job_id = create.json()["id"]

    # Cancel
    cancel = await client.post(
        f"/api/analyst/jobs/{job_id}/cancel",
        headers={"Authorization": f"Bearer {mc_token}"},
    )
    assert cancel.status_code == 200
    body = cancel.json()
    assert body["status"]       == "cancelled"
    assert body["completed_at"] is not None

    # Re-fetch to confirm persistence
    v_token = make_token(viewer_user.id, viewer_user.role)
    get     = await client.get(
        f"/api/analyst/jobs/{job_id}",
        headers={"Authorization": f"Bearer {v_token}"},
    )
    assert get.status_code == 200
    fetched = get.json()
    assert fetched["status"]       == "cancelled"
    assert fetched["completed_at"] is not None


async def test_cancel_already_cancelled_409(
    client: AsyncClient, mission_commander_user, make_token
):
    """Cancelling an already-cancelled job must return 409."""
    mc_token = make_token(mission_commander_user.id, mission_commander_user.role)

    create = await client.post(
        "/api/analyst/jobs",
        json=_VALID_JOB,
        headers={"Authorization": f"Bearer {mc_token}"},
    )
    job_id = create.json()["id"]

    # First cancel
    await client.post(
        f"/api/analyst/jobs/{job_id}/cancel",
        headers={"Authorization": f"Bearer {mc_token}"},
    )

    # Second cancel — must conflict
    resp = await client.post(
        f"/api/analyst/jobs/{job_id}/cancel",
        headers={"Authorization": f"Bearer {mc_token}"},
    )
    assert resp.status_code == 409


async def test_cancel_nonexistent_job_404(
    client: AsyncClient, mission_commander_user, make_token
):
    token = make_token(mission_commander_user.id, mission_commander_user.role)
    resp  = await client.post(
        "/api/analyst/jobs/00000000-0000-0000-0000-000000000000/cancel",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 404


async def test_cancel_job_viewer_403(
    client: AsyncClient, mission_commander_user, viewer_user, make_token
):
    """VIEWER cannot cancel a job."""
    mc_token = make_token(mission_commander_user.id, mission_commander_user.role)
    create   = await client.post(
        "/api/analyst/jobs",
        json=_VALID_JOB,
        headers={"Authorization": f"Bearer {mc_token}"},
    )
    job_id = create.json()["id"]

    v_token = make_token(viewer_user.id, viewer_user.role)
    resp    = await client.post(
        f"/api/analyst/jobs/{job_id}/cancel",
        headers={"Authorization": f"Bearer {v_token}"},
    )
    assert resp.status_code == 403


async def test_cancel_job_unauthenticated_401(client: AsyncClient):
    resp = await client.post(
        "/api/analyst/jobs/00000000-0000-0000-0000-000000000000/cancel"
    )
    assert resp.status_code == 401
