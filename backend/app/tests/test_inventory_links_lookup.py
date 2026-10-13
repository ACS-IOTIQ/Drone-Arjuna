"""
Inventory link lookups, link edits/deletes and drone cross-reference
====================================================================
GET    /api/inventory/links/drones/{id}/payloads      GET /api/inventory/links/payloads/{id}/drones
GET    /api/inventory/links/drones/{id}/threats       GET /api/inventory/links/threats/{id}/drones
GET    /api/inventory/links/payloads/{id}/threats     GET /api/inventory/links/threats/{id}/payloads
PUT    /api/inventory/links/drone-threat/{link_id}    DELETE ... /drone-threat/{link_id}
PUT    /api/inventory/links/payload-threat/{link_id}  DELETE ... /payload-threat/{link_id}
GET    /api/inventory/drones/{id}/cross-reference

(Link creation, the drone-payload PUT/DELETE and the KB profile / search / analytics
queries are covered in test_inventory_kb.py; its fixtures are reused here.)

Topology built by `kb_links_setup`:
    Drone1 carries Payload1 (primary) and Payload2;  Drone2 carries Payload2
    Drone1 is exposed to Threat1 (MEDIUM) and Threat2 (HIGH)
    Payload1 counters Threat1 (HIGH) and Threat2 (MEDIUM);  Payload2 counters Threat2 (HIGH)

Covers:
  - every lookup returns {items, total}, each item = link card + the related entity card,
    in both directions; entities with no links give an empty list
  - unknown ids -> 404 (with the entity named), non-integer ids -> 422
  - PUT: partial updates, empty body is a no-op, invalid levels -> 422, unknown link -> 404,
    change is visible in the lookups
  - DELETE: 204, link disappears from lookups, other links untouched, repeat -> 404
  - cross-reference: compatible payloads, exposure, counterable threats via payloads
  - RBAC: reads need VIEWER; writes need ADMIN; unauthenticated -> 401
"""
import pytest
from httpx import AsyncClient

from app.tests.test_inventory_kb import (  # noqa: F401 — fixtures reused by name
    kb_drone_type,
    kb_drone_type2,
    kb_links_setup,
    kb_payload_type,
    kb_payload_type2,
    kb_threat_system,
    kb_threat_system2,
)

BASE = "/api/inventory"
MISSING = 999_999


def _auth(user, make_token) -> dict:
    return {"Authorization": f"Bearer {make_token(user.id, user.role)}"}


def _ids(items, key):
    return {i[key]["id"] for i in items}


# (route name, URL builder, key holding the related entity, expected related ids builder)
LOOKUPS = [
    ("drone->payloads (drone1)", lambda s: f"{BASE}/links/drones/{s['drones'][0]['id']}/payloads",
     "payload", lambda s: {s["payloads"][0]["id"], s["payloads"][1]["id"]}),
    ("drone->payloads (drone2)", lambda s: f"{BASE}/links/drones/{s['drones'][1]['id']}/payloads",
     "payload", lambda s: {s["payloads"][1]["id"]}),
    ("payload->drones (payload1)", lambda s: f"{BASE}/links/payloads/{s['payloads'][0]['id']}/drones",
     "drone", lambda s: {s["drones"][0]["id"]}),
    ("payload->drones (payload2)", lambda s: f"{BASE}/links/payloads/{s['payloads'][1]['id']}/drones",
     "drone", lambda s: {s["drones"][0]["id"], s["drones"][1]["id"]}),
    ("drone->threats (drone1)", lambda s: f"{BASE}/links/drones/{s['drones'][0]['id']}/threats",
     "threat", lambda s: {s["threats"][0]["id"], s["threats"][1]["id"]}),
    ("threat->drones (threat2)", lambda s: f"{BASE}/links/threats/{s['threats'][1]['id']}/drones",
     "drone", lambda s: {s["drones"][0]["id"]}),
    ("payload->threats (payload1)", lambda s: f"{BASE}/links/payloads/{s['payloads'][0]['id']}/threats",
     "threat", lambda s: {s["threats"][0]["id"], s["threats"][1]["id"]}),
    ("payload->threats (payload2)", lambda s: f"{BASE}/links/payloads/{s['payloads'][1]['id']}/threats",
     "threat", lambda s: {s["threats"][1]["id"]}),
    ("threat->payloads (threat2)", lambda s: f"{BASE}/links/threats/{s['threats'][1]['id']}/payloads",
     "payload", lambda s: {s["payloads"][0]["id"], s["payloads"][1]["id"]}),
    ("threat->payloads (threat1)", lambda s: f"{BASE}/links/threats/{s['threats'][0]['id']}/payloads",
     "payload", lambda s: {s["payloads"][0]["id"]}),
]
LOOKUP_IDS = [name for name, *_ in LOOKUPS]

