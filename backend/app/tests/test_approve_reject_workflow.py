"""
Approve / Reject Workflow — Regression Tests
=============================================
These tests lock in the exact backend contract that the fixed UserManager.tsx
now relies on. The frontend bug (2026-07-02) called /api/auth/register with an
undefined body instead of the correct /accept and /reject endpoints.

Scenarios covered:

  Approve path (the broken path)
  ──────────────────────────────
  AR-01  POST /api/auth/access-requests/{id}/accept returns 200 (not the
         /register endpoint which would return 422 on malformed body)
  AR-02  Response contains temp_password (frontend merges this into the row)
  AR-03  Response contains status='approved' and reviewed_at (frontend state update)
  AR-04  Accepted user immediately appears in GET /api/auth/users (loadUsers refresh)
  AR-05  role_override is honoured when supplied
  AR-06  admin_note is persisted and returned (admin note visible in list)

  Reject path (was local-only — never hit backend)
  ─────────────────────────────────────────────────
  AR-07  POST /api/auth/access-requests/{id}/reject returns 200
  AR-08  Response contains status='rejected' and reviewed_at
  AR-09  Rejected request does NOT create a user account
  AR-10  admin_note is persisted when supplied
  AR-11  Rejected row visible in GET /api/auth/access-requests with status='rejected'

  Guard rails (double-action prevention)
  ───────────────────────────────────────
  AR-12  Accepting an already-approved request → 409
  AR-13  Rejecting an already-rejected request → 409
  AR-14  Accepting a rejected request → 409
  AR-15  Rejecting an approved request → 409

  Auth guards
  ───────────
  AR-16  Viewer cannot accept → 403
  AR-17  Viewer cannot reject → 403
  AR-18  Unauthenticated accept → 401
  AR-19  Unauthenticated reject → 401
  AR-20  Non-existent request id on accept → 404
  AR-21  Non-existent request id on reject → 404
"""
import pytest
from httpx import AsyncClient

from app.tests.helpers import access_request_payload, auth_headers


# ── Shared fixtures ────────────────────────────────────────────────────────────

@pytest.fixture
async def pending(client: AsyncClient):
    """Create one pending access request; yield its id and original body."""
    body = access_request_payload()
    resp = await client.post("/api/auth/request-access", json=body)
    assert resp.status_code == 201
    return {"id": resp.json()["id"], "body": body}


@pytest.fixture
async def pending2(client: AsyncClient):
    """A second independent pending request for tests that need two."""
    body = access_request_payload()
    resp = await client.post("/api/auth/request-access", json=body)
    assert resp.status_code == 201
    return {"id": resp.json()["id"], "body": body}


# ═══════════════════════════════════════════════════════════════════════════════
# AR-01 … AR-06  Approve path
# ═══════════════════════════════════════════════════════════════════════════════

async def test_ar01_accept_returns_200(
    client: AsyncClient, admin_user, make_token, pending
):
    """AR-01: /accept endpoint returns HTTP 200, not the /register endpoint."""
    hdrs = auth_headers(admin_user, make_token)
    resp = await client.post(
        f"/api/auth/access-requests/{pending['id']}/accept",
        json={},
        headers=hdrs,
    )
    assert resp.status_code == 200


async def test_ar02_accept_response_contains_temp_password(
    client: AsyncClient, admin_user, make_token, pending
):
    """AR-02: Response must include a non-empty temp_password for the frontend to display."""
    hdrs = auth_headers(admin_user, make_token)
    resp = await client.post(
        f"/api/auth/access-requests/{pending['id']}/accept",
        json={},
        headers=hdrs,
    )
    data = resp.json()
    assert "temp_password" in data
    assert data["temp_password"] is not None
    assert len(data["temp_password"]) >= 10


async def test_ar03_accept_response_shape_for_frontend_state_merge(
    client: AsyncClient, admin_user, make_token, pending
):
    """AR-03: Response must carry status='approved' and reviewed_at so the
    frontend can merge it directly into the requests array."""
    hdrs = auth_headers(admin_user, make_token)
    resp = await client.post(
        f"/api/auth/access-requests/{pending['id']}/accept",
        json={},
        headers=hdrs,
    )
    data = resp.json()
    assert data["status"] == "approved"
    assert data["reviewed_at"] is not None
    assert data["id"] == pending["id"]


