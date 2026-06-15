from httpx import AsyncClient

from app.tests.helpers import auth_headers, drone_instance_payload, drone_type_payload


async def _seed_inventory(client: AsyncClient, headers: dict) -> tuple[dict, dict]:
    quad_resp = await client.post(
        "/api/master/drone-types",
        json=drone_type_payload(
            size_class="small",
            mission_type="ISR",
            autopilot_type="PX4",
            max_speed_ms=28.0,
            cruise_speed_ms=16.0,
            endurance_h=1.5,
            notes="Inventory search target",
        ),
        headers=headers,
    )
    assert quad_resp.status_code == 201, quad_resp.text

    fixed_resp = await client.post(
        "/api/master/drone-types",
        json=drone_type_payload(
            size_class="medium",
            mission_type="logistics",
            autopilot_type="ArduPilot",
            is_vtol=False,
            max_speed_ms=45.0,
            cruise_speed_ms=32.0,
            endurance_h=4.0,
            range_km=180.0,
        ),
        headers=headers,
    )
    assert fixed_resp.status_code == 201, fixed_resp.text

    drone_resp = await client.post(
        "/api/master/drones",
        json=drone_instance_payload(quad_resp.json()["id"]),
        headers=headers,
    )
    assert drone_resp.status_code == 201, drone_resp.text
    return quad_resp.json(), fixed_resp.json()


async def test_inventory_requires_auth(client: AsyncClient):
    resp = await client.get("/api/inventory/drones")
    assert resp.status_code == 401


async def test_inventory_list_detail_quick_ref_compare_and_search(
    client: AsyncClient, admin_user, viewer_user, make_token
):
    admin_headers = auth_headers(admin_user, make_token)
    viewer_headers = auth_headers(viewer_user, make_token)
    quad, fixed = await _seed_inventory(client, admin_headers)

    list_resp = await client.get("/api/inventory/drones", headers=viewer_headers)
    assert list_resp.status_code == 200
    assert list_resp.json()["total"] >= 2

    filtered = await client.get(
        "/api/inventory/drones",
        params={"size_class": "small", "mission_type": "ISR", "autopilot": "PX4"},
        headers=viewer_headers,
    )
    assert filtered.status_code == 200
    ids = {item["id"] for item in filtered.json()["items"]}
    assert quad["id"] in ids
    assert fixed["id"] not in ids

    detail = await client.get(f"/api/inventory/drones/{quad['id']}", headers=viewer_headers)
    assert detail.status_code == 200
    assert detail.json()["registered_instances"][0]["call_sign"].startswith("DA-")

    quick = await client.get(
        f"/api/inventory/drones/{quad['id']}/quick-ref",
        headers=viewer_headers,
    )
    assert quick.status_code == 200
    assert quick.json()["key_specs"]["max_payload_kg"] == quad["max_payload_weight_kg"]

    compare = await client.get(
        "/api/inventory/compare",
        params=[("ids", quad["id"]), ("ids", fixed["id"])],
        headers=viewer_headers,
    )
    assert compare.status_code == 200
    assert len(compare.json()["drones"]) == 2
    assert any(row["metric"] == "Endurance" for row in compare.json()["metrics"])

    compare_bad = await client.get(
        "/api/inventory/compare",
        params={"ids": quad["id"]},
        headers=viewer_headers,
    )
    assert compare_bad.status_code == 400

    search = await client.get(
        "/api/inventory/search",
        params={"q": "search target", "limit": 5},
        headers=viewer_headers,
    )
    assert search.status_code == 200
    assert any(item["id"] == quad["id"] for item in search.json()["results"])

    empty_search = await client.get(
        "/api/inventory/search",
        params={"q": ""},
        headers=viewer_headers,
    )
    assert empty_search.status_code == 200
    assert empty_search.json()["total"] == 0

    payloads = await client.get("/api/inventory/payloads", headers=viewer_headers)
    assert payloads.status_code == 200
    assert payloads.json()["items"] == []


async def test_inventory_missing_drone_returns_404(
    client: AsyncClient, viewer_user, make_token
):
    headers = auth_headers(viewer_user, make_token)
    resp = await client.get("/api/inventory/drones/999999", headers=headers)
    assert resp.status_code == 404