# Every lookup route with an entity id placeholder, and the 404 message it should produce.
LOOKUP_ROUTES = [
    ("/links/drones/{id}/payloads", "Drone type"),
    ("/links/payloads/{id}/drones", "Payload type"),
    ("/links/drones/{id}/threats", "Drone type"),
    ("/links/threats/{id}/drones", "Threat system"),
    ("/links/payloads/{id}/threats", "Payload type"),
    ("/links/threats/{id}/payloads", "Threat system"),
]


# ══════════════════════════════════════════════════════════════════════
# GET lookups
# ══════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("name,url,key,expected", LOOKUPS, ids=LOOKUP_IDS)
async def test_lookup_returns_the_linked_entities(
    client: AsyncClient, viewer_user, make_token, kb_links_setup, name, url, key, expected
):
    r = await client.get(url(kb_links_setup), headers=_auth(viewer_user, make_token))
    assert r.status_code == 200, r.text
    body = r.json()
    assert set(body) == {"items", "total"}
    assert body["total"] == len(body["items"]) == len(expected(kb_links_setup))
    assert _ids(body["items"], key) == expected(kb_links_setup)


@pytest.mark.parametrize("name,url,key,expected", LOOKUPS, ids=LOOKUP_IDS)
async def test_lookup_items_are_link_cards_without_foreign_key_columns(
    client: AsyncClient, viewer_user, make_token, kb_links_setup, name, url, key, expected
):
    r = await client.get(url(kb_links_setup), headers=_auth(viewer_user, make_token))
    for item in r.json()["items"]:
        assert {"id", "notes", "created_at", key} <= set(item)
        assert "drone_type_id" not in item
        assert "payload_type_id" not in item
        assert "threat_system_id" not in item


async def test_drone_payload_lookup_carries_the_link_attributes(
    client: AsyncClient, viewer_user, make_token, kb_links_setup
):
    d1 = kb_links_setup["drones"][0]["id"]
    p1, p2 = (p["id"] for p in kb_links_setup["payloads"])
    r = await client.get(f"{BASE}/links/drones/{d1}/payloads", headers=_auth(viewer_user, make_token))
    by_payload = {i["payload"]["id"]: i for i in r.json()["items"]}
    assert by_payload[p1]["is_primary"] is True and by_payload[p1]["max_qty"] == 1
    assert by_payload[p2]["is_primary"] is False
    assert by_payload[p1]["notes"] == "Primary EO/IR imaging sensor"
    assert {"id", "name", "category", "weight_kg"} <= set(by_payload[p1]["payload"])


async def test_drone_threat_lookup_carries_the_exposure_level(
    client: AsyncClient, viewer_user, make_token, kb_links_setup
):
    d1 = kb_links_setup["drones"][0]["id"]
    t1, t2 = (t["id"] for t in kb_links_setup["threats"])
    r = await client.get(f"{BASE}/links/drones/{d1}/threats", headers=_auth(viewer_user, make_token))
    levels = {i["threat"]["id"]: i["exposure_level"] for i in r.json()["items"]}
    assert levels == {t1: "MEDIUM", t2: "HIGH"}
    assert {"id", "name", "category", "classification"} <= set(r.json()["items"][0]["threat"])


async def test_payload_threat_lookup_carries_the_effectiveness(
    client: AsyncClient, viewer_user, make_token, kb_links_setup
):
    p1 = kb_links_setup["payloads"][0]["id"]
    t1, t2 = (t["id"] for t in kb_links_setup["threats"])
    r = await client.get(f"{BASE}/links/payloads/{p1}/threats", headers=_auth(viewer_user, make_token))
    effectiveness = {i["threat"]["id"]: i["effectiveness"] for i in r.json()["items"]}
    assert effectiveness == {t1: "HIGH", t2: "MEDIUM"}


