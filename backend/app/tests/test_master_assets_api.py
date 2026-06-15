from httpx import AsyncClient

from app.tests.helpers import (
    auth_headers,
    drone_instance_payload,
    drone_type_payload,
    payload_payload,
    payload_type_payload,
    vessel_payload,
)


async def _create_type(client: AsyncClient, headers: dict) -> dict:
    resp = await client.post("/api/master/drone-types", json=drone_type_payload(), headers=headers)
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _create_drone(client: AsyncClient, headers: dict, type_id: int) -> dict:
    resp = await client.post(
        "/api/master/drones",
        json=drone_instance_payload(type_id),
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def test_drone_instance_endpoints_and_type_archive_block(
    client: AsyncClient, admin_user, flight_controller_user, viewer_user, make_token
):
    admin_headers = auth_headers(admin_user, make_token)
    fc_headers = auth_headers(flight_controller_user, make_token)
    viewer_headers = auth_headers(viewer_user, make_token)
    dtype = await _create_type(client, admin_headers)

    drone = await _create_drone(client, admin_headers, dtype["id"])
    did = drone["id"]
    assert drone["call_sign"].startswith("DA-")
    assert drone["status"] == "offline"

    list_resp = await client.get("/api/master/drones", headers=viewer_headers)
    assert list_resp.status_code == 200
    assert any(item["id"] == did for item in list_resp.json())

    spec_resp = await client.get(f"/api/master/drones/{did}/type-spec", headers=viewer_headers)
    assert spec_resp.status_code == 200
    assert spec_resp.json()["id"] == dtype["id"]

    status_resp = await client.patch(
        f"/api/master/drones/{did}/status",
        json={"status": "online"},
        headers=fc_headers,
    )
    assert status_resp.status_code == 200
    assert status_resp.json()["status"] == "online"

    bad_status = await client.patch(
        f"/api/master/drones/{did}/status",
        json={"status": "flying-sideways"},
        headers=fc_headers,
    )
    assert bad_status.status_code == 400

    update_resp = await client.put(
        f"/api/master/drones/{did}",
        json={"notes": "Updated drone notes", "status": "maintenance"},
        headers=admin_headers,
    )
    assert update_resp.status_code == 200
    assert update_resp.json()["notes"] == "Updated drone notes"

    duplicate = await client.post(
        "/api/master/drones",
        json=drone_instance_payload(
            dtype["id"],
            call_sign=drone["call_sign"],
            serial_number="SN-duplicate-for-call-sign-test",
        ),
        headers=admin_headers,
    )
    assert duplicate.status_code == 409

    blocked_archive = await client.delete(
        f"/api/master/drone-types/{dtype['id']}",
        headers=admin_headers,
    )
    assert blocked_archive.status_code == 409


async def test_vessel_position_assignment_unassignment_and_archive(
    client: AsyncClient, admin_user, flight_controller_user, viewer_user, make_token
):
    admin_headers = auth_headers(admin_user, make_token)
    fc_headers = auth_headers(flight_controller_user, make_token)
    viewer_headers = auth_headers(viewer_user, make_token)
    dtype = await _create_type(client, admin_headers)
    drone = await _create_drone(client, admin_headers, dtype["id"])

    create_resp = await client.post(
        "/api/master/vessels",
        json=vessel_payload(),
        headers=admin_headers,
    )
    assert create_resp.status_code == 201, create_resp.text
    vessel = create_resp.json()
    assert vessel["vessel_id"].startswith("INS-")

    list_resp = await client.get("/api/master/vessels", headers=viewer_headers)
    assert list_resp.status_code == 200
    assert any(item["id"] == vessel["id"] for item in list_resp.json())

    position_resp = await client.post(
        f"/api/master/vessels/{vessel['id']}/position",
        json={"latitude": 13.1, "longitude": 80.2, "heading_deg": 90.0, "speed_kts": 12.5},
        headers=fc_headers,
    )
    assert position_resp.status_code == 200
    assert position_resp.json()["latitude"] == 13.1

    assign_resp = await client.post(
        f"/api/master/vessels/{vessel['id']}/assign-drone/{drone['id']}",
        headers=admin_headers,
    )
    assert assign_resp.status_code == 200

    blocked_archive = await client.delete(
        f"/api/master/vessels/{vessel['id']}",
        headers=admin_headers,
    )
    assert blocked_archive.status_code == 409

    unassign_resp = await client.post(
        f"/api/master/vessels/{vessel['id']}/unassign-drone/{drone['id']}",
        headers=admin_headers,
    )
    assert unassign_resp.status_code == 200

    archive_resp = await client.delete(
        f"/api/master/vessels/{vessel['id']}",
        headers=admin_headers,
    )
    assert archive_resp.status_code == 204


async def test_payload_type_and_payload_crud(
    client: AsyncClient, admin_user, viewer_user, make_token
):
    admin_headers = auth_headers(admin_user, make_token)
    viewer_headers = auth_headers(viewer_user, make_token)

    pt_resp = await client.post(
        "/api/master/payload-types",
        json=payload_type_payload(),
        headers=admin_headers,
    )
    assert pt_resp.status_code == 201, pt_resp.text
    payload_type = pt_resp.json()

    duplicate_pt = await client.post(
        "/api/master/payload-types",
        json=payload_type_payload(name=payload_type["name"]),
        headers=admin_headers,
    )
    assert duplicate_pt.status_code == 409

    payload_resp = await client.post(
        "/api/master/payloads",
        json=payload_payload(payload_type["id"]),
        headers=admin_headers,
    )
    assert payload_resp.status_code == 201, payload_resp.text
    payload = payload_resp.json()

    list_resp = await client.get("/api/master/payloads", headers=viewer_headers)
    assert list_resp.status_code == 200
    assert any(item["id"] == payload["id"] for item in list_resp.json())

    blocked_pt_delete = await client.delete(
        f"/api/master/payload-types/{payload_type['id']}",
        headers=admin_headers,
    )
    assert blocked_pt_delete.status_code == 409

    update_payload = await client.put(
        f"/api/master/payloads/{payload['id']}",
        json={"status": "maintenance", "weight": 1.6},
        headers=admin_headers,
    )
    assert update_payload.status_code == 200
    assert update_payload.json()["status"] == "maintenance"

    delete_payload = await client.delete(
        f"/api/master/payloads/{payload['id']}",
        headers=admin_headers,
    )
    assert delete_payload.status_code == 204

    delete_pt = await client.delete(
        f"/api/master/payload-types/{payload_type['id']}",
        headers=admin_headers,
    )
    assert delete_pt.status_code == 204