async def test_ar04_accepted_user_appears_in_users_list(
    client: AsyncClient, admin_user, make_token, pending
):
    """AR-04: After accept, GET /api/auth/users must include the new account
    (verifies the frontend's loadUsers() refresh will succeed)."""
    hdrs = auth_headers(admin_user, make_token)
    await client.post(
        f"/api/auth/access-requests/{pending['id']}/accept",
        json={},
        headers=hdrs,
    )
    users_resp = await client.get("/api/auth/users", headers=hdrs)
    assert users_resp.status_code == 200
    usernames = [u["username"] for u in users_resp.json()]
    assert pending["body"]["username"] in usernames


async def test_ar05_role_override_applied(
    client: AsyncClient, admin_user, make_token
):
    """AR-05: role_override in the accept body replaces the requested_role."""
    body = access_request_payload(requested_role="viewer")
    req_resp = await client.post("/api/auth/request-access", json=body)
    req_id = req_resp.json()["id"]

    hdrs = auth_headers(admin_user, make_token)
    accept = await client.post(
        f"/api/auth/access-requests/{req_id}/accept",
        json={"role_override": "mission_commander"},
        headers=hdrs,
    )
    assert accept.status_code == 200

    # Verify the created account carries the overridden role
    login = await client.post(
        "/api/auth/token",
        data={"username": body["username"], "password": accept.json()["temp_password"]},
    )
    assert login.status_code == 200
    assert login.json()["role"] == "mission_commander"


async def test_ar06_admin_note_persisted_on_accept(
    client: AsyncClient, admin_user, make_token, pending
):
    """AR-06: admin_note supplied in accept body is stored and returned."""
    hdrs = auth_headers(admin_user, make_token)
    note = "Cleared by OC — July batch"
    resp = await client.post(
        f"/api/auth/access-requests/{pending['id']}/accept",
        json={"admin_note": note},
        headers=hdrs,
    )
    assert resp.status_code == 200
    assert resp.json()["admin_note"] == note


# ═══════════════════════════════════════════════════════════════════════════════
# AR-07 … AR-11  Reject path
# ═══════════════════════════════════════════════════════════════════════════════

async def test_ar07_reject_returns_200(
    client: AsyncClient, admin_user, make_token, pending
):
    """AR-07: /reject endpoint returns HTTP 200 (was previously local-only in
    the frontend — this confirms the endpoint exists and responds correctly)."""
    hdrs = auth_headers(admin_user, make_token)
    resp = await client.post(
        f"/api/auth/access-requests/{pending['id']}/reject",
        json={},
        headers=hdrs,
    )
    assert resp.status_code == 200


async def test_ar08_reject_response_shape_for_frontend_state_merge(
    client: AsyncClient, admin_user, make_token, pending
):
    """AR-08: Response must carry status='rejected' and reviewed_at so the
    frontend can merge it into the requests array without a reload."""
    hdrs = auth_headers(admin_user, make_token)
    resp = await client.post(
        f"/api/auth/access-requests/{pending['id']}/reject",
        json={},
        headers=hdrs,
    )
    data = resp.json()
    assert data["status"] == "rejected"
    assert data["reviewed_at"] is not None
    assert data["id"] == pending["id"]


async def test_ar09_reject_does_not_create_user(
    client: AsyncClient, admin_user, make_token, pending
):
    """AR-09: Rejecting a request must NOT create a user account."""
    hdrs = auth_headers(admin_user, make_token)
    await client.post(
        f"/api/auth/access-requests/{pending['id']}/reject",
        json={},
        headers=hdrs,
    )
    users_resp = await client.get("/api/auth/users", headers=hdrs)
    usernames = [u["username"] for u in users_resp.json()]
    assert pending["body"]["username"] not in usernames


async def test_ar10_admin_note_persisted_on_reject(
    client: AsyncClient, admin_user, make_token, pending
):
    """AR-10: admin_note supplied in reject body is stored and returned."""
    hdrs = auth_headers(admin_user, make_token)
    note = "Request rejected by administrator."
    resp = await client.post(
        f"/api/auth/access-requests/{pending['id']}/reject",
        json={"admin_note": note},
        headers=hdrs,
    )
    assert resp.status_code == 200
    assert resp.json()["admin_note"] == note


async def test_ar11_rejected_row_visible_in_list(
    client: AsyncClient, admin_user, make_token, pending
):
    """AR-11: After rejection, GET /access-requests returns the row with
    status='rejected' so the frontend list re-renders correctly."""
    hdrs = auth_headers(admin_user, make_token)
    await client.post(
        f"/api/auth/access-requests/{pending['id']}/reject",
        json={},
        headers=hdrs,
    )
    list_resp = await client.get("/api/auth/access-requests", headers=hdrs)
    records = list_resp.json()
    match = next((r for r in records if r["id"] == pending["id"]), None)
    assert match is not None
    assert match["status"] == "rejected"


