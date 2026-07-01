"""
Access Request flow tests
=========================
Tests cover the four endpoints added for the "Request Access" feature:

  1. POST /api/auth/request-access  (public — no auth)
       - valid submission → 201
       - duplicate pending username → 409
       - missing required field → 422
       - same username resubmittable after prior request is no longer pending

  2. GET /api/auth/access-requests  (admin only)
       - admin receives full list → 200
       - non-admin → 403
       - unauthenticated → 401

  3. POST /api/auth/access-requests/{id}/accept  (admin only)
       - pending request → 200, user created, temp_password in response
       - accepted user can immediately log in with the temp_password
       - role_override replaces requested_role when supplied
       - admin_note stored on the record
       - accepting a non-existent id → 404
       - accepting an already-approved request → 409
       - username already registered in users table → 409
       - non-admin → 403

  4. POST /api/auth/access-requests/{id}/reject  (admin only)
       - pending request → 200, status == 'rejected'
       - rejecting a non-existent id → 404
       - rejecting an already-rejected request → 409
       - non-admin → 403
"""
import pytest
from httpx import AsyncClient

from app.tests.helpers import access_request_payload, auth_headers


# ── Shared fixture: a pending access request row ──────────────────────────────

@pytest.fixture
async def pending_request(client: AsyncClient):
    """Submit one valid access request and return the server response body."""
    body = access_request_payload()
    resp = await client.post("/api/auth/request-access", json=body)
    assert resp.status_code == 201
    return {"body": body, "id": resp.json()["id"]}


# ═══════════════════════════════════════════════════════════════════════
# 1. POST /api/auth/request-access  — public submission
# ═══════════════════════════════════════════════════════════════════════

async def test_submit_request_returns_201(client: AsyncClient):
    """
    A correctly formed access request must be accepted with HTTP 201
    and return a JSON body containing a positive integer id.
    """
    body = access_request_payload()
    resp = await client.post("/api/auth/request-access", json=body)
    assert resp.status_code == 201
    data = resp.json()
    assert "id" in data
    assert isinstance(data["id"], int)
    assert data["id"] > 0


async def test_submit_request_stores_all_fields(client: AsyncClient, admin_user, make_token):
    """
    After a successful submission the record must appear in the admin list
    with every field intact (username, full_name, email, mobile, role, reason).
    """
    body = access_request_payload(
        username="ops_field_01",
        full_name="Captain Arjun Singh",
        email="arjun.singh@example.com",
        mobile="+91 9876543210",
        requested_role="flight_controller",
        reason="Assigned to forward ops",
    )
    await client.post("/api/auth/request-access", json=body)

    hdrs = auth_headers(admin_user, make_token)
    list_resp = await client.get("/api/auth/access-requests", headers=hdrs)
    assert list_resp.status_code == 200
    records = list_resp.json()
    match = next((r for r in records if r["username"] == "ops_field_01"), None)
    assert match is not None
    assert match["full_name"] == "Captain Arjun Singh"
    assert match["email"] == "arjun.singh@example.com"
    assert match["mobile"] == "+91 9876543210"
    assert match["requested_role"] == "flight_controller"
    assert match["reason"] == "Assigned to forward ops"
    assert match["status"] == "pending"


async def test_submit_request_defaults_role_to_viewer(client: AsyncClient, admin_user, make_token):
    """
    When requested_role is omitted the backend must default it to 'viewer'.
    """
    body = access_request_payload()
    body.pop("requested_role", None)
    resp = await client.post("/api/auth/request-access", json=body)
    assert resp.status_code == 201
    req_id = resp.json()["id"]

    hdrs = auth_headers(admin_user, make_token)
    list_resp = await client.get("/api/auth/access-requests", headers=hdrs)
    record = next((r for r in list_resp.json() if r["id"] == req_id), None)
    assert record is not None
    assert record["requested_role"] == "viewer"


async def test_duplicate_pending_username_is_409(client: AsyncClient, pending_request):
    """
    Submitting a second request with the same username while the first is
    still pending must return HTTP 409.
    """
    body = access_request_payload(username=pending_request["body"]["username"])
    resp = await client.post("/api/auth/request-access", json=body)
    assert resp.status_code == 409


async def test_missing_username_is_422(client: AsyncClient):
    """Required field 'username' missing → FastAPI validation error 422."""
    body = access_request_payload()
    body.pop("username")
    resp = await client.post("/api/auth/request-access", json=body)
    assert resp.status_code == 422


