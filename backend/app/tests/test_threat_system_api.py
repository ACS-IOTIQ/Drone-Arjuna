"""
Threat System API tests
=======================
GET / POST / PUT / PATCH / DELETE /api/inventory/threat-systems

Covers:
  - Happy-path create / list / get / update / delete
  - PATCH /{id}/notes endpoint
  - Duplicate name → 409
  - Get / update / delete non-existent → 404
  - Category and country query filters
  - All fields round-trip through POST → GET
  - RBAC: intelligence_analyst and mission_commander can read
  - RBAC: only admin can create / update / delete
  - RBAC: intelligence_analyst and admin can PATCH notes
  - RBAC: viewer blocked from all operations (403)
  - Unauthenticated requests → 401
  - Invalid category value → 422
"""
import pytest
import pytest_asyncio
from httpx import AsyncClient


_BASE = "/api/inventory/threat-systems"

_TS_BODY = {
    "name": "Test SAM-2000",
    "category": "SAM",
    "manufacturer": "Test Defence Ltd",
    "country": "India",
    "max_range_km": 40.0,
    "max_altitude_m": 15000.0,
    "max_speed_kmh": 2800.0,
    "radar_cross_section_m2": 0.01,
    "countermeasures": ["chaff", "flare"],
    "notes": "Surface-to-air missile system for testing",
    "classification": "RESTRICTED",
}

_TS_BODY2 = {**_TS_BODY, "name": "Test RADAR-500", "category": "RADAR"}


@pytest_asyncio.fixture
async def threat(client: AsyncClient, admin_user, make_token):
    token = make_token(admin_user.id, admin_user.role)
    hdrs  = {"Authorization": f"Bearer {token}"}
    resp  = await client.post(_BASE, json=_TS_BODY, headers=hdrs)
    assert resp.status_code == 201, resp.text
    data  = resp.json()
    yield data
    await client.delete(f"{_BASE}/{data['id']}", headers=hdrs)


# ══════════════════════════════════════════════════════════════════════
# Create
# ══════════════════════════════════════════════════════════════════════

async def test_create_threat_201(client: AsyncClient, admin_user, make_token):
    token = make_token(admin_user.id, admin_user.role)
    hdrs  = {"Authorization": f"Bearer {token}"}
    resp  = await client.post(_BASE, json=_TS_BODY2, headers=hdrs)
    assert resp.status_code == 201
    body = resp.json()
    assert body["name"]           == _TS_BODY2["name"]
    assert body["category"]       == "RADAR"
    assert body["country"]        == "India"
    assert body["classification"] == "RESTRICTED"
    assert "id" in body
    await client.delete(f"{_BASE}/{body['id']}", headers=hdrs)


