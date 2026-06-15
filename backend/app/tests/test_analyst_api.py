"""
Drone Analyst API tests
=======================
GET /api/analyst/status
POST /api/analyst/jobs
GET /api/analyst/jobs
GET /api/analyst/jobs/{job_id}
POST /api/analyst/jobs/{job_id}/cancel
GET /api/analyst/results
GET /api/analyst/models
GET /api/analyst/models/{model_id}

Covers:
  - Module status returns capability summary
  - Create job with valid type returns 201 with job record
  - Create job with invalid type → 400
  - Create job with unknown model_id → 404
  - List jobs returns a paginated list
  - Get job by ID returns the job record
  - Get non-existent job → 404
  - Cancel pending job transitions to "cancelled"
  - Cancel already-cancelled job → 409
  - Results stub returns empty list
  - Model registry list and detail
  - Get non-existent model → 404
  - RBAC: VIEWER blocked from create/cancel; unauthenticated → 401

Note: mission_stats and mission_series endpoints are omitted because
they query TimescaleDB directly (not mockable via dependency injection).
"""
import pytest
import pytest_asyncio
from httpx import AsyncClient


# ══════════════════════════════════════════════════════════════════════
# Module status
# ══════════════════════════════════════════════════════════════════════

async def test_analyst_status_200(client: AsyncClient, viewer_user, make_token):
    token = make_token(viewer_user.id, viewer_user.role)
    resp  = await client.get(
        "/api/analyst/status",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "module_version"      in body
    assert "ai_inference_ready"  in body
    assert "jobs"                in body
    assert "capabilities"        in body
    assert "registered_models"   in body


async def test_analyst_status_unauthenticated_401(client: AsyncClient):
    resp = await client.get("/api/analyst/status")
    assert resp.status_code == 401


# ══════════════════════════════════════════════════════════════════════
# Analysis jobs
# ══════════════════════════════════════════════════════════════════════

async def test_create_job_201(client: AsyncClient, admin_user, make_token):
    """MISSION_COMMANDER+ can submit a telemetry_report job."""
    token = make_token(admin_user.id, admin_user.role)
    resp  = await client.post(
        "/api/analyst/jobs",
        json={"job_type": "telemetry_report", "params": {}},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["type"]   == "telemetry_report"
    assert body["status"] == "pending"
    assert "id"           in body
    assert "created_at"   in body


async def test_create_job_invalid_type_400(
    client: AsyncClient, admin_user, make_token
):
    token = make_token(admin_user.id, admin_user.role)
    resp  = await client.post(
        "/api/analyst/jobs",
        json={"job_type": "self_destruct", "params": {}},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 400


async def test_create_job_unknown_model_404(
    client: AsyncClient, admin_user, make_token
):
    """Specifying a model_id not in the registry must return 404."""
    token = make_token(admin_user.id, admin_user.role)
    resp  = await client.post(
        "/api/analyst/jobs",
        json={"job_type": "object_detection", "model_id": "nonexistent-model-xyz"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 404


async def test_list_jobs_200(client: AsyncClient, viewer_user, make_token):
    token = make_token(viewer_user.id, viewer_user.role)
    resp  = await client.get(
        "/api/analyst/jobs",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "jobs"  in body
    assert "total" in body
    assert isinstance(body["jobs"], list)


async def test_get_job_200(client: AsyncClient, admin_user, make_token):
    """Create a job then retrieve it by ID."""
    token = make_token(admin_user.id, admin_user.role)
    hdrs  = {"Authorization": f"Bearer {token}"}

    create = await client.post(
        "/api/analyst/jobs",
        json={"job_type": "video_analysis"},
        headers=hdrs,
    )
    assert create.status_code == 201
    job_id = create.json()["id"]

    get = await client.get(f"/api/analyst/jobs/{job_id}", headers=hdrs)
    assert get.status_code == 200
    assert get.json()["id"] == job_id


async def test_get_job_not_found_404(
    client: AsyncClient, viewer_user, make_token
):
    token = make_token(viewer_user.id, viewer_user.role)
    resp  = await client.get(
        "/api/analyst/jobs/00000000-0000-0000-0000-000000000000",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 404


async def test_cancel_job_200(client: AsyncClient, admin_user, make_token):
    """Cancelling a pending job transitions it to 'cancelled'."""
    token = make_token(admin_user.id, admin_user.role)
    hdrs  = {"Authorization": f"Bearer {token}"}

    create = await client.post(
        "/api/analyst/jobs",
        json={"job_type": "change_detection"},
        headers=hdrs,
    )
    assert create.status_code == 201
    job_id = create.json()["id"]

    cancel = await client.post(
        f"/api/analyst/jobs/{job_id}/cancel",
        headers=hdrs,
    )
    assert cancel.status_code == 200
    assert cancel.json()["status"] == "cancelled"


async def test_cancel_already_cancelled_409(
    client: AsyncClient, admin_user, make_token
):
    """Cancelling a job that is already cancelled must return 409."""
    token = make_token(admin_user.id, admin_user.role)
    hdrs  = {"Authorization": f"Bearer {token}"}

    create = await client.post(
        "/api/analyst/jobs",
        json={"job_type": "telemetry_report"},
        headers=hdrs,
    )
    assert create.status_code == 201
    job_id = create.json()["id"]

    # First cancel
    await client.post(f"/api/analyst/jobs/{job_id}/cancel", headers=hdrs)
    # Second cancel — must be rejected
    resp = await client.post(f"/api/analyst/jobs/{job_id}/cancel", headers=hdrs)
    assert resp.status_code == 409


# ══════════════════════════════════════════════════════════════════════
# Detection results (V1 stub)
# ══════════════════════════════════════════════════════════════════════

async def test_list_results_stub_200(client: AsyncClient, viewer_user, make_token):
    """V1 stub returns an empty results list with a note."""
    token = make_token(viewer_user.id, viewer_user.role)
    resp  = await client.get(
        "/api/analyst/results",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"]   == 0
    assert "results"       in body
    assert "note"          in body


async def test_list_results_with_mission_filter_200(
    client: AsyncClient, viewer_user, make_token
):
    token = make_token(viewer_user.id, viewer_user.role)
    resp  = await client.get(
        "/api/analyst/results?mission_id=1",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["mission_id"] == 1


# ══════════════════════════════════════════════════════════════════════
# Model registry
# ══════════════════════════════════════════════════════════════════════

async def test_list_models_200(client: AsyncClient, viewer_user, make_token):
    token = make_token(viewer_user.id, viewer_user.role)
    resp  = await client.get(
        "/api/analyst/models",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "models" in body
    assert "total"  in body
    assert body["total"] >= 3    # at least the 3 seeded models
    for model in body["models"]:
        assert "id"     in model
        assert "name"   in model
        assert "status" in model


async def test_get_model_200(client: AsyncClient, viewer_user, make_token):
    """Retrieve a known model from the registry."""
    token = make_token(viewer_user.id, viewer_user.role)
    resp  = await client.get(
        "/api/analyst/models/yolov8n-coco",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"]   == "yolov8n-coco"
    assert body["type"] == "object_detection"


async def test_get_model_not_found_404(client: AsyncClient, viewer_user, make_token):
    token = make_token(viewer_user.id, viewer_user.role)
    resp  = await client.get(
        "/api/analyst/models/nonexistent-model",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 404


# ══════════════════════════════════════════════════════════════════════
# RBAC
# ══════════════════════════════════════════════════════════════════════

async def test_viewer_blocked_from_create_job_403(
    client: AsyncClient, viewer_user, make_token
):
    token = make_token(viewer_user.id, viewer_user.role)
    resp  = await client.post(
        "/api/analyst/jobs",
        json={"job_type": "telemetry_report"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403


async def test_viewer_blocked_from_cancel_job_403(
    client: AsyncClient, admin_user, viewer_user, make_token
):
    """VIEWER cannot cancel a job even if it exists."""
    ad_token = make_token(admin_user.id, admin_user.role)
    create   = await client.post(
        "/api/analyst/jobs",
        json={"job_type": "telemetry_report"},
        headers={"Authorization": f"Bearer {ad_token}"},
    )
    assert create.status_code == 201
    job_id = create.json()["id"]

    vw_token = make_token(viewer_user.id, viewer_user.role)
    resp     = await client.post(
        f"/api/analyst/jobs/{job_id}/cancel",
        headers={"Authorization": f"Bearer {vw_token}"},
    )
    assert resp.status_code == 403


async def test_analyst_jobs_unauthenticated_401(client: AsyncClient):
    resp = await client.get("/api/analyst/jobs")
    assert resp.status_code == 401


async def test_analyst_models_unauthenticated_401(client: AsyncClient):
    resp = await client.get("/api/analyst/models")
    assert resp.status_code == 401
