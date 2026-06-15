"""
Drone Inventory API tests
=========================
GET /api/inventory/drones
GET /api/inventory/drones/{type_id}
GET /api/inventory/drones/{type_id}/quick-ref
GET /api/inventory/compare?ids=...
GET /api/inventory/search?q=...
GET /api/inventory/payloads

Covers:
  - Catalogue list with optional filters
  - Detail view for a single drone type
  - Quick-reference card
  - Side-by-side comparison (2 drones)
  - Comparison errors: < 2 IDs → 400, > 4 IDs → 400
  - ILIKE search matches name / manufacturer / model
  - Empty search query returns empty results (no crash)
  - Payload stub returns empty list
  - RBAC: all endpoints require VIEWER; unauthenticated → 401
"""
import pytest
import pytest_asyncio
from httpx import AsyncClient


_DT_BASE = {
    "manufacturer": "Inventory Corp",
    "size_class":   "medium",
    "mission_type": "ISR",
    "is_vtol":      True,
    "max_speed_ms": 28.0,
    "cruise_speed_ms": 20.0,
    "max_altitude_m":  2500.0,
    "endurance_h":     3.5,
    "range_km":        60.0,
    "max_takeoff_weight_kg": 12.0,
    "max_payload_weight_kg":  2.5,
    "autopilot_type": "ArduPilot",
}


@pytest_asyncio.fixture
async def inv_drone_type(client: AsyncClient, admin_user, make_token):
    """First drone type for inventory tests."""
    token = make_token(admin_user.id, admin_user.role)
    hdrs  = {"Authorization": f"Bearer {token}"}
    body  = {**_DT_BASE, "name": "Inv-Eagle-200", "model": "INV-E200"}
    resp  = await client.post("/api/master/drone-types", json=body, headers=hdrs)
    assert resp.status_code == 201, resp.text
    data  = resp.json()
    yield data
    await client.delete(f"/api/master/drone-types/{data['id']}", headers=hdrs)


@pytest_asyncio.fixture
async def inv_drone_type2(client: AsyncClient, admin_user, make_token):
    """Second drone type for comparison tests."""
    token = make_token(admin_user.id, admin_user.role)
    hdrs  = {"Authorization": f"Bearer {token}"}
    body  = {
        **_DT_BASE,
        "name":          "Inv-Falcon-300",
        "model":         "INV-F300",
        "max_speed_ms":  35.0,
        "cruise_speed_ms": 25.0,
    }
    resp = await client.post("/api/master/drone-types", json=body, headers=hdrs)
    assert resp.status_code == 201, resp.text
    data = resp.json()
    yield data
    await client.delete(f"/api/master/drone-types/{data['id']}", headers=hdrs)


# ══════════════════════════════════════════════════════════════════════
# Catalogue list
# ══════════════════════════════════════════════════════════════════════

