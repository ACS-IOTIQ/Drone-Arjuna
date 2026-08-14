"""
Analyst Job Artifact Tests — MinIO-backed images, videos, PDF reports
=======================================================================
POST   /api/analyst/jobs/{job_id}/artifacts               — upload a file
GET    /api/analyst/jobs/{job_id}/artifacts                — list files
GET    /api/analyst/jobs/{job_id}/artifacts/{artifact_id}  — presigned URL
DELETE /api/analyst/jobs/{job_id}/artifacts/{artifact_id}  — delete

Wiring under test
------------------
  AnalystService.upload_artifact() classifies the upload's content type
  into a kind (image/video/report_pdf) via app.core.storage.classify_content_type,
  builds an object key, uploads bytes to MinIO, and persists a JobArtifact
  row. Only image/*, video/*, and application/pdf are accepted — anything
  else is rejected with 400 before touching MinIO.

All actual MinIO I/O is mocked — these tests verify the wiring (kind
classification, object key generation, persistence, filtering, 404s,
RBAC) without requiring a live MinIO instance.

Covers:
  - Upload PNG image → kind='image', persisted, retrievable
  - Upload MP4 video → kind='video'
  - Upload PDF report → kind='report_pdf'
  - Upload unsupported content type (e.g. text/plain) → 400, MinIO untouched
  - List artifacts for a job → returns all uploaded
  - List artifacts filtered by kind
  - List artifacts for nonexistent job → 404
  - Get presigned URL for an artifact → 200 with url
  - Get presigned URL for unknown artifact_id → 404
  - Get presigned URL for artifact belonging to a different job → 404
  - Delete artifact → removed from MinIO and from listing
  - Delete unknown artifact → 404
  - RBAC: VIEWER can list/get but not upload/delete (needs MISSION_COMMANDER)
  - Unauthenticated → 401 on all endpoints
"""
import pytest
from unittest.mock import AsyncMock, patch
from httpx import AsyncClient

_VALID_JOB = {"job_type": "object_detection", "params": {}}


def _patch_storage(presign_return="http://minio.local/da-analyst-imagery/jobs/x/y?sig=abc"):
    return (
        patch("app.core.storage.ensure_bucket", new_callable=AsyncMock),
        patch("app.core.storage.upload_bytes", new_callable=AsyncMock),
        patch(
            "app.core.storage.get_presigned_url",
            new_callable=AsyncMock,
            return_value=presign_return,
        ),
        patch("app.core.storage.delete_object", new_callable=AsyncMock),
    )