async def test_reverse_lookups_agree_with_forward_lookups(
    client: AsyncClient, viewer_user, make_token, kb_links_setup
):
    """Every drone->payload pair seen from the drone side is also seen from the payload side."""
    hdrs = _auth(viewer_user, make_token)
    for drone in kb_links_setup["drones"]:
        fwd = await client.get(f"{BASE}/links/drones/{drone['id']}/payloads", headers=hdrs)
        for item in fwd.json()["items"]:
            back = await client.get(
                f"{BASE}/links/payloads/{item['payload']['id']}/drones", headers=hdrs
            )
            assert drone["id"] in _ids(back.json()["items"], "drone")


async def test_entities_without_links_give_empty_lists(
    client: AsyncClient, viewer_user, make_token, kb_drone_type2, kb_threat_system
):
    hdrs = _auth(viewer_user, make_token)
    for url in (
        f"{BASE}/links/drones/{kb_drone_type2['id']}/payloads",
        f"{BASE}/links/drones/{kb_drone_type2['id']}/threats",
        f"{BASE}/links/threats/{kb_threat_system['id']}/drones",
        f"{BASE}/links/threats/{kb_threat_system['id']}/payloads",
    ):
        r = await client.get(url, headers=hdrs)
        assert r.status_code == 200, (url, r.text)
        assert r.json() == {"items": [], "total": 0}


@pytest.mark.parametrize("route,label", LOOKUP_ROUTES)
async def test_lookup_unknown_entity_is_404_and_names_it(
    client: AsyncClient, viewer_user, make_token, route, label
):
    r = await client.get(BASE + route.format(id=MISSING), headers=_auth(viewer_user, make_token))
    assert r.status_code == 404
    assert f"{label} #{MISSING} not found" in r.json()["detail"]


@pytest.mark.parametrize("route,label", LOOKUP_ROUTES)
async def test_lookup_non_integer_id_is_422(
    client: AsyncClient, viewer_user, make_token, route, label
):
    r = await client.get(BASE + route.format(id="abc"), headers=_auth(viewer_user, make_token))
    assert r.status_code == 422


@pytest.mark.parametrize("route,label", LOOKUP_ROUTES)
async def test_lookup_unauthenticated_401(client: AsyncClient, route, label):
    assert (await client.get(BASE + route.format(id=1))).status_code == 401


# ══════════════════════════════════════════════════════════════════════
# PUT /links/drone-threat/{link_id}  and  /links/payload-threat/{link_id}
# ══════════════════════════════════════════════════════════════════════

async def test_update_drone_threat_link_exposure_level(
    client: AsyncClient, admin_user, make_token, kb_links_setup
):
    link = kb_links_setup["drone_threat_links"][0]               # MEDIUM
    r = await client.put(
        f"{BASE}/links/drone-threat/{link['id']}",
        json={"exposure_level": "CRITICAL"},
        headers=_auth(admin_user, make_token),
    )
    assert r.status_code == 200, r.text
    assert r.json()["exposure_level"] == "CRITICAL"
    assert r.json()["notes"] == link["notes"]                    # untouched field kept


async def test_update_drone_threat_link_notes_only(
    client: AsyncClient, admin_user, make_token, kb_links_setup
):
    link = kb_links_setup["drone_threat_links"][1]               # HIGH
    r = await client.put(
        f"{BASE}/links/drone-threat/{link['id']}",
        json={"notes": "Re-assessed after exercise"},
        headers=_auth(admin_user, make_token),
    )
    assert r.status_code == 200
    assert r.json()["notes"] == "Re-assessed after exercise"
    assert r.json()["exposure_level"] == "HIGH"


async def test_update_drone_threat_link_is_visible_in_the_lookup(
    client: AsyncClient, admin_user, viewer_user, make_token, kb_links_setup
):
    link = kb_links_setup["drone_threat_links"][0]
    d1 = kb_links_setup["drones"][0]["id"]
    t1 = kb_links_setup["threats"][0]["id"]
    await client.put(f"{BASE}/links/drone-threat/{link['id']}", json={"exposure_level": "LOW"},
                     headers=_auth(admin_user, make_token))
    r = await client.get(f"{BASE}/links/drones/{d1}/threats", headers=_auth(viewer_user, make_token))
    levels = {i["threat"]["id"]: i["exposure_level"] for i in r.json()["items"]}
    assert levels[t1] == "LOW"


