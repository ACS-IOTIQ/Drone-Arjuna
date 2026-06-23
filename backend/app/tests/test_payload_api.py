"""
Payload Type API tests
======================
Tests the full CRUD surface for PayloadType:
  GET / POST / PUT / DELETE /api/master/payload-types

Covers:
  - Happy-path create / list / get / update / delete
  - Duplicate name → 409
  - Non-existent ID → 404
  - RBAC: VIEWER blocked from write operations
  - All fields round-trip correctly (DB persistence)

Note: The /api/master/payloads (payload instances) endpoints were removed
in the Payload table removal (migration 009). Only PayloadType remains.
"""
import pytest
import pytest_asyncio
from httpx import AsyncClient


# ── Shared request bodies ─────────────────────────────────────────────────────

_PT_BODY = {
    "name":         "EO Camera API Test",
    "manufacturer": "Test Systems Ltd",
    "model":        "EO-100T",
    "category":     "sensor",
}
_PT_BODY2 = {
    "name":         "LiDAR API Test",
    "manufacturer": "Test Systems Ltd",
    "model":        "LiDAR-200T",
    "category":     "sensor",
}


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def pt(client: AsyncClient, admin_user, make_token):
    """Creates a PayloadType row via POST; deletes it on teardown."""
    token = make_token(admin_user.id, admin_user.role)
    hdrs = {"Authorization": f"Bearer {token}"}

    resp = await client.post("/api/master/payload-types", json=_PT_BODY, headers=hdrs)
    assert resp.status_code == 201, resp.text
    data = resp.json()
    yield data

    await client.delete(f"/api/master/payload-types/{data['id']}", headers=hdrs)


# ═══════════════════════════════════════════════════════════════════════
# PayloadType — CRUD
# ═══════════════════════════════════════════════════════════════════════

async def test_create_payload_type_201(client: AsyncClient, admin_user, make_token):
    """Admin can create a payload type; response contains all required fields."""
    token = make_token(admin_user.id, admin_user.role)
    hdrs  = {"Authorization": f"Bearer {token}"}

    resp = await client.post("/api/master/payload-types", json=_PT_BODY2, headers=hdrs)
    assert resp.status_code == 201
    body = resp.json()
    assert body["name"]         == _PT_BODY2["name"]
    assert body["manufacturer"] == _PT_BODY2["manufacturer"]
    assert body["model"]        == _PT_BODY2["model"]
    assert "id"         in body
    assert "created_at" in body

    await client.delete(f"/api/master/payload-types/{body['id']}", headers=hdrs)