async def test_create_threat_duplicate_name_409(
    client: AsyncClient, admin_user, threat, make_token
):
    token = make_token(admin_user.id, admin_user.role)
    resp  = await client.post(
        _BASE,
        json=_TS_BODY,
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 409


async def test_create_threat_default_classification(
    client: AsyncClient, admin_user, make_token
):
    """classification should default to UNCLASSIFIED when omitted."""
    token = make_token(admin_user.id, admin_user.role)
    hdrs  = {"Authorization": f"Bearer {token}"}
    body  = {k: v for k, v in _TS_BODY.items() if k != "classification"}
    body["name"] = "Default Class UAV"
    resp  = await client.post(_BASE, json=body, headers=hdrs)
    assert resp.status_code == 201
    data  = resp.json()
    assert data["classification"] == "UNCLASSIFIED"
    await client.delete(f"{_BASE}/{data['id']}", headers=hdrs)


async def test_create_threat_invalid_category_422(
    client: AsyncClient, admin_user, make_token
):
    """Invalid category value must be rejected with 422."""
    token = make_token(admin_user.id, admin_user.role)
    resp  = await client.post(
        _BASE,
        json={**_TS_BODY, "name": "Bad Cat", "category": "TANK"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 422


# ══════════════════════════════════════════════════════════════════════
# Read
# ══════════════════════════════════════════════════════════════════════

async def test_list_threat_systems_200(
    client: AsyncClient, intelligence_analyst_user, threat, make_token
):
    token = make_token(intelligence_analyst_user.id, intelligence_analyst_user.role)
    resp  = await client.get(
        _BASE,
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "items" in body
    assert "total" in body
    assert threat["id"] in [item["id"] for item in body["items"]]


async def test_mission_commander_can_list_threat_systems(
    client: AsyncClient, mission_commander_user, threat, make_token
):
    token = make_token(mission_commander_user.id, mission_commander_user.role)
    resp  = await client.get(
        _BASE,
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200


async def test_list_threats_filter_category(
    client: AsyncClient, admin_user, make_token
):
    """Only SAM threats returned when category=SAM filter applied."""
    token = make_token(admin_user.id, admin_user.role)
    hdrs  = {"Authorization": f"Bearer {token}"}

    sam   = await client.post(_BASE, json=_TS_BODY, headers=hdrs)
    radar = await client.post(_BASE, json=_TS_BODY2, headers=hdrs)
    assert sam.status_code == 201 and radar.status_code == 201

    resp = await client.get(f"{_BASE}?category=SAM", headers=hdrs)
    assert resp.status_code == 200
    categories = [item["category"] for item in resp.json()["items"]]
    assert all(c == "SAM" for c in categories)

    await client.delete(f"{_BASE}/{sam.json()['id']}", headers=hdrs)
    await client.delete(f"{_BASE}/{radar.json()['id']}", headers=hdrs)


async def test_list_threats_filter_country(
    client: AsyncClient, admin_user, make_token
):
    """Only threats matching the country filter are returned."""
    token = make_token(admin_user.id, admin_user.role)
    hdrs  = {"Authorization": f"Bearer {token}"}

    t1 = await client.post(_BASE, json=_TS_BODY, headers=hdrs)
    t2 = await client.post(
        _BASE,
        json={**_TS_BODY2, "country": "Russia"},
        headers=hdrs,
    )
    assert t1.status_code == 201 and t2.status_code == 201

    resp = await client.get(f"{_BASE}?country=India", headers=hdrs)
    assert resp.status_code == 200
    countries = [item["country"] for item in resp.json()["items"]]
    assert all(c == "India" for c in countries)

    await client.delete(f"{_BASE}/{t1.json()['id']}", headers=hdrs)
    await client.delete(f"{_BASE}/{t2.json()['id']}", headers=hdrs)


async def test_get_threat_system_200(
    client: AsyncClient, intelligence_analyst_user, threat, make_token
):
    token = make_token(intelligence_analyst_user.id, intelligence_analyst_user.role)
    resp  = await client.get(
        f"{_BASE}/{threat['id']}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["name"] == _TS_BODY["name"]


async def test_get_threat_system_not_found_404(
    client: AsyncClient, intelligence_analyst_user, make_token
):
    token = make_token(intelligence_analyst_user.id, intelligence_analyst_user.role)
    resp  = await client.get(
        f"{_BASE}/999999",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 404


# ══════════════════════════════════════════════════════════════════════
# Update (PUT)
# ══════════════════════════════════════════════════════════════════════

async def test_update_threat_notes_200(
    client: AsyncClient, admin_user, threat, make_token
):
    token = make_token(admin_user.id, admin_user.role)
    resp  = await client.put(
        f"{_BASE}/{threat['id']}",
        json={"notes": "Updated in test"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["notes"] == "Updated in test"


async def test_update_threat_classification_200(
    client: AsyncClient, admin_user, threat, make_token
):
    token = make_token(admin_user.id, admin_user.role)
    resp  = await client.put(
        f"{_BASE}/{threat['id']}",
        json={"classification": "TOP SECRET"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["classification"] == "TOP SECRET"


async def test_update_threat_not_found_404(
    client: AsyncClient, admin_user, make_token
):
    token = make_token(admin_user.id, admin_user.role)
    resp  = await client.put(
        f"{_BASE}/999999",
        json={"notes": "Should 404"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 404


# ══════════════════════════════════════════════════════════════════════
# PATCH notes
# ══════════════════════════════════════════════════════════════════════

async def test_patch_notes_admin_200(
    client: AsyncClient, admin_user, threat, make_token
):
    token = make_token(admin_user.id, admin_user.role)
    resp  = await client.patch(
        f"{_BASE}/{threat['id']}/notes",
        json={"notes": "Admin patched this note"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["notes"] == "Admin patched this note"


async def test_patch_notes_analyst_200(
    client: AsyncClient, intelligence_analyst_user, threat, make_token
):
    token = make_token(intelligence_analyst_user.id, intelligence_analyst_user.role)
    resp  = await client.patch(
        f"{_BASE}/{threat['id']}/notes",
        json={"notes": "Analyst updated this note"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["notes"] == "Analyst updated this note"


async def test_patch_notes_not_found_404(
    client: AsyncClient, admin_user, make_token
):
    token = make_token(admin_user.id, admin_user.role)
    resp  = await client.patch(
        f"{_BASE}/999999/notes",
        json={"notes": "No such threat"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 404


async def test_patch_notes_viewer_403(
    client: AsyncClient, viewer_user, threat, make_token
):
    token = make_token(viewer_user.id, viewer_user.role)
    resp  = await client.patch(
        f"{_BASE}/{threat['id']}/notes",
        json={"notes": "Should be blocked"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403


# ══════════════════════════════════════════════════════════════════════
# Delete
# ══════════════════════════════════════════════════════════════════════

async def test_delete_threat_system_204(client: AsyncClient, admin_user, make_token):
    token = make_token(admin_user.id, admin_user.role)
    hdrs  = {"Authorization": f"Bearer {token}"}

    create = await client.post(
        _BASE,
        json={**_TS_BODY, "name": "Temporary EW System", "category": "EW"},
        headers=hdrs,
    )
    assert create.status_code == 201
    tid = create.json()["id"]

    delete = await client.delete(f"{_BASE}/{tid}", headers=hdrs)
    assert delete.status_code == 204

    get = await client.get(f"{_BASE}/{tid}", headers=hdrs)
    assert get.status_code == 404


async def test_delete_threat_system_not_found_404(
    client: AsyncClient, admin_user, make_token
):
    token = make_token(admin_user.id, admin_user.role)
    resp  = await client.delete(
        f"{_BASE}/999999",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 404


# ══════════════════════════════════════════════════════════════════════
# All fields round-trip
# ══════════════════════════════════════════════════════════════════════

async def test_threat_all_fields_persisted(
    client: AsyncClient, admin_user, make_token
):
    """Every field submitted on POST must be retrievable unchanged via GET."""
    token = make_token(admin_user.id, admin_user.role)
    hdrs  = {"Authorization": f"Bearer {token}"}
    body  = {
        "name":                   "Persist-Test UAV",
        "category":               "UAV",
        "manufacturer":           "ACS Defence",
        "country":                "India",
        "max_range_km":           200.0,
        "max_altitude_m":         8000.0,
        "max_speed_kmh":          350.0,
        "radar_cross_section_m2": 0.005,
        "countermeasures":        ["jamming", "chaff", "flare"],
        "notes":                  "Persistence check entry",
        "classification":         "CONFIDENTIAL",
    }
    create = await client.post(_BASE, json=body, headers=hdrs)
    assert create.status_code == 201
    tid = create.json()["id"]
    try:
        get = await client.get(f"{_BASE}/{tid}", headers=hdrs)
        assert get.status_code == 200
        stored = get.json()
        for field in ("name", "category", "manufacturer", "country",
                      "max_range_km", "max_altitude_m", "max_speed_kmh",
                      "radar_cross_section_m2", "countermeasures",
                      "notes", "classification"):
            assert stored[field] == body[field], f"Field '{field}' mismatch"
    finally:
        await client.delete(f"{_BASE}/{tid}", headers=hdrs)


# ══════════════════════════════════════════════════════════════════════
# RBAC
# ══════════════════════════════════════════════════════════════════════

async def test_threat_systems_unauthenticated_401(client: AsyncClient):
    resp = await client.get(_BASE)
    assert resp.status_code == 401


async def test_viewer_blocked_from_list_threat_systems_403(
    client: AsyncClient, viewer_user, make_token
):
    """Viewer role is not in the allowed read roles (intelligence_analyst / mission_commander / admin)."""
    token = make_token(viewer_user.id, viewer_user.role)
    resp  = await client.get(
        _BASE,
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403


async def test_viewer_blocked_from_create_threat_403(
    client: AsyncClient, viewer_user, make_token
):
    token = make_token(viewer_user.id, viewer_user.role)
    resp  = await client.post(
        _BASE,
        json=_TS_BODY,
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403


async def test_viewer_blocked_from_update_threat_403(
    client: AsyncClient, viewer_user, threat, make_token
):
    token = make_token(viewer_user.id, viewer_user.role)
    resp  = await client.put(
        f"{_BASE}/{threat['id']}",
        json={"notes": "Should fail"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403


async def test_viewer_blocked_from_delete_threat_403(
    client: AsyncClient, viewer_user, threat, make_token
):
    token = make_token(viewer_user.id, viewer_user.role)
    resp  = await client.delete(
        f"{_BASE}/{threat['id']}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403