async def test_update_payload_threat_link_effectiveness(
    client: AsyncClient, admin_user, make_token, kb_links_setup
):
    link = kb_links_setup["payload_threat_links"][1]             # MEDIUM
    r = await client.put(
        f"{BASE}/links/payload-threat/{link['id']}",
        json={"effectiveness": "LOW", "notes": "Degraded in rain"},
        headers=_auth(admin_user, make_token),
    )
    assert r.status_code == 200, r.text
    assert r.json()["effectiveness"] == "LOW"
    assert r.json()["notes"] == "Degraded in rain"


@pytest.mark.parametrize("path,field", [
    ("drone-threat", "exposure_level"),
    ("payload-threat", "effectiveness"),
])
async def test_update_link_with_empty_body_changes_nothing(
    client: AsyncClient, admin_user, make_token, kb_links_setup, path, field
):
    link = kb_links_setup["drone_threat_links" if path == "drone-threat" else "payload_threat_links"][0]
    r = await client.put(f"{BASE}/links/{path}/{link['id']}", json={}, headers=_auth(admin_user, make_token))
    assert r.status_code == 200
    assert r.json()[field] == link[field]
    assert r.json()["notes"] == link["notes"]


@pytest.mark.parametrize("path,field", [
    ("drone-threat", "exposure_level"),
    ("payload-threat", "effectiveness"),
])
@pytest.mark.parametrize("bad", ["EXTREME", "high", "", 5])
async def test_update_link_rejects_levels_outside_the_allowed_set(
    client: AsyncClient, admin_user, make_token, kb_links_setup, path, field, bad
):
    link = kb_links_setup["drone_threat_links" if path == "drone-threat" else "payload_threat_links"][0]
    r = await client.put(f"{BASE}/links/{path}/{link['id']}", json={field: bad},
                         headers=_auth(admin_user, make_token))
    assert r.status_code == 422


@pytest.mark.parametrize("level", ["LOW", "MEDIUM", "HIGH", "CRITICAL"])
async def test_update_link_accepts_every_allowed_level(
    client: AsyncClient, admin_user, make_token, kb_links_setup, level
):
    link = kb_links_setup["drone_threat_links"][0]
    r = await client.put(f"{BASE}/links/drone-threat/{link['id']}", json={"exposure_level": level},
                         headers=_auth(admin_user, make_token))
    assert r.status_code == 200 and r.json()["exposure_level"] == level


@pytest.mark.parametrize("path", ["drone-threat", "payload-threat"])
async def test_update_unknown_link_is_404(client: AsyncClient, admin_user, make_token, path):
    r = await client.put(f"{BASE}/links/{path}/{MISSING}", json={"notes": "x"},
                         headers=_auth(admin_user, make_token))
    assert r.status_code == 404
    assert f"#{MISSING} not found" in r.json()["detail"]


@pytest.mark.parametrize("path", ["drone-threat", "payload-threat"])
async def test_update_link_non_integer_id_is_422(client: AsyncClient, admin_user, make_token, path):
    r = await client.put(f"{BASE}/links/{path}/abc", json={}, headers=_auth(admin_user, make_token))
    assert r.status_code == 422


@pytest.mark.parametrize("path", ["drone-threat", "payload-threat"])
async def test_update_link_forbidden_for_non_admins(
    client: AsyncClient, viewer_user, mission_commander_user, make_token, kb_links_setup, path
):
    link = kb_links_setup["drone_threat_links" if path == "drone-threat" else "payload_threat_links"][0]
    for user in (viewer_user, mission_commander_user):
        r = await client.put(f"{BASE}/links/{path}/{link['id']}", json={"notes": "nope"},
                             headers=_auth(user, make_token))
        assert r.status_code == 403, (path, user.role)


@pytest.mark.parametrize("path", ["drone-threat", "payload-threat"])
async def test_update_link_unauthenticated_401(client: AsyncClient, path):
    assert (await client.put(f"{BASE}/links/{path}/1", json={})).status_code == 401


# ══════════════════════════════════════════════════════════════════════
# DELETE /links/drone-threat/{link_id}  and  /links/payload-threat/{link_id}
# ══════════════════════════════════════════════════════════════════════

