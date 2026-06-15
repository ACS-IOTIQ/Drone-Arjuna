"""
Config Templates API tests
===========================
GET / POST / PUT / DELETE /api/master/config-templates
GET /api/master/config-templates?drone_type_id=X
POST /api/master/config-templates/{tid}/apply/{drone_id}

Covers:
  - Happy-path create / list / get / update / archive
  - Duplicate template name → 409
  - Unknown drone type → 404
  - Blank template name → 422 (schema validator)
  - Filter by drone_type_id returns only matching templates
  - update sets updated_at; settings are replaced
  - Archive makes template invisible (GET → 404, list returns 0)
  - apply: drone type mismatch → 422
  - apply: happy path returns settings dict
  - RBAC: VIEWER blocked from all write operations
"""
import pytest
import pytest_asyncio
from httpx import AsyncClient


# ── shared fixtures ───────────────────────────────────────────────────────────

_DT_BODY = {
    "name": "CT-DroneType-Alpha",
    "manufacturer": "ACS Systems",
    "model": "Alpha-1",
    "size_class": "medium",
    "mission_type": "ISR",
    "is_vtol": True,
    "max_speed_ms": 30.0,
    "cruise_speed_ms": 20.0,
    "max_altitude_m": 3000.0,
    "endurance_h": 4.0,
    "range_km": 80.0,
    "max_takeoff_weight_kg": 15.0,
    "max_payload_weight_kg": 3.0,
    "autopilot_type": "ArduPilot",
}

_DT_BODY2 = {**_DT_BODY, "name": "CT-DroneType-Beta", "model": "Beta-1"}

_INSTANCE_BODY = {
    "call_sign": "CT-ALPHA-01",
    "serial_number": "CT-SN-001",
    "drone_type_id": None,  # filled per-fixture
}

_SETTINGS = {"RTL_ALT": 50, "FENCE_ENABLE": 1, "FS_THR_ENABLE": 1}


@pytest_asyncio.fixture
async def drone_type(client: AsyncClient, admin_user, make_token):
    """Create a drone type; tear it down after the test."""
    token = make_token(admin_user.id, admin_user.role)
    hdrs = {"Authorization": f"Bearer {token}"}
    resp = await client.post("/api/master/drone-types", json=_DT_BODY, headers=hdrs)
    assert resp.status_code == 201, resp.text
    data = resp.json()
    yield data
    await client.delete(f"/api/master/drone-types/{data['id']}", headers=hdrs)


@pytest_asyncio.fixture
async def drone_type2(client: AsyncClient, admin_user, make_token):
    """A second drone type for mismatch tests."""
    token = make_token(admin_user.id, admin_user.role)
    hdrs = {"Authorization": f"Bearer {token}"}
    resp = await client.post("/api/master/drone-types", json=_DT_BODY2, headers=hdrs)
    assert resp.status_code == 201, resp.text
    data = resp.json()
    yield data
    await client.delete(f"/api/master/drone-types/{data['id']}", headers=hdrs)


