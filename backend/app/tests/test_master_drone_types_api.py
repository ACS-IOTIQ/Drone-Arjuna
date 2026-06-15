from httpx import AsyncClient

from app.tests.helpers import auth_headers, drone_type_payload


async def create_drone_type(client: AsyncClient, headers: dict, **overrides) -> dict:
    resp = await client.post(
        "/api/master/drone-types",
        json=drone_type_payload(**overrides),
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def test_drone_type_crud_stats_and_archive(
    client: AsyncClient, admin_user, viewer_user, make_token
):
    admin_headers = auth_headers(admin_user, make_token)
    viewer_headers = auth_headers(viewer_user, make_token)

    created = await create_drone_type(client, admin_headers, size_class="medium")
    tid = created["id"]
    assert created["is_active"] is True

    list_resp = await client.get("/api/master/drone-types", headers=viewer_headers)
    assert list_resp.status_code == 200
    assert any(item["id"] == tid for item in list_resp.json())

    get_resp = await client.get(f"/api/master/drone-types/{tid}", headers=viewer_headers)
    assert get_resp.status_code == 200
    assert get_resp.json()["name"] == created["name"]

    stats_resp = await client.get("/api/master/drone-types/stats", headers=viewer_headers)
    assert stats_resp.status_code == 200
    assert stats_resp.json()["total_active_types"] >= 1
    assert stats_resp.json()["by_size_class"]["medium"] >= 1

    update_resp = await client.put(
        f"/api/master/drone-types/{tid}",
        json={"notes": "Updated in API test", "range_km": 95.0},
        headers=admin_headers,
    )
    assert update_resp.status_code == 200
    assert update_resp.json()["range_km"] == 95.0

    delete_resp = await client.delete(f"/api/master/drone-types/{tid}", headers=admin_headers)
    assert delete_resp.status_code == 204

    archived_get = await client.get(f"/api/master/drone-types/{tid}", headers=viewer_headers)
    assert archived_get.status_code == 404


async def test_drone_type_create_requires_mission_commander_or_admin(
    client: AsyncClient, viewer_user, make_token
):
    resp = await client.post(
        "/api/master/drone-types",
        json=drone_type_payload(),
        headers=auth_headers(viewer_user, make_token),
    )
    assert resp.status_code == 403


async def test_drone_type_duplicate_and_validation_errors(
    client: AsyncClient, admin_user, make_token
):
    headers = auth_headers(admin_user, make_token)
    payload = drone_type_payload(name="Duplicate Guard Type")

    first = await client.post("/api/master/drone-types", json=payload, headers=headers)
    assert first.status_code == 201

    duplicate = await client.post("/api/master/drone-types", json=payload, headers=headers)
    assert duplicate.status_code == 409

    invalid = drone_type_payload(
        max_speed_ms=20.0,
        cruise_speed_ms=25.0,
        max_takeoff_weight_kg=5.0,
        max_payload_weight_kg=1.0,
    )
    invalid_resp = await client.post("/api/master/drone-types", json=invalid, headers=headers)
    assert invalid_resp.status_code == 422