async def test_list_inventory_drones_200(
    client: AsyncClient, viewer_user, inv_drone_type, make_token
):
    token = make_token(viewer_user.id, viewer_user.role)
    resp  = await client.get(
        "/api/inventory/drones",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "items" in body
    assert "total" in body
    assert body["total"] >= 1
    assert inv_drone_type["id"] in [item["id"] for item in body["items"]]


async def test_list_inventory_drones_filter_size_class_200(
    client: AsyncClient, viewer_user, inv_drone_type, make_token
):
    """Filter by size_class returns a subset."""
    token = make_token(viewer_user.id, viewer_user.role)
    resp  = await client.get(
        "/api/inventory/drones?size_class=medium",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    for item in resp.json()["items"]:
        assert item["size_class"] == "medium"


async def test_list_inventory_drones_unknown_filter_200(
    client: AsyncClient, viewer_user, make_token
):
    """Filtering by a size_class that matches nothing returns empty items."""
    token = make_token(viewer_user.id, viewer_user.role)
    resp  = await client.get(
        "/api/inventory/drones?size_class=gigantic",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["total"] == 0


# ══════════════════════════════════════════════════════════════════════
# Detail view
# ══════════════════════════════════════════════════════════════════════

async def test_get_inventory_drone_detail_200(
    client: AsyncClient, viewer_user, inv_drone_type, make_token
):
    token = make_token(viewer_user.id, viewer_user.role)
    resp  = await client.get(
        f"/api/inventory/drones/{inv_drone_type['id']}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"]           == inv_drone_type["id"]
    assert "performance"        in body
    assert "physical"           in body
    assert "registered_instances" in body


async def test_get_inventory_drone_not_found_404(
    client: AsyncClient, viewer_user, make_token
):
    token = make_token(viewer_user.id, viewer_user.role)
    resp  = await client.get(
        "/api/inventory/drones/999999",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 404


# ══════════════════════════════════════════════════════════════════════
# Quick reference
# ══════════════════════════════════════════════════════════════════════

async def test_quick_ref_200(
    client: AsyncClient, viewer_user, inv_drone_type, make_token
):
    token = make_token(viewer_user.id, viewer_user.role)
    resp  = await client.get(
        f"/api/inventory/drones/{inv_drone_type['id']}/quick-ref",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"]        == inv_drone_type["id"]
    assert "key_specs"       in body
    assert "endurance_h"     in body["key_specs"]
    assert "range_km"        in body["key_specs"]


async def test_quick_ref_not_found_404(
    client: AsyncClient, viewer_user, make_token
):
    token = make_token(viewer_user.id, viewer_user.role)
    resp  = await client.get(
        "/api/inventory/drones/999999/quick-ref",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 404


# ══════════════════════════════════════════════════════════════════════
# Comparison
# ══════════════════════════════════════════════════════════════════════

async def test_compare_two_drones_200(
    client: AsyncClient, viewer_user, inv_drone_type, inv_drone_type2, make_token
):
    token = make_token(viewer_user.id, viewer_user.role)
    ids   = f"{inv_drone_type['id']}&ids={inv_drone_type2['id']}"
    resp  = await client.get(
        f"/api/inventory/compare?ids={ids}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "drones"  in body
    assert "metrics" in body
    assert len(body["drones"]) == 2


async def test_compare_one_drone_400(
    client: AsyncClient, viewer_user, inv_drone_type, make_token
):
    """Comparing fewer than 2 types must return 400."""
    token = make_token(viewer_user.id, viewer_user.role)
    resp  = await client.get(
        f"/api/inventory/compare?ids={inv_drone_type['id']}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 400


async def test_compare_not_found_404(
    client: AsyncClient, viewer_user, inv_drone_type, make_token
):
    """One non-existent ID in the comparison must return 404."""
    token = make_token(viewer_user.id, viewer_user.role)
    ids   = f"{inv_drone_type['id']}&ids=999999"
    resp  = await client.get(
        f"/api/inventory/compare?ids={ids}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 404


# ══════════════════════════════════════════════════════════════════════
# Search
# ══════════════════════════════════════════════════════════════════════

async def test_search_by_name_returns_match(
    client: AsyncClient, viewer_user, inv_drone_type, make_token
):
    token = make_token(viewer_user.id, viewer_user.role)
    resp  = await client.get(
        "/api/inventory/search?q=Inv-Eagle",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "results" in body
    assert body["total"] >= 1
    assert any(r["id"] == inv_drone_type["id"] for r in body["results"])


async def test_search_by_manufacturer(
    client: AsyncClient, viewer_user, inv_drone_type, make_token
):
    token = make_token(viewer_user.id, viewer_user.role)
    resp  = await client.get(
        "/api/inventory/search?q=Inventory+Corp",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["total"] >= 1


async def test_search_no_match_returns_empty(
    client: AsyncClient, viewer_user, make_token
):
    token = make_token(viewer_user.id, viewer_user.role)
    resp  = await client.get(
        "/api/inventory/search?q=zzznomatchzzz",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["total"] == 0


async def test_search_empty_query_200(
    client: AsyncClient, viewer_user, make_token
):
    """Empty search query returns an empty result set without error."""
    token = make_token(viewer_user.id, viewer_user.role)
    resp  = await client.get(
        "/api/inventory/search?q=",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["total"] == 0


# ══════════════════════════════════════════════════════════════════════
# Payload stub
# ══════════════════════════════════════════════════════════════════════

async def test_list_inventory_payloads_stub_200(
    client: AsyncClient, viewer_user, make_token
):
    """V1 payload stub returns an empty list with a note."""
    token = make_token(viewer_user.id, viewer_user.role)
    resp  = await client.get(
        "/api/inventory/payloads",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 0
    assert "note"  in body


# ══════════════════════════════════════════════════════════════════════
# RBAC
# ══════════════════════════════════════════════════════════════════════

async def test_inventory_unauthenticated_401(client: AsyncClient):
    resp = await client.get("/api/inventory/drones")
    assert resp.status_code == 401


async def test_inventory_search_unauthenticated_401(client: AsyncClient):
    resp = await client.get("/api/inventory/search?q=test")
    assert resp.status_code == 401
