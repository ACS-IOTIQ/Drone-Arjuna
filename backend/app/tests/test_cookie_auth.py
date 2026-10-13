"""
HttpOnly-cookie sessions for browsers (H-03):

  - login sets HttpOnly, SameSite=Strict cookies (refresh cookie scoped to /api/auth)
  - cookie-authenticated GET works; unsafe methods need the X-Requested-With header (CSRF)
  - /refresh and /logout work from the cookie alone; logout clears cookies and revokes
  - Authorization: Bearer keeps working for API clients
"""
from httpx import AsyncClient

CSRF = {"X-Requested-With": "DroneArjuna"}
LOGIN = {"username": "admin_test", "password": "Admin@1234"}


async def _login(client: AsyncClient):
    resp = await client.post("/api/auth/token", data=LOGIN)
    assert resp.status_code == 200
    return resp


async def test_login_sets_httponly_strict_cookies(client: AsyncClient, admin_user):
    resp = await _login(client)
    cookies = resp.headers.get_list("set-cookie")
    access = next(c for c in cookies if c.startswith("da_access="))
    refresh = next(c for c in cookies if c.startswith("da_refresh="))
    for c in (access, refresh):
        assert "HttpOnly" in c
        assert "SameSite=strict" in c or "samesite=strict" in c.lower()
    assert "Path=/api/auth" in refresh
    assert "Path=/;" in access or access.rstrip().endswith("Path=/")


async def test_cookie_authenticates_get_without_authorization_header(client: AsyncClient, admin_user):
    await _login(client)
    resp = await client.get("/api/auth/me")
    assert resp.status_code == 200
    assert resp.json()["username"] == "admin_test"


async def test_cookie_unsafe_request_without_csrf_header_is_403(client: AsyncClient, admin_user):
    await _login(client)
    resp = await client.post("/api/auth/ws-ticket")
    assert resp.status_code == 403
    resp = await client.post("/api/auth/ws-ticket", headers=CSRF)
    assert resp.status_code == 200
    assert "ticket" in resp.json()


async def test_no_credentials_is_401(client: AsyncClient):
    assert (await client.get("/api/auth/me")).status_code == 401
    assert (await client.post("/api/auth/ws-ticket", headers=CSRF)).status_code == 401


async def test_bearer_still_works_without_csrf_header(client: AsyncClient, admin_user):
    token = (await _login(client)).json()["access_token"]
    client.cookies.clear()
    resp = await client.post("/api/auth/ws-ticket", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200


async def test_refresh_from_cookie_issues_new_access_cookie(client: AsyncClient, admin_user):
    await _login(client)
    client.cookies.delete("da_access")
    resp = await client.post("/api/auth/refresh", headers=CSRF)
    assert resp.status_code == 200
    assert any(c.startswith("da_access=") for c in resp.headers.get_list("set-cookie"))
    assert (await client.get("/api/auth/me")).status_code == 200


async def test_refresh_from_cookie_requires_csrf_header(client: AsyncClient, admin_user):
    await _login(client)
    resp = await client.post("/api/auth/refresh")
    assert resp.status_code == 403


async def test_logout_clears_cookies_and_revokes_tokens(client: AsyncClient, admin_user):
    login = await _login(client)
    access = login.json()["access_token"]
    resp = await client.post("/api/auth/logout", headers=CSRF)
    assert resp.status_code == 200
    cleared = " ".join(resp.headers.get_list("set-cookie")).lower()
    assert "da_access=" in cleared and "da_refresh=" in cleared and "max-age=0" in cleared
    # The old access token is revoked even if someone kept a copy of it.
    client.cookies.clear()
    stale = await client.get("/api/auth/me", headers={"Authorization": f"Bearer {access}"})
    assert stale.status_code == 401