async def _create_job(client: AsyncClient, token: str) -> str:
    resp = await client.post(
        "/api/analyst/jobs",
        json=_VALID_JOB,
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def _upload(client, job_id, token, filename, content, content_type):
    ensure_p, upload_p, _, _ = _patch_storage()
    with ensure_p, upload_p:
        return await client.post(
            f"/api/analyst/jobs/{job_id}/artifacts",
            headers={"Authorization": f"Bearer {token}"},
            files={"file": (filename, content, content_type)},
        )


# ══════════════════════════════════════════════════════════════════════
# POST /api/analyst/jobs/{job_id}/artifacts — Upload
# ══════════════════════════════════════════════════════════════════════

async def test_upload_image_classified_correctly(
    client: AsyncClient, mission_commander_user, make_token
):
    token = make_token(mission_commander_user.id, mission_commander_user.role)
    job_id = await _create_job(client, token)

    resp = await _upload(client, job_id, token, "frame001.png", b"pngbytes", "image/png")
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["kind"] == "image"
    assert body["job_id"] == job_id
    assert body["filename"] == "frame001.png"
    assert body["content_type"] == "image/png"
    assert body["size_bytes"] == len(b"pngbytes")
    assert body["object_key"].startswith(f"jobs/{job_id}/")
    assert body["uploaded_by"] == mission_commander_user.id


async def test_upload_video_classified_correctly(
    client: AsyncClient, mission_commander_user, make_token
):
    token = make_token(mission_commander_user.id, mission_commander_user.role)
    job_id = await _create_job(client, token)

    resp = await _upload(client, job_id, token, "flight.mp4", b"mp4bytes", "video/mp4")
    assert resp.status_code == 201, resp.text
    assert resp.json()["kind"] == "video"


async def test_upload_pdf_report_classified_correctly(
    client: AsyncClient, mission_commander_user, make_token
):
    token = make_token(mission_commander_user.id, mission_commander_user.role)
    job_id = await _create_job(client, token)

    resp = await _upload(
        client, job_id, token, "mission_report.pdf", b"%PDF-1.4 fake", "application/pdf"
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["kind"] == "report_pdf"


async def test_upload_calls_storage_with_correct_args(
    client: AsyncClient, mission_commander_user, make_token
):
    token = make_token(mission_commander_user.id, mission_commander_user.role)
    job_id = await _create_job(client, token)

    ensure_p, upload_p, _, _ = _patch_storage()
    with ensure_p as mock_ensure, upload_p as mock_upload:
        resp = await client.post(
            f"/api/analyst/jobs/{job_id}/artifacts",
            headers={"Authorization": f"Bearer {token}"},
            files={"file": ("scene.jpg", b"jpgdata", "image/jpeg")},
        )
    assert resp.status_code == 201
    mock_ensure.assert_awaited_once()
    mock_upload.assert_awaited_once()
    key, data, content_type = mock_upload.call_args.args
    assert key.startswith(f"jobs/{job_id}/")
    assert key.endswith("_scene.jpg")
    assert data == b"jpgdata"
    assert content_type == "image/jpeg"


async def test_upload_unsupported_content_type_rejected(
    client: AsyncClient, mission_commander_user, make_token
):
    """A content type outside image/video/pdf must be rejected before touching MinIO."""
    token = make_token(mission_commander_user.id, mission_commander_user.role)
    job_id = await _create_job(client, token)

    ensure_p, upload_p, _, _ = _patch_storage()
    with ensure_p as mock_ensure, upload_p as mock_upload:
        resp = await client.post(
            f"/api/analyst/jobs/{job_id}/artifacts",
            headers={"Authorization": f"Bearer {token}"},
            files={"file": ("notes.txt", b"plain text", "text/plain")},
        )
    assert resp.status_code == 400
    mock_ensure.assert_not_awaited()
    mock_upload.assert_not_awaited()


async def test_upload_nonexistent_job_404(
    client: AsyncClient, mission_commander_user, make_token
):
    token = make_token(mission_commander_user.id, mission_commander_user.role)
    resp = await _upload(
        client, "00000000-0000-0000-0000-000000000000", token,
        "x.jpg", b"data", "image/jpeg",
    )
    assert resp.status_code == 404


async def test_upload_viewer_403(
    client: AsyncClient, mission_commander_user, viewer_user, make_token
):
    mc_token = make_token(mission_commander_user.id, mission_commander_user.role)
    job_id = await _create_job(client, mc_token)

    v_token = make_token(viewer_user.id, viewer_user.role)
    resp = await _upload(client, job_id, v_token, "x.jpg", b"data", "image/jpeg")
    assert resp.status_code == 403


async def test_upload_unauthenticated_401(client: AsyncClient):
    resp = await client.post(
        "/api/analyst/jobs/00000000-0000-0000-0000-000000000000/artifacts",
        files={"file": ("x.jpg", b"data", "image/jpeg")},
    )
    assert resp.status_code == 401


# ══════════════════════════════════════════════════════════════════════
# GET /api/analyst/jobs/{job_id}/artifacts — List
# ══════════════════════════════════════════════════════════════════════

async def test_list_artifacts_returns_all_uploaded(
    client: AsyncClient, mission_commander_user, viewer_user, make_token
):
    mc_token = make_token(mission_commander_user.id, mission_commander_user.role)
    job_id = await _create_job(client, mc_token)

    await _upload(client, job_id, mc_token, "a.jpg", b"1", "image/jpeg")
    await _upload(client, job_id, mc_token, "b.mp4", b"2", "video/mp4")
    await _upload(client, job_id, mc_token, "c.pdf", b"3", "application/pdf")

    v_token = make_token(viewer_user.id, viewer_user.role)
    resp = await client.get(
        f"/api/analyst/jobs/{job_id}/artifacts",
        headers={"Authorization": f"Bearer {v_token}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 3
    kinds = {a["kind"] for a in body["artifacts"]}
    assert kinds == {"image", "video", "report_pdf"}


async def test_list_artifacts_filtered_by_kind(
    client: AsyncClient, mission_commander_user, viewer_user, make_token
):
    mc_token = make_token(mission_commander_user.id, mission_commander_user.role)
    job_id = await _create_job(client, mc_token)

    await _upload(client, job_id, mc_token, "a.jpg", b"1", "image/jpeg")
    await _upload(client, job_id, mc_token, "b.pdf", b"2", "application/pdf")

    v_token = make_token(viewer_user.id, viewer_user.role)
    resp = await client.get(
        f"/api/analyst/jobs/{job_id}/artifacts?kind=report_pdf",
        headers={"Authorization": f"Bearer {v_token}"},
    )
    assert resp.status_code == 200
    artifacts = resp.json()["artifacts"]
    assert len(artifacts) == 1
    assert artifacts[0]["kind"] == "report_pdf"


async def test_list_artifacts_nonexistent_job_404(
    client: AsyncClient, viewer_user, make_token
):
    token = make_token(viewer_user.id, viewer_user.role)
    resp = await client.get(
        "/api/analyst/jobs/00000000-0000-0000-0000-000000000000/artifacts",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 404


async def test_list_artifacts_unauthenticated_401(client: AsyncClient):
    resp = await client.get(
        "/api/analyst/jobs/00000000-0000-0000-0000-000000000000/artifacts"
    )
    assert resp.status_code == 401


# ══════════════════════════════════════════════════════════════════════
# GET /api/analyst/jobs/{job_id}/artifacts/{artifact_id} — Presigned URL
# ══════════════════════════════════════════════════════════════════════

async def test_get_artifact_url(
    client: AsyncClient, mission_commander_user, viewer_user, make_token
):
    mc_token = make_token(mission_commander_user.id, mission_commander_user.role)
    job_id = await _create_job(client, mc_token)
    upload_resp = await _upload(client, job_id, mc_token, "a.jpg", b"1", "image/jpeg")
    artifact_id = upload_resp.json()["id"]

    v_token = make_token(viewer_user.id, viewer_user.role)
    _, _, presign_p, _ = _patch_storage()
    with presign_p as mock_presign:
        resp = await client.get(
            f"/api/analyst/jobs/{job_id}/artifacts/{artifact_id}",
            headers={"Authorization": f"Bearer {v_token}"},
        )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["artifact_id"] == artifact_id
    assert body["job_id"] == job_id
    assert body["kind"] == "image"
    assert body["url"].startswith("http://minio.local/")
    mock_presign.assert_awaited_once()


async def test_get_artifact_url_unknown_artifact_404(
    client: AsyncClient, mission_commander_user, make_token
):
    token = make_token(mission_commander_user.id, mission_commander_user.role)
    job_id = await _create_job(client, token)
    resp = await client.get(
        f"/api/analyst/jobs/{job_id}/artifacts/00000000-0000-0000-0000-000000000000",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 404


async def test_get_artifact_url_wrong_job_404(
    client: AsyncClient, mission_commander_user, make_token
):
    """An artifact_id that belongs to a different job must 404, not leak cross-job."""
    token = make_token(mission_commander_user.id, mission_commander_user.role)
    job_a = await _create_job(client, token)
    job_b = await _create_job(client, token)

    upload_resp = await _upload(client, job_a, token, "a.jpg", b"1", "image/jpeg")
    artifact_id = upload_resp.json()["id"]

    resp = await client.get(
        f"/api/analyst/jobs/{job_b}/artifacts/{artifact_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 404


async def test_get_artifact_url_unauthenticated_401(client: AsyncClient):
    resp = await client.get(
        "/api/analyst/jobs/00000000-0000-0000-0000-000000000000/artifacts/"
        "00000000-0000-0000-0000-000000000000"
    )
    assert resp.status_code == 401


# ══════════════════════════════════════════════════════════════════════
# DELETE /api/analyst/jobs/{job_id}/artifacts/{artifact_id}
# ══════════════════════════════════════════════════════════════════════

async def test_delete_artifact_removes_from_listing(
    client: AsyncClient, mission_commander_user, make_token
):
    token = make_token(mission_commander_user.id, mission_commander_user.role)
    job_id = await _create_job(client, token)
    upload_resp = await _upload(client, job_id, token, "a.jpg", b"1", "image/jpeg")
    artifact_id = upload_resp.json()["id"]

    _, _, _, delete_p = _patch_storage()
    with delete_p as mock_delete:
        resp = await client.delete(
            f"/api/analyst/jobs/{job_id}/artifacts/{artifact_id}",
            headers={"Authorization": f"Bearer {token}"},
        )
    assert resp.status_code == 204
    mock_delete.assert_awaited_once()

    list_resp = await client.get(
        f"/api/analyst/jobs/{job_id}/artifacts",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert list_resp.json()["total"] == 0


async def test_delete_unknown_artifact_404(
    client: AsyncClient, mission_commander_user, make_token
):
    token = make_token(mission_commander_user.id, mission_commander_user.role)
    job_id = await _create_job(client, token)
    resp = await client.delete(
        f"/api/analyst/jobs/{job_id}/artifacts/00000000-0000-0000-0000-000000000000",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 404


async def test_delete_artifact_viewer_403(
    client: AsyncClient, mission_commander_user, viewer_user, make_token
):
    mc_token = make_token(mission_commander_user.id, mission_commander_user.role)
    job_id = await _create_job(client, mc_token)
    upload_resp = await _upload(client, job_id, mc_token, "a.jpg", b"1", "image/jpeg")
    artifact_id = upload_resp.json()["id"]

    v_token = make_token(viewer_user.id, viewer_user.role)
    resp = await client.delete(
        f"/api/analyst/jobs/{job_id}/artifacts/{artifact_id}",
        headers={"Authorization": f"Bearer {v_token}"},
    )
    assert resp.status_code == 403


async def test_delete_artifact_unauthenticated_401(client: AsyncClient):
    resp = await client.delete(
        "/api/analyst/jobs/00000000-0000-0000-0000-000000000000/artifacts/"
        "00000000-0000-0000-0000-000000000000"
    )
    assert resp.status_code == 401