async def test_delete_drone_threat_link_removes_only_that_link(
    client: AsyncClient, admin_user, viewer_user, make_token, kb_links_setup
):
    d1 = kb_links_setup["drones"][0]["id"]
    t1, t2 = (t["id"] for t in kb_links_setup["threats"])
    link = kb_links_setup["drone_threat_links"][0]               # drone1 <-> threat1

    r = await client.delete(f"{BASE}/links/drone-threat/{link['id']}", headers=_auth(admin_user, make_token))
    assert r.status_code == 204
    assert r.content == b""

    after = await client.get(f"{BASE}/links/drones/{d1}/threats", headers=_auth(viewer_user, make_token))
    assert _ids(after.json()["items"], "threat") == {t2}          # the other link survives
    reverse = await client.get(f"{BASE}/links/threats/{t1}/drones", headers=_auth(viewer_user, make_token))
    assert reverse.json()["items"] == []


async def test_delete_payload_threat_link_removes_only_that_link(
    client: AsyncClient, admin_user, viewer_user, make_token, kb_links_setup
):
    p1 = kb_links_setup["payloads"][0]["id"]
    t1, t2 = (t["id"] for t in kb_links_setup["threats"])
    link = kb_links_setup["payload_threat_links"][0]             # payload1 <-> threat1

    r = await client.delete(f"{BASE}/links/payload-threat/{link['id']}", headers=_auth(admin_user, make_token))
    assert r.status_code == 204

    after = await client.get(f"{BASE}/links/payloads/{p1}/threats", headers=_auth(viewer_user, make_token))
    assert _ids(after.json()["items"], "threat") == {t2}


@pytest.mark.parametrize("path", ["drone-threat", "payload-threat"])
async def test_delete_link_twice_second_is_404(
    client: AsyncClient, admin_user, make_token, kb_links_setup, path
):
    link = kb_links_setup["drone_threat_links" if path == "drone-threat" else "payload_threat_links"][0]
    hdrs = _auth(admin_user, make_token)
    assert (await client.delete(f"{BASE}/links/{path}/{link['id']}", headers=hdrs)).status_code == 204
    assert (await client.delete(f"{BASE}/links/{path}/{link['id']}", headers=hdrs)).status_code == 404


@pytest.mark.parametrize("path", ["drone-threat", "payload-threat"])
async def test_delete_unknown_link_is_404(client: AsyncClient, admin_user, make_token, path):
    r = await client.delete(f"{BASE}/links/{path}/{MISSING}", headers=_auth(admin_user, make_token))
    assert r.status_code == 404


async def test_deleted_link_can_be_created_again(
    client: AsyncClient, admin_user, make_token, kb_links_setup
):
    hdrs = _auth(admin_user, make_token)
    link = kb_links_setup["drone_threat_links"][0]
    body = {
        "drone_type_id": kb_links_setup["drones"][0]["id"],
        "threat_system_id": kb_links_setup["threats"][0]["id"],
        "exposure_level": "LOW",
    }
    assert (await client.post(f"{BASE}/links/drone-threat", json=body, headers=hdrs)).status_code == 409
    await client.delete(f"{BASE}/links/drone-threat/{link['id']}", headers=hdrs)
    assert (await client.post(f"{BASE}/links/drone-threat", json=body, headers=hdrs)).status_code == 201


@pytest.mark.parametrize("path", ["drone-threat", "payload-threat"])
async def test_delete_link_forbidden_for_non_admins(
    client: AsyncClient, viewer_user, mission_commander_user, make_token, kb_links_setup, path
):
    link = kb_links_setup["drone_threat_links" if path == "drone-threat" else "payload_threat_links"][0]
    for user in (viewer_user, mission_commander_user):
        r = await client.delete(f"{BASE}/links/{path}/{link['id']}", headers=_auth(user, make_token))
        assert r.status_code == 403, (path, user.role)


@pytest.mark.parametrize("path", ["drone-threat", "payload-threat"])
async def test_delete_link_unauthenticated_401(client: AsyncClient, path):
    assert (await client.delete(f"{BASE}/links/{path}/1")).status_code == 401


async def test_forbidden_delete_leaves_the_link_in_place(
    client: AsyncClient, viewer_user, make_token, kb_links_setup
):
    link = kb_links_setup["drone_threat_links"][0]
    d1 = kb_links_setup["drones"][0]["id"]
    await client.delete(f"{BASE}/links/drone-threat/{link['id']}", headers=_auth(viewer_user, make_token))
    r = await client.get(f"{BASE}/links/drones/{d1}/threats", headers=_auth(viewer_user, make_token))
    assert r.json()["total"] == 2