async def test_create_payload_type_duplicate_409(
    client: AsyncClient, admin_user, pt, make_token
):
    """Posting the same name twice must return 409 Conflict."""
    token = make_token(admin_user.id, admin_user.role)
    resp  = await client.post(
        "/api/master/payload-types",
        json={**_PT_BODY},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 409


async def test_list_payload_types_200(
    client: AsyncClient, viewer_user, pt, make_token
):
    """VIEWER can list all payload types; created fixture appears in results."""
    token = make_token(viewer_user.id, viewer_user.role)
    resp  = await client.get(
        "/api/master/payload-types",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)
    assert pt["id"] in [item["id"] for item in resp.json()]


async def test_get_payload_type_200(
    client: AsyncClient, viewer_user, pt, make_token
):
    """VIEWER can fetch a single payload type by ID."""
    token = make_token(viewer_user.id, viewer_user.role)
    resp  = await client.get(
        f"/api/master/payload-types/{pt['id']}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["name"] == _PT_BODY["name"]


async def test_get_payload_type_not_found_404(
    client: AsyncClient, viewer_user, make_token
):
    """Non-existent ID must return 404."""
    token = make_token(viewer_user.id, viewer_user.role)
    resp  = await client.get(
        "/api/master/payload-types/999999",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 404


async def test_update_payload_type_200(
    client: AsyncClient, admin_user, pt, make_token
):
    """Admin can update notes on an existing payload type."""
    token = make_token(admin_user.id, admin_user.role)
    resp  = await client.put(
        f"/api/master/payload-types/{pt['id']}",
        json={"notes": "Updated notes"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["notes"] == "Updated notes"


async def test_delete_payload_type_204(
    client: AsyncClient, admin_user, make_token
):
    """Admin can delete a payload type; it must be gone afterwards."""
    token = make_token(admin_user.id, admin_user.role)
    hdrs  = {"Authorization": f"Bearer {token}"}

    create = await client.post(
        "/api/master/payload-types",
        json={"name": "Deletable PT", "manufacturer": "Test Co", "model": "DEL-1"},
        headers=hdrs,
    )
    assert create.status_code == 201
    tid = create.json()["id"]

    delete = await client.delete(f"/api/master/payload-types/{tid}", headers=hdrs)
    assert delete.status_code == 204

    get = await client.get(f"/api/master/payload-types/{tid}", headers=hdrs)
    assert get.status_code == 404


async def test_viewer_blocked_from_create_payload_type_403(
    client: AsyncClient, viewer_user, make_token
):
    """VIEWER must receive 403 when trying to create a payload type."""
    token = make_token(viewer_user.id, viewer_user.role)
    resp  = await client.post(
        "/api/master/payload-types",
        json={"name": "Should Not Exist", "manufacturer": "X", "model": "Y"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403


async def test_viewer_blocked_from_update_payload_type_403(
    client: AsyncClient, viewer_user, pt, make_token
):
    """VIEWER must receive 403 when trying to update a payload type."""
    token = make_token(viewer_user.id, viewer_user.role)
    resp  = await client.put(
        f"/api/master/payload-types/{pt['id']}",
        json={"notes": "Viewer attempt"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403


async def test_viewer_blocked_from_delete_payload_type_403(
    client: AsyncClient, viewer_user, pt, make_token
):
    """VIEWER must receive 403 when trying to delete a payload type."""
    token = make_token(viewer_user.id, viewer_user.role)
    resp  = await client.delete(
        f"/api/master/payload-types/{pt['id']}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403


# ══════════════════════════════════════════════════════════════════════
# DB Persistence — all fields round-trip through POST → GET
# ══════════════════════════════════════════════════════════════════════

async def test_payload_type_all_fields_persisted(
    client: AsyncClient, admin_user, make_token
):
    """All PayloadType fields must be retrievable unchanged after POST."""
    token = make_token(admin_user.id, admin_user.role)
    hdrs  = {"Authorization": f"Bearer {token}"}
    body  = {
        "name":             "Persist-SAR-Sensor",
        "manufacturer":     "ACS Sensors",
        "model":            "SAR-1000",
        "category":         "sensor",
        "weight_kg":        2.5,
        "voltage_v":        12.0,
        "max_current_a":    3.0,
        "has_gimbal":       True,
        "sensor_type":      "SAR",
        "resolution":       "0.5m",
        "frame_rate_fps":   1.0,
        "notes":            "Synthetic aperture radar — persistence check",
    }
    create = await client.post("/api/master/payload-types", json=body, headers=hdrs)
    assert create.status_code == 201
    ptid = create.json()["id"]
    try:
        get    = await client.get(f"/api/master/payload-types/{ptid}", headers=hdrs)
        assert get.status_code == 200
        stored = get.json()
        assert stored["name"]           == body["name"]
        assert stored["manufacturer"]   == body["manufacturer"]
        assert stored["model"]          == body["model"]
        assert stored["category"]       == body["category"]
        assert stored["weight_kg"]      == body["weight_kg"]
        assert stored["voltage_v"]      == body["voltage_v"]
        assert stored["max_current_a"]  == body["max_current_a"]
        assert stored["has_gimbal"]     == body["has_gimbal"]
        assert stored["sensor_type"]    == body["sensor_type"]
        assert stored["resolution"]     == body["resolution"]
        assert stored["frame_rate_fps"] == body["frame_rate_fps"]
        assert stored["notes"]          == body["notes"]
        assert stored["is_active"]      is True
        assert "id"         in stored
        assert "created_at" in stored
    finally:
        await client.delete(f"/api/master/payload-types/{ptid}", headers=hdrs)
