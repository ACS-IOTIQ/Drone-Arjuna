"""
Payload API tests
=================
Tests the full CRUD surface for:
  GET / POST / PUT / DELETE /api/master/payload-types
  GET / POST / PUT / DELETE /api/master/payloads

Covers:
  - Happy-path create / list / get / update / delete
  - Duplicate name / serial → 409
  - Invalid foreign key → 404
  - RBAC: VIEWER blocked from all write operations
  - Delete PayloadType blocked while a Payload still references it
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

_PL_BODY = {
    "name": "EO-CAM-T01",
    "weight": 0.85,
    "status": "available",
    "manufacturer": "Test Systems Ltd",
    "serial_number": "TEST-SN-0001",
}


# ── Fixtures: rows created via the API itself ─────────────────────────────────

@pytest_asyncio.fixture
async def pt(client: AsyncClient, admin_user, make_token):
    """
    Creates a PayloadType row via POST before the test and deletes it
    afterwards.  Teardown is skipped gracefully if the test already deleted it.
    """
    token = make_token(admin_user.id, admin_user.role)
    hdrs = {"Authorization": f"Bearer {token}"}

    resp = await client.post("/api/master/payload-types", json=_PT_BODY, headers=hdrs)
    assert resp.status_code == 201, resp.text
    data = resp.json()
    yield data

    await client.delete(f"/api/master/payload-types/{data['id']}", headers=hdrs)


@pytest_asyncio.fixture
async def pl(client: AsyncClient, admin_user, pt, make_token):
    """
    Creates a Payload row via POST before the test and deletes it afterwards.
    Depends on `pt` so teardown order is: payload deleted first, then type.
    """
    token = make_token(admin_user.id, admin_user.role)
    hdrs = {"Authorization": f"Bearer {token}"}

    body = {**_PL_BODY, "payload_type_id": pt["id"]}
    resp = await client.post("/api/master/payloads", json=body, headers=hdrs)
    assert resp.status_code == 201, resp.text
    data = resp.json()
    yield data

    await client.delete(f"/api/master/payloads/{data['id']}", headers=hdrs)


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
    """Admin can delete a payload type that has no referencing payloads."""
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

    # Confirm it is gone
    get = await client.get(f"/api/master/payload-types/{tid}", headers=hdrs)
    assert get.status_code == 404


async def test_delete_payload_type_blocked_409(
    client: AsyncClient, admin_user, pl, make_token
):
    """
    Deleting a PayloadType while a Payload still references it must fail
    with 409 (the service enforces referential integrity).
    """
    token = make_token(admin_user.id, admin_user.role)
    resp  = await client.delete(
        f"/api/master/payload-types/{pl['payload_type_id']}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 409


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


# ═══════════════════════════════════════════════════════════════════════
# Payload — CRUD
# ═══════════════════════════════════════════════════════════════════════

async def test_create_payload_201(
    client: AsyncClient, admin_user, pt, make_token
):
    """Admin can register a new payload; response contains all required fields."""
    token = make_token(admin_user.id, admin_user.role)
    hdrs  = {"Authorization": f"Bearer {token}"}

    body = {**_PL_BODY, "payload_type_id": pt["id"], "serial_number": "TEST-SN-0002"}
    resp = await client.post("/api/master/payloads", json=body, headers=hdrs)
    assert resp.status_code == 201
    data = resp.json()
    assert data["name"]            == _PL_BODY["name"]
    assert data["payload_type_id"] == pt["id"]
    assert data["weight"]          == _PL_BODY["weight"]
    assert data["status"]          == "available"
    assert data["serial_number"]   == "TEST-SN-0002"
    assert "id"         in data
    assert "created_at" in data

    await client.delete(f"/api/master/payloads/{data['id']}", headers=hdrs)


async def test_create_payload_duplicate_serial_409(
    client: AsyncClient, admin_user, pl, make_token
):
    """Registering a payload with an already-used serial number must return 409."""
    token = make_token(admin_user.id, admin_user.role)
    body  = {**_PL_BODY, "payload_type_id": pl["payload_type_id"],
             "serial_number": pl["serial_number"]}
    resp  = await client.post(
        "/api/master/payloads",
        json=body,
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 409


async def test_create_payload_invalid_type_404(
    client: AsyncClient, admin_user, make_token
):
    """Referencing a non-existent PayloadType ID must return 404."""
    token = make_token(admin_user.id, admin_user.role)
    body  = {**_PL_BODY, "payload_type_id": 999999, "serial_number": "UNIQUE-SN-9999"}
    resp  = await client.post(
        "/api/master/payloads",
        json=body,
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 404


async def test_list_payloads_200(
    client: AsyncClient, viewer_user, pl, make_token
):
    """VIEWER can list all payloads; the fixture payload appears in results."""
    token = make_token(viewer_user.id, viewer_user.role)
    resp  = await client.get(
        "/api/master/payloads",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)
    assert pl["id"] in [item["id"] for item in resp.json()]


async def test_get_payload_200(
    client: AsyncClient, viewer_user, pl, make_token
):
    """VIEWER can fetch a single payload by ID."""
    token = make_token(viewer_user.id, viewer_user.role)
    resp  = await client.get(
        f"/api/master/payloads/{pl['id']}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["serial_number"] == pl["serial_number"]


async def test_get_payload_not_found_404(
    client: AsyncClient, viewer_user, make_token
):
    """Non-existent payload ID must return 404."""
    token = make_token(viewer_user.id, viewer_user.role)
    resp  = await client.get(
        "/api/master/payloads/999999",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 404


async def test_update_payload_status_200(
    client: AsyncClient, admin_user, pl, make_token
):
    """Admin can update a payload's status field."""
    token = make_token(admin_user.id, admin_user.role)
    resp  = await client.put(
        f"/api/master/payloads/{pl['id']}",
        json={"status": "mounted"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "mounted"


async def test_update_payload_name_200(
    client: AsyncClient, admin_user, pl, make_token
):
    """Admin can rename a payload."""
    token = make_token(admin_user.id, admin_user.role)
    resp  = await client.put(
        f"/api/master/payloads/{pl['id']}",
        json={"name": "Renamed Payload"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["name"] == "Renamed Payload"


async def test_delete_payload_204(
    client: AsyncClient, admin_user, pt, make_token
):
    """Admin can delete a payload; it must be gone afterwards."""
    token = make_token(admin_user.id, admin_user.role)
    hdrs  = {"Authorization": f"Bearer {token}"}

    body   = {**_PL_BODY, "payload_type_id": pt["id"], "serial_number": "DELETE-ME-001"}
    create = await client.post("/api/master/payloads", json=body, headers=hdrs)
    assert create.status_code == 201
    pid = create.json()["id"]

    delete = await client.delete(f"/api/master/payloads/{pid}", headers=hdrs)
    assert delete.status_code == 204

    get = await client.get(f"/api/master/payloads/{pid}", headers=hdrs)
    assert get.status_code == 404


async def test_viewer_blocked_from_create_payload_403(
    client: AsyncClient, viewer_user, pt, make_token
):
    """VIEWER must receive 403 when trying to register a payload."""
    token = make_token(viewer_user.id, viewer_user.role)
    body  = {**_PL_BODY, "payload_type_id": pt["id"], "serial_number": "VIEWER-BLOCKED"}
    resp  = await client.post(
        "/api/master/payloads",
        json=body,
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403


async def test_viewer_blocked_from_delete_payload_403(
    client: AsyncClient, viewer_user, pl, make_token
):
    """VIEWER must receive 403 when trying to delete a payload."""
    token = make_token(viewer_user.id, viewer_user.role)
    resp  = await client.delete(
        f"/api/master/payloads/{pl['id']}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403


# ══════════════════════════════════════════════════════════════════════
# DB Persistence — verify all fields round-trip through POST → GET
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


async def test_payload_all_fields_persisted(
    client: AsyncClient, admin_user, pt, make_token
):
    """All Payload fields must be retrievable unchanged after POST."""
    token = make_token(admin_user.id, admin_user.role)
    hdrs  = {"Authorization": f"Bearer {token}"}
    body  = {
        "name":            "Persist-EO-CAM-01",
        "payload_type_id": pt["id"],
        "weight":          1.25,
        "status":          "available",
        "manufacturer":    "ACS Optics",
        "serial_number":   "PT-EO-SN-2026",
    }
    create = await client.post("/api/master/payloads", json=body, headers=hdrs)
    assert create.status_code == 201
    pid = create.json()["id"]
    try:
        get    = await client.get(f"/api/master/payloads/{pid}", headers=hdrs)
        assert get.status_code == 200
        stored = get.json()
        assert stored["name"]            == body["name"]
        assert stored["payload_type_id"] == body["payload_type_id"]
        assert stored["weight"]          == body["weight"]
        assert stored["status"]          == body["status"]
        assert stored["manufacturer"]    == body["manufacturer"]
        assert stored["serial_number"]   == body["serial_number"]
        assert "id"         in stored
        assert "created_at" in stored
    finally:
        await client.delete(f"/api/master/payloads/{pid}", headers=hdrs)