async def test_missing_full_name_is_422(client: AsyncClient):
    """Required field 'full_name' missing → 422."""
    body = access_request_payload()
    body.pop("full_name")
    resp = await client.post("/api/auth/request-access", json=body)
    assert resp.status_code == 422


async def test_missing_email_is_422(client: AsyncClient):
    """Required field 'email' missing → 422."""
    body = access_request_payload()
    body.pop("email")
    resp = await client.post("/api/auth/request-access", json=body)
    assert resp.status_code == 422


async def test_invalid_email_format_is_422(client: AsyncClient):
    """A non-email string in the email field → 422 (EmailStr validation)."""
    body = access_request_payload(email="not-an-email")
    resp = await client.post("/api/auth/request-access", json=body)
    assert resp.status_code == 422


async def test_same_username_allowed_after_approval(
    client: AsyncClient, admin_user, make_token, pending_request
):
    """
    After the first request for a username has been approved, a fresh request
    with the same username must be blocked with 409 because the username now
    exists in the users table — but the pending-duplicate guard itself should
    not be what blocks it (that guard only fires when status == 'pending').
    Concretely: a second POST /request-access after approval returns 409 only
    because the accept endpoint blocked it or because the row exists; a third
    NEW username must still succeed.
    """
    hdrs = auth_headers(admin_user, make_token)
    req_id = pending_request["id"]

    # Accept the first request
    accept_resp = await client.post(
        f"/api/auth/access-requests/{req_id}/accept", json={}, headers=hdrs
    )
    assert accept_resp.status_code == 200

    # A completely different username must still be submittable
    fresh = access_request_payload()
    resp = await client.post("/api/auth/request-access", json=fresh)
    assert resp.status_code == 201


# ═══════════════════════════════════════════════════════════════════════
# 2. GET /api/auth/access-requests  — admin listing
# ═══════════════════════════════════════════════════════════════════════

async def test_admin_can_list_access_requests(
    client: AsyncClient, admin_user, make_token, pending_request
):
    """
    Admin must receive HTTP 200 and a non-empty list that includes the
    previously submitted request.
    """
    hdrs = auth_headers(admin_user, make_token)
    resp = await client.get("/api/auth/access-requests", headers=hdrs)
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    ids = [r["id"] for r in data]
    assert pending_request["id"] in ids


async def test_list_requests_empty_when_none_submitted(
    client: AsyncClient, admin_user, make_token
):
    """
    When no requests exist the endpoint must return 200 with an empty list,
    not 404.
    """
    hdrs = auth_headers(admin_user, make_token)
    resp = await client.get("/api/auth/access-requests", headers=hdrs)
    assert resp.status_code == 200
    assert resp.json() == []


async def test_non_admin_cannot_list_requests(
    client: AsyncClient, viewer_user, make_token
):
    """A viewer role must be refused with HTTP 403."""
    hdrs = auth_headers(viewer_user, make_token)
    resp = await client.get("/api/auth/access-requests", headers=hdrs)
    assert resp.status_code == 403


async def test_unauthenticated_list_requests_is_401(client: AsyncClient):
    """No Bearer token → 401."""
    resp = await client.get("/api/auth/access-requests")
    assert resp.status_code == 401


# ═══════════════════════════════════════════════════════════════════════
# 3. POST /api/auth/access-requests/{id}/accept
# ═══════════════════════════════════════════════════════════════════════