# ══════════════════════════════════════════════════════════════════════
# GET /drones/{drone_type_id}/cross-reference
# ══════════════════════════════════════════════════════════════════════

async def test_cross_reference_full_neighbourhood_of_drone1(
    client: AsyncClient, viewer_user, make_token, kb_links_setup
):
    d1 = kb_links_setup["drones"][0]
    p1, p2 = (p["id"] for p in kb_links_setup["payloads"])
    t1, t2 = (t["id"] for t in kb_links_setup["threats"])

    r = await client.get(f"{BASE}/drones/{d1['id']}/cross-reference", headers=_auth(viewer_user, make_token))
    assert r.status_code == 200, r.text
    body = r.json()
    assert set(body) == {"drone", "compatible_payloads", "exposed_to_threats", "can_counter_threats"}
    assert body["drone"]["id"] == d1["id"]
    assert body["drone"]["name"] == d1["name"]
    assert _ids(body["compatible_payloads"], "payload") == {p1, p2}
    assert _ids(body["exposed_to_threats"], "threat") == {t1, t2}
    # threats this drone can counter, reached through each of its payloads
    assert {(c["via_payload"]["id"], c["threat"]["id"]) for c in body["can_counter_threats"]} == {
        (p1, t1), (p1, t2), (p2, t2),
    }
    assert all("effectiveness" in c for c in body["can_counter_threats"])


async def test_cross_reference_only_counts_the_drones_own_payloads(
    client: AsyncClient, viewer_user, make_token, kb_links_setup
):
    d2 = kb_links_setup["drones"][1]                             # carries Payload2 only
    p2 = kb_links_setup["payloads"][1]["id"]
    t2 = kb_links_setup["threats"][1]["id"]

    r = await client.get(f"{BASE}/drones/{d2['id']}/cross-reference", headers=_auth(viewer_user, make_token))
    body = r.json()
    assert _ids(body["compatible_payloads"], "payload") == {p2}
    assert body["exposed_to_threats"] == []
    assert [(c["via_payload"]["id"], c["threat"]["id"]) for c in body["can_counter_threats"]] == [(p2, t2)]


async def test_cross_reference_for_drone_without_links_is_all_empty(
    client: AsyncClient, viewer_user, make_token, kb_drone_type2
):
    r = await client.get(f"{BASE}/drones/{kb_drone_type2['id']}/cross-reference",
                         headers=_auth(viewer_user, make_token))
    assert r.status_code == 200
    body = r.json()
    assert body["drone"]["id"] == kb_drone_type2["id"]
    assert body["compatible_payloads"] == []
    assert body["exposed_to_threats"] == []
    assert body["can_counter_threats"] == []


async def test_cross_reference_reflects_a_deleted_link(
    client: AsyncClient, admin_user, viewer_user, make_token, kb_links_setup
):
    d1 = kb_links_setup["drones"][0]["id"]
    p1 = kb_links_setup["payloads"][0]["id"]
    # remove Payload1's links to both threats -> Drone1 can no longer counter via Payload1
    for link in kb_links_setup["payload_threat_links"][:2]:
        await client.delete(f"{BASE}/links/payload-threat/{link['id']}", headers=_auth(admin_user, make_token))
    r = await client.get(f"{BASE}/drones/{d1}/cross-reference", headers=_auth(viewer_user, make_token))
    assert p1 not in {c["via_payload"]["id"] for c in r.json()["can_counter_threats"]}


async def test_cross_reference_unknown_drone_type_404(client: AsyncClient, viewer_user, make_token):
    r = await client.get(f"{BASE}/drones/{MISSING}/cross-reference", headers=_auth(viewer_user, make_token))
    assert r.status_code == 404
    assert f"Drone type #{MISSING} not found" in r.json()["detail"]


async def test_cross_reference_non_integer_id_422(client: AsyncClient, viewer_user, make_token):
    r = await client.get(f"{BASE}/drones/abc/cross-reference", headers=_auth(viewer_user, make_token))
    assert r.status_code == 422


async def test_cross_reference_unauthenticated_401(client: AsyncClient):
    assert (await client.get(f"{BASE}/drones/1/cross-reference")).status_code == 401