@pytest_asyncio.fixture
async def config_template(client: AsyncClient, admin_user, drone_type, make_token):
    """Create a config template against drone_type; tear it down after the test."""
    token = make_token(admin_user.id, admin_user.role)
    hdrs = {"Authorization": f"Bearer {token}"}
    resp = await client.post(
        "/api/master/config-templates",
        json={
            "name": "Base-Config",
            "drone_type_id": drone_type["id"],
            "description": "Default MAVLink params",
            "settings": _SETTINGS,
        },
        headers=hdrs,
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()
    yield data
    await client.delete(f"/api/master/config-templates/{data['id']}", headers=hdrs)


@pytest_asyncio.fixture
async def drone_instance(client: AsyncClient, admin_user, drone_type, make_token):
    """Register a drone instance of drone_type."""
    token = make_token(admin_user.id, admin_user.role)
    hdrs = {"Authorization": f"Bearer {token}"}
    body = {**_INSTANCE_BODY, "drone_type_id": drone_type["id"]}
    resp = await client.post("/api/master/drones", json=body, headers=hdrs)
    assert resp.status_code == 201, resp.text
    data = resp.json()
    yield data


# ══════════════════════════════════════════════════════════════════════
# Create
# ══════════════════════════════════════════════════════════════════════

async def test_create_config_template_201(
    client: AsyncClient, admin_user, drone_type, make_token
):
    token = make_token(admin_user.id, admin_user.role)
    hdrs = {"Authorization": f"Bearer {token}"}
    resp = await client.post(
        "/api/master/config-templates",
        json={
            "name": "New-Config",
            "drone_type_id": drone_type["id"],
            "settings": _SETTINGS,
        },
        headers=hdrs,
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["name"] == "New-Config"
    assert body["drone_type_id"] == drone_type["id"]
    assert body["settings"] == _SETTINGS
    assert body["is_active"] is True
    assert "id" in body
    assert "created_at" in body
    assert body["updated_at"] is None
    await client.delete(f"/api/master/config-templates/{body['id']}", headers=hdrs)


async def test_create_config_template_duplicate_name_409(
    client: AsyncClient, admin_user, config_template, drone_type, make_token
):
    token = make_token(admin_user.id, admin_user.role)
    resp = await client.post(
        "/api/master/config-templates",
        json={
            "name": config_template["name"],
            "drone_type_id": drone_type["id"],
            "settings": {},
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 409


async def test_create_config_template_blank_name_422(
    client: AsyncClient, admin_user, drone_type, make_token
):
    token = make_token(admin_user.id, admin_user.role)
    resp = await client.post(
        "/api/master/config-templates",
        json={
            "name": "   ",
            "drone_type_id": drone_type["id"],
            "settings": {},
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 422


async def test_create_config_template_unknown_type_404(
    client: AsyncClient, admin_user, make_token
):
    token = make_token(admin_user.id, admin_user.role)
    resp = await client.post(
        "/api/master/config-templates",
        json={
            "name": "Orphan-Config",
            "drone_type_id": 999999,
            "settings": {},
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 404


# ══════════════════════════════════════════════════════════════════════
# Read / list
# ══════════════════════════════════════════════════════════════════════

async def test_list_config_templates_200(
    client: AsyncClient, viewer_user, config_template, make_token
):
    token = make_token(viewer_user.id, viewer_user.role)
    resp = await client.get(
        "/api/master/config-templates",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    ids = [item["id"] for item in resp.json()]
    assert config_template["id"] in ids


async def test_filter_config_templates_by_drone_type_200(
    client: AsyncClient, viewer_user, config_template, drone_type, make_token
):
    token = make_token(viewer_user.id, viewer_user.role)
    resp = await client.get(
        f"/api/master/config-templates?drone_type_id={drone_type['id']}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    items = resp.json()
    assert len(items) >= 1
    assert all(i["drone_type_id"] == drone_type["id"] for i in items)


async def test_filter_config_templates_wrong_type_returns_empty(
    client: AsyncClient, viewer_user, config_template, drone_type2, make_token
):
    """Filtering by a type that has no templates returns an empty list."""
    token = make_token(viewer_user.id, viewer_user.role)
    resp = await client.get(
        f"/api/master/config-templates?drone_type_id={drone_type2['id']}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    assert resp.json() == []


async def test_get_config_template_200(
    client: AsyncClient, viewer_user, config_template, make_token
):
    token = make_token(viewer_user.id, viewer_user.role)
    resp = await client.get(
        f"/api/master/config-templates/{config_template['id']}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["name"] == config_template["name"]


async def test_get_config_template_not_found_404(
    client: AsyncClient, viewer_user, make_token
):
    token = make_token(viewer_user.id, viewer_user.role)
    resp = await client.get(
        "/api/master/config-templates/999999",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 404


# ══════════════════════════════════════════════════════════════════════
# Update
# ══════════════════════════════════════════════════════════════════════

async def test_update_config_template_settings_200(
    client: AsyncClient, admin_user, config_template, make_token
):
    token = make_token(admin_user.id, admin_user.role)
    new_settings = {"RTL_ALT": 100, "FENCE_ENABLE": 0}
    resp = await client.put(
        f"/api/master/config-templates/{config_template['id']}",
        json={"settings": new_settings},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["settings"] == new_settings
    assert body["updated_at"] is not None


async def test_update_config_template_not_found_404(
    client: AsyncClient, admin_user, make_token
):
    token = make_token(admin_user.id, admin_user.role)
    resp = await client.put(
        "/api/master/config-templates/999999",
        json={"settings": {}},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 404


async def test_update_config_template_invalid_type_404(
    client: AsyncClient, admin_user, config_template, make_token
):
    """Changing drone_type_id to a non-existent type must fail."""
    token = make_token(admin_user.id, admin_user.role)
    resp = await client.put(
        f"/api/master/config-templates/{config_template['id']}",
        json={"drone_type_id": 999999},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 404


# ══════════════════════════════════════════════════════════════════════
# Archive (soft-delete)
# ══════════════════════════════════════════════════════════════════════

async def test_archive_config_template_204(
    client: AsyncClient, admin_user, drone_type, make_token
):
    token = make_token(admin_user.id, admin_user.role)
    hdrs = {"Authorization": f"Bearer {token}"}
    create = await client.post(
        "/api/master/config-templates",
        json={"name": "Temp-Config", "drone_type_id": drone_type["id"], "settings": {}},
        headers=hdrs,
    )
    assert create.status_code == 201
    tid = create.json()["id"]

    resp = await client.delete(f"/api/master/config-templates/{tid}", headers=hdrs)
    assert resp.status_code == 204

    get = await client.get(f"/api/master/config-templates/{tid}", headers=hdrs)
    assert get.status_code == 404


async def test_archived_template_excluded_from_list(
    client: AsyncClient, admin_user, drone_type, make_token
):
    token = make_token(admin_user.id, admin_user.role)
    hdrs = {"Authorization": f"Bearer {token}"}
    create = await client.post(
        "/api/master/config-templates",
        json={"name": "Will-Archive", "drone_type_id": drone_type["id"], "settings": {}},
        headers=hdrs,
    )
    assert create.status_code == 201
    tid = create.json()["id"]

    await client.delete(f"/api/master/config-templates/{tid}", headers=hdrs)

    lst = await client.get(
        f"/api/master/config-templates?drone_type_id={drone_type['id']}", headers=hdrs
    )
    assert lst.status_code == 200
    assert tid not in [i["id"] for i in lst.json()]


# ══════════════════════════════════════════════════════════════════════
# Apply endpoint
# ══════════════════════════════════════════════════════════════════════

async def test_apply_config_template_to_drone_200(
    client: AsyncClient, admin_user, config_template, drone_instance, make_token
):
    """Happy path: template type matches drone type → returns settings dict."""
    token = make_token(admin_user.id, admin_user.role)
    resp = await client.post(
        f"/api/master/config-templates/{config_template['id']}/apply/{drone_instance['id']}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["template_id"] == config_template["id"]
    assert body["drone_id"] == drone_instance["id"]
    assert body["settings"] == _SETTINGS


async def test_apply_config_template_type_mismatch_422(
    client: AsyncClient, admin_user, drone_type, drone_type2, drone_instance, make_token
):
    """Template is for drone_type but drone_instance is also drone_type — both same.
    Create a template for drone_type2 and try to apply to drone_instance (drone_type)."""
    token = make_token(admin_user.id, admin_user.role)
    hdrs = {"Authorization": f"Bearer {token}"}

    # Create template for drone_type2
    ct = await client.post(
        "/api/master/config-templates",
        json={"name": "Beta-Config", "drone_type_id": drone_type2["id"], "settings": {}},
        headers=hdrs,
    )
    assert ct.status_code == 201
    wrong_tid = ct.json()["id"]

    # Apply template meant for drone_type2 to a drone of drone_type → 422
    resp = await client.post(
        f"/api/master/config-templates/{wrong_tid}/apply/{drone_instance['id']}",
        headers=hdrs,
    )
    assert resp.status_code == 422

    await client.delete(f"/api/master/config-templates/{wrong_tid}", headers=hdrs)


async def test_apply_config_template_unknown_template_404(
    client: AsyncClient, admin_user, drone_instance, make_token
):
    token = make_token(admin_user.id, admin_user.role)
    resp = await client.post(
        f"/api/master/config-templates/999999/apply/{drone_instance['id']}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 404


async def test_apply_config_template_unknown_drone_404(
    client: AsyncClient, admin_user, config_template, make_token
):
    token = make_token(admin_user.id, admin_user.role)
    resp = await client.post(
        f"/api/master/config-templates/{config_template['id']}/apply/999999",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 404


# ══════════════════════════════════════════════════════════════════════
# RBAC
# ══════════════════════════════════════════════════════════════════════

async def test_config_templates_unauthenticated_401(client: AsyncClient):
    resp = await client.get("/api/master/config-templates")
    assert resp.status_code == 401


async def test_viewer_blocked_from_create_config_template_403(
    client: AsyncClient, viewer_user, drone_type, make_token
):
    token = make_token(viewer_user.id, viewer_user.role)
    resp = await client.post(
        "/api/master/config-templates",
        json={"name": "RBAC-Test", "drone_type_id": drone_type["id"], "settings": {}},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403


async def test_viewer_blocked_from_update_config_template_403(
    client: AsyncClient, viewer_user, config_template, make_token
):
    token = make_token(viewer_user.id, viewer_user.role)
    resp = await client.put(
        f"/api/master/config-templates/{config_template['id']}",
        json={"settings": {}},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403


async def test_viewer_blocked_from_archive_config_template_403(
    client: AsyncClient, viewer_user, config_template, make_token
):
    token = make_token(viewer_user.id, viewer_user.role)
    resp = await client.delete(
        f"/api/master/config-templates/{config_template['id']}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403