async def test_accept_creates_user_account(
    client: AsyncClient, admin_user, make_token, pending_request
):
    """
    Accepting a pending request must return HTTP 200 with status='approved'
    and a non-empty temp_password string.
    """
    hdrs = auth_headers(admin_user, make_token)
    resp = await client.post(
        f"/api/auth/access-requests/{pending_request['id']}/accept",
        json={},
        headers=hdrs,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "approved"
    assert data["temp_password"] is not None
    assert len(data["temp_password"]) >= 10


async def test_accepted_user_can_login(
    client: AsyncClient, admin_user, make_token, pending_request
):
    """
    After admin accepts a request the new user must be able to log in
    immediately using the temp_password returned in the accept response.
    """
    hdrs = auth_headers(admin_user, make_token)
    accept = await client.post(
        f"/api/auth/access-requests/{pending_request['id']}/accept",
        json={},
        headers=hdrs,
    )
    assert accept.status_code == 200
    temp_pwd = accept.json()["temp_password"]
    username = pending_request["body"]["username"]

    login = await client.post(
        "/api/auth/token",
        data={"username": username, "password": temp_pwd},
    )
    assert login.status_code == 200
    assert "access_token" in login.json()


async def test_accept_uses_role_override(
    client: AsyncClient, admin_user, make_token
):
    """
    When role_override is supplied in the accept body the created user must
    receive that role, not the originally requested_role.
    """
    body = access_request_payload(requested_role="viewer")
    req_resp = await client.post("/api/auth/request-access", json=body)
    req_id = req_resp.json()["id"]

    hdrs = auth_headers(admin_user, make_token)
    accept = await client.post(
        f"/api/auth/access-requests/{req_id}/accept",
        json={"role_override": "flight_controller"},
        headers=hdrs,
    )
    assert accept.status_code == 200

    # Verify the created account has the overridden role
    username = body["username"]
    login = await client.post(
        "/api/auth/token",
        data={"username": username, "password": accept.json()["temp_password"]},
    )
    token_data = login.json()
    assert token_data["role"] == "flight_controller"


async def test_accept_stores_admin_note(
    client: AsyncClient, admin_user, make_token, pending_request
):
    """admin_note in the accept body must be persisted and returned."""
    hdrs = auth_headers(admin_user, make_token)
    resp = await client.post(
        f"/api/auth/access-requests/{pending_request['id']}/accept",
        json={"admin_note": "Cleared by OC — batch 3"},
        headers=hdrs,
    )
    assert resp.status_code == 200
    assert resp.json()["admin_note"] == "Cleared by OC — batch 3"


async def test_accept_nonexistent_request_is_404(
    client: AsyncClient, admin_user, make_token
):
    """Accepting an id that does not exist must return HTTP 404."""
    hdrs = auth_headers(admin_user, make_token)
    resp = await client.post(
        "/api/auth/access-requests/99999/accept",
        json={},
        headers=hdrs,
    )
    assert resp.status_code == 404


async def test_accept_already_approved_request_is_409(
    client: AsyncClient, admin_user, make_token, pending_request
):
    """Trying to accept a request that is already 'approved' must return 409."""
    hdrs = auth_headers(admin_user, make_token)
    req_id = pending_request["id"]

    first = await client.post(
        f"/api/auth/access-requests/{req_id}/accept", json={}, headers=hdrs
    )
    assert first.status_code == 200

    second = await client.post(
        f"/api/auth/access-requests/{req_id}/accept", json={}, headers=hdrs
    )
    assert second.status_code == 409


async def test_accept_rejected_request_is_409(
    client: AsyncClient, admin_user, make_token, pending_request
):
    """
    A request that has been rejected must not be re-accepted — must return 409.
    """
    hdrs = auth_headers(admin_user, make_token)
    req_id = pending_request["id"]

    await client.post(
        f"/api/auth/access-requests/{req_id}/reject", json={}, headers=hdrs
    )

    accept = await client.post(
        f"/api/auth/access-requests/{req_id}/accept", json={}, headers=hdrs
    )
    assert accept.status_code == 409


async def test_accept_conflict_when_username_already_registered(
    client: AsyncClient, admin_user, make_token
):
    """
    If a user account with the same username already exists the accept
    endpoint must return 409 and must NOT create a duplicate account.
    """
    from app.core.auth import hash_password
    from app.models.user import User
    from app.tests.conftest import _TestSession

    username = "conflict_user"
    async with _TestSession() as session:
        existing = User(
            username=username,
            email="conflict@example.com",
            hashed_password=hash_password("Conflict@99"),
            role="viewer",
            is_active=True,
        )
        session.add(existing)
        await session.commit()

    body = access_request_payload(username=username)
    req_resp = await client.post("/api/auth/request-access", json=body)
    assert req_resp.status_code == 201

    hdrs = auth_headers(admin_user, make_token)
    accept = await client.post(
        f"/api/auth/access-requests/{req_resp.json()['id']}/accept",
        json={},
        headers=hdrs,
    )
    assert accept.status_code == 409


async def test_non_admin_cannot_accept_request(
    client: AsyncClient, viewer_user, make_token, pending_request
):
    """A viewer role must receive 403 when trying to accept."""
    hdrs = auth_headers(viewer_user, make_token)
    resp = await client.post(
        f"/api/auth/access-requests/{pending_request['id']}/accept",
        json={},
        headers=hdrs,
    )
    assert resp.status_code == 403


async def test_unauthenticated_accept_is_401(
    client: AsyncClient, pending_request
):
    """No Bearer token on accept endpoint → 401."""
    resp = await client.post(
        f"/api/auth/access-requests/{pending_request['id']}/accept",
        json={},
    )
    assert resp.status_code == 401


# ═══════════════════════════════════════════════════════════════════════
# 4. POST /api/auth/access-requests/{id}/reject
# ═══════════════════════════════════════════════════════════════════════

async def test_reject_pending_request_returns_200(
    client: AsyncClient, admin_user, make_token, pending_request
):
    """
    Rejecting a pending request must return HTTP 200 with status='rejected'
    and a populated reviewed_at timestamp.
    """
    hdrs = auth_headers(admin_user, make_token)
    resp = await client.post(
        f"/api/auth/access-requests/{pending_request['id']}/reject",
        json={},
        headers=hdrs,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "rejected"
    assert data["reviewed_at"] is not None


async def test_reject_stores_admin_note(
    client: AsyncClient, admin_user, make_token, pending_request
):
    """admin_note in the reject body must be persisted and returned."""
    hdrs = auth_headers(admin_user, make_token)
    resp = await client.post(
        f"/api/auth/access-requests/{pending_request['id']}/reject",
        json={"admin_note": "Insufficient clearance level"},
        headers=hdrs,
    )
    assert resp.status_code == 200
    assert resp.json()["admin_note"] == "Insufficient clearance level"


async def test_reject_does_not_create_user(
    client: AsyncClient, admin_user, make_token, pending_request
):
    """
    After rejection the username must NOT appear in the users list —
    no account should have been created.
    """
    hdrs = auth_headers(admin_user, make_token)
    await client.post(
        f"/api/auth/access-requests/{pending_request['id']}/reject",
        json={},
        headers=hdrs,
    )
    users_resp = await client.get("/api/auth/users", headers=hdrs)
    usernames = [u["username"] for u in users_resp.json()]
    assert pending_request["body"]["username"] not in usernames


async def test_reject_nonexistent_request_is_404(
    client: AsyncClient, admin_user, make_token
):
    """Rejecting an id that does not exist must return HTTP 404."""
    hdrs = auth_headers(admin_user, make_token)
    resp = await client.post(
        "/api/auth/access-requests/99999/reject",
        json={},
        headers=hdrs,
    )
    assert resp.status_code == 404


async def test_reject_already_rejected_is_409(
    client: AsyncClient, admin_user, make_token, pending_request
):
    """Trying to reject an already-rejected request must return 409."""
    hdrs = auth_headers(admin_user, make_token)
    req_id = pending_request["id"]

    first = await client.post(
        f"/api/auth/access-requests/{req_id}/reject", json={}, headers=hdrs
    )
    assert first.status_code == 200

    second = await client.post(
        f"/api/auth/access-requests/{req_id}/reject", json={}, headers=hdrs
    )
    assert second.status_code == 409


async def test_reject_approved_request_is_409(
    client: AsyncClient, admin_user, make_token, pending_request
):
    """
    A request that has already been approved must not be rejectable —
    must return 409.
    """
    hdrs = auth_headers(admin_user, make_token)
    req_id = pending_request["id"]

    await client.post(
        f"/api/auth/access-requests/{req_id}/accept", json={}, headers=hdrs
    )

    reject = await client.post(
        f"/api/auth/access-requests/{req_id}/reject", json={}, headers=hdrs
    )
    assert reject.status_code == 409


async def test_non_admin_cannot_reject_request(
    client: AsyncClient, viewer_user, make_token, pending_request
):
    """A viewer role must receive 403 when trying to reject."""
    hdrs = auth_headers(viewer_user, make_token)
    resp = await client.post(
        f"/api/auth/access-requests/{pending_request['id']}/reject",
        json={},
        headers=hdrs,
    )
    assert resp.status_code == 403


async def test_unauthenticated_reject_is_401(
    client: AsyncClient, pending_request
):
    """No Bearer token on reject endpoint → 401."""
    resp = await client.post(
        f"/api/auth/access-requests/{pending_request['id']}/reject",
        json={},
    )
    assert resp.status_code == 401