# ═══════════════════════════════════════════════════════════════════════════════
# AR-12 … AR-15  Double-action guard rails
# ═══════════════════════════════════════════════════════════════════════════════

async def test_ar12_double_accept_is_409(
    client: AsyncClient, admin_user, make_token, pending
):
    """AR-12: Accepting an already-approved request must return 409."""
    hdrs = auth_headers(admin_user, make_token)
    req_id = pending["id"]
    first = await client.post(
        f"/api/auth/access-requests/{req_id}/accept", json={}, headers=hdrs
    )
    assert first.status_code == 200
    second = await client.post(
        f"/api/auth/access-requests/{req_id}/accept", json={}, headers=hdrs
    )
    assert second.status_code == 409


async def test_ar13_double_reject_is_409(
    client: AsyncClient, admin_user, make_token, pending
):
    """AR-13: Rejecting an already-rejected request must return 409."""
    hdrs = auth_headers(admin_user, make_token)
    req_id = pending["id"]
    first = await client.post(
        f"/api/auth/access-requests/{req_id}/reject", json={}, headers=hdrs
    )
    assert first.status_code == 200
    second = await client.post(
        f"/api/auth/access-requests/{req_id}/reject", json={}, headers=hdrs
    )
    assert second.status_code == 409


async def test_ar14_accept_after_reject_is_409(
    client: AsyncClient, admin_user, make_token, pending
):
    """AR-14: A rejected request cannot be subsequently accepted."""
    hdrs = auth_headers(admin_user, make_token)
    req_id = pending["id"]
    await client.post(f"/api/auth/access-requests/{req_id}/reject", json={}, headers=hdrs)
    accept = await client.post(
        f"/api/auth/access-requests/{req_id}/accept", json={}, headers=hdrs
    )
    assert accept.status_code == 409


async def test_ar15_reject_after_accept_is_409(
    client: AsyncClient, admin_user, make_token, pending
):
    """AR-15: An approved request cannot be subsequently rejected."""
    hdrs = auth_headers(admin_user, make_token)
    req_id = pending["id"]
    await client.post(f"/api/auth/access-requests/{req_id}/accept", json={}, headers=hdrs)
    reject = await client.post(
        f"/api/auth/access-requests/{req_id}/reject", json={}, headers=hdrs
    )
    assert reject.status_code == 409


# ═══════════════════════════════════════════════════════════════════════════════
# AR-16 … AR-21  Auth guards
# ═══════════════════════════════════════════════════════════════════════════════

async def test_ar16_viewer_cannot_accept(
    client: AsyncClient, viewer_user, make_token, pending
):
    """AR-16: Viewer role must receive 403 on accept."""
    hdrs = auth_headers(viewer_user, make_token)
    resp = await client.post(
        f"/api/auth/access-requests/{pending['id']}/accept", json={}, headers=hdrs
    )
    assert resp.status_code == 403


async def test_ar17_viewer_cannot_reject(
    client: AsyncClient, viewer_user, make_token, pending
):
    """AR-17: Viewer role must receive 403 on reject."""
    hdrs = auth_headers(viewer_user, make_token)
    resp = await client.post(
        f"/api/auth/access-requests/{pending['id']}/reject", json={}, headers=hdrs
    )
    assert resp.status_code == 403


async def test_ar18_unauthenticated_accept_is_401(
    client: AsyncClient, pending
):
    """AR-18: No Bearer token on accept → 401."""
    resp = await client.post(
        f"/api/auth/access-requests/{pending['id']}/accept", json={}
    )
    assert resp.status_code == 401


async def test_ar19_unauthenticated_reject_is_401(
    client: AsyncClient, pending
):
    """AR-19: No Bearer token on reject → 401."""
    resp = await client.post(
        f"/api/auth/access-requests/{pending['id']}/reject", json={}
    )
    assert resp.status_code == 401


async def test_ar20_accept_nonexistent_is_404(
    client: AsyncClient, admin_user, make_token
):
    """AR-20: Accepting a non-existent request id must return 404."""
    hdrs = auth_headers(admin_user, make_token)
    resp = await client.post(
        "/api/auth/access-requests/99999/accept", json={}, headers=hdrs
    )
    assert resp.status_code == 404


async def test_ar21_reject_nonexistent_is_404(
    client: AsyncClient, admin_user, make_token
):
    """AR-21: Rejecting a non-existent request id must return 404."""
    hdrs = auth_headers(admin_user, make_token)
    resp = await client.post(
        "/api/auth/access-requests/99999/reject", json={}, headers=hdrs
    )
    assert resp.status_code == 404
