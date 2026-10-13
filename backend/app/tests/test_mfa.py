"""
TOTP multi-factor authentication (H-02).

  - algorithm checked against the RFC 6238 test vectors
  - replay / drift / bad-input handling
  - enrolment, login challenge, recovery codes, disable, admin reset
  - the MFA lockout is separate from the password lockout
"""
import base64
import json
import time

import pytest
from httpx import AsyncClient

from app.core import totp
from app.tests.helpers import auth_headers

# RFC 6238 appendix B secret ("12345678901234567890"), SHA-1
RFC_SECRET = base64.b32encode(b"12345678901234567890").decode().rstrip("=")
LOGIN = {"username": "admin_test", "password": "Admin@1234"}


# ── algorithm ────────────────────────────────────────────────────────

@pytest.mark.parametrize("t,expected", [
    (59, "287082"),
    (1111111109, "081804"),
    (1111111111, "050471"),
    (1234567890, "005924"),
    (2000000000, "279037"),
    (20000000000, "353130"),
])
def test_rfc6238_vectors(t, expected):
    assert totp.code_at(RFC_SECRET, t) == expected


def test_verify_accepts_current_and_adjacent_steps_only():
    now = 1_700_000_000
    secret = totp.generate_secret()
    assert totp.verify_totp(secret, totp.code_at(secret, now), now=now) is not None
    assert totp.verify_totp(secret, totp.code_at(secret, now - 30), now=now) is not None   # 1 step late
    assert totp.verify_totp(secret, totp.code_at(secret, now + 30), now=now) is not None   # 1 step early
    assert totp.verify_totp(secret, totp.code_at(secret, now - 90), now=now) is None       # too old
    assert totp.verify_totp(secret, totp.code_at(secret, now + 90), now=now) is None


def test_replay_of_same_step_is_refused():
    now = 1_700_000_000
    secret = totp.generate_secret()
    code = totp.code_at(secret, now)
    step = totp.verify_totp(secret, code, now=now)
    assert step is not None
    assert totp.verify_totp(secret, code, now=now, last_step=step) is None


@pytest.mark.parametrize("bad", ["", "12345", "1234567", "abcdef", "12 34 5", None])
def test_malformed_codes_are_rejected(bad):
    assert totp.verify_totp(totp.generate_secret(), bad) is None


def test_spaces_in_code_are_tolerated():
    now = 1_700_000_000
    secret = totp.generate_secret()
    c = totp.code_at(secret, now)
    assert totp.verify_totp(secret, f"{c[:3]} {c[3:]}", now=now) is not None


def test_secret_encryption_roundtrip_and_ciphertext_differs():
    s = totp.generate_secret()
    enc = totp.encrypt_secret(s)
    assert s not in enc
    assert totp.decrypt_secret(enc) == s


def test_recovery_codes_single_use_and_hashed():
    codes = totp.generate_recovery_codes()
    assert len(codes) == 10 and len(set(codes)) == 10
    hashes = [totp.hash_recovery_code(c) for c in codes]
    assert codes[0] not in hashes
    remaining = totp.consume_recovery_code(codes[0].upper(), hashes)     # case-insensitive
    assert remaining is not None and len(remaining) == 9
    assert totp.consume_recovery_code(codes[0], remaining) is None        # already used
    assert totp.consume_recovery_code("nope-nope", hashes) is None


def test_provisioning_uri_format():
    uri = totp.provisioning_uri("ABC234", "admin_test")
    assert uri.startswith("otpauth://totp/DroneArjuna%3Aadmin_test?secret=ABC234")
    assert "issuer=DroneArjuna" in uri and "digits=6" in uri and "period=30" in uri


# ── API flow ─────────────────────────────────────────────────────────

async def _enrol(client: AsyncClient, admin_user, make_token):
    hdrs = auth_headers(admin_user, make_token)
    setup = await client.post("/api/auth/mfa/setup", headers=hdrs)
    assert setup.status_code == 200
    secret = setup.json()["secret"]
    enable = await client.post("/api/auth/mfa/enable", json={"code": totp.code_at(secret)}, headers=hdrs)
    assert enable.status_code == 200, enable.text
    return secret, enable.json()["recovery_codes"], hdrs


async def test_enrol_enable_returns_recovery_codes_and_secret_is_encrypted(
    client: AsyncClient, admin_user, make_token,
):
    secret, codes, hdrs = await _enrol(client, admin_user, make_token)
    assert len(codes) == 10
    me = (await client.get("/api/auth/me", headers=hdrs)).json()
    assert me["totp_enabled"] is True
    assert "totp_secret_enc" not in me and "recovery_codes" not in me


async def test_enable_with_wrong_code_fails(client: AsyncClient, admin_user, make_token):
    hdrs = auth_headers(admin_user, make_token)
    await client.post("/api/auth/mfa/setup", headers=hdrs)
    r = await client.post("/api/auth/mfa/enable", json={"code": "000000"}, headers=hdrs)
    assert r.status_code == 400
    assert (await client.get("/api/auth/me", headers=hdrs)).json()["totp_enabled"] is False


async def test_enable_without_setup_is_400_and_double_setup_is_409(
    client: AsyncClient, admin_user, make_token,
):
    hdrs = auth_headers(admin_user, make_token)
    assert (await client.post("/api/auth/mfa/enable", json={"code": "123456"}, headers=hdrs)).status_code == 400
    await _enrol(client, admin_user, make_token)
    assert (await client.post("/api/auth/mfa/setup", headers=hdrs)).status_code == 409


async def test_login_without_mfa_is_unchanged(client: AsyncClient, admin_user):
    r = await client.post("/api/auth/token", data=LOGIN)
    assert r.status_code == 200
    assert "access_token" in r.json() and "mfa_required" not in r.json()


async def test_login_with_mfa_returns_challenge_and_no_session(
    client: AsyncClient, admin_user, make_token,
):
    await _enrol(client, admin_user, make_token)
    client.cookies.clear()
    r = await client.post("/api/auth/token", data=LOGIN)
    assert r.status_code == 200
    body = r.json()
    assert body["mfa_required"] is True and "mfa_token" in body
    assert "access_token" not in body
    assert not r.headers.get_list("set-cookie")                          # no session cookies yet
    assert (await client.get("/api/auth/me")).status_code == 401


async def test_mfa_verify_with_totp_creates_session(client: AsyncClient, admin_user, make_token):
    secret, _, _ = await _enrol(client, admin_user, make_token)
    client.cookies.clear()
    challenge = (await client.post("/api/auth/token", data=LOGIN)).json()
    # enrolment consumed this step; use the next step's code (within allowed drift)
    code = totp.code_at(secret, time.time() + totp.STEP_SECONDS)
    r = await client.post("/api/auth/mfa/verify",
                          json={"mfa_token": challenge["mfa_token"], "code": code})
    assert r.status_code == 200, r.text
    assert "access_token" in r.json()
    assert any(c.startswith("da_access=") for c in r.headers.get_list("set-cookie"))
    assert (await client.get("/api/auth/me")).status_code == 200


async def test_mfa_token_is_single_use(client: AsyncClient, admin_user, make_token):
    secret, codes, _ = await _enrol(client, admin_user, make_token)
    client.cookies.clear()
    challenge = (await client.post("/api/auth/token", data=LOGIN)).json()
    ok = await client.post("/api/auth/mfa/verify",
                           json={"mfa_token": challenge["mfa_token"], "code": codes[0]})
    assert ok.status_code == 200
    again = await client.post("/api/auth/mfa/verify",
                              json={"mfa_token": challenge["mfa_token"], "code": codes[1]})
    assert again.status_code == 401


async def test_wrong_code_is_401_and_recovery_code_works_once(
    client: AsyncClient, admin_user, make_token,
):
    _, codes, _ = await _enrol(client, admin_user, make_token)
    client.cookies.clear()
    ch = (await client.post("/api/auth/token", data=LOGIN)).json()
    bad = await client.post("/api/auth/mfa/verify", json={"mfa_token": ch["mfa_token"], "code": "000000"})
    assert bad.status_code == 401
    good = await client.post("/api/auth/mfa/verify", json={"mfa_token": ch["mfa_token"], "code": codes[3]})
    assert good.status_code == 200
    # the same recovery code cannot be reused on a later login
    client.cookies.clear()
    ch2 = (await client.post("/api/auth/token", data=LOGIN)).json()
    reuse = await client.post("/api/auth/mfa/verify", json={"mfa_token": ch2["mfa_token"], "code": codes[3]})
    assert reuse.status_code == 401


async def test_access_token_is_not_accepted_as_mfa_token(client: AsyncClient, admin_user, make_token):
    await _enrol(client, admin_user, make_token)
    access = make_token(admin_user.id, admin_user.role)
    r = await client.post("/api/auth/mfa/verify", json={"mfa_token": access, "code": "123456"})
    assert r.status_code == 401


async def test_replayed_totp_code_is_rejected(client: AsyncClient, admin_user, make_token):
    secret, _, _ = await _enrol(client, admin_user, make_token)
    client.cookies.clear()
    ch = (await client.post("/api/auth/token", data=LOGIN)).json()
    code = totp.code_at(secret, time.time() + totp.STEP_SECONDS)
    assert (await client.post("/api/auth/mfa/verify", json={"mfa_token": ch["mfa_token"], "code": code})).status_code == 200
    client.cookies.clear()
    ch2 = (await client.post("/api/auth/token", data=LOGIN)).json()
    replay = await client.post("/api/auth/mfa/verify", json={"mfa_token": ch2["mfa_token"], "code": code})
    assert replay.status_code == 401


async def test_disable_requires_password_and_code(client: AsyncClient, admin_user, make_token):
    secret, codes, hdrs = await _enrol(client, admin_user, make_token)
    wrong_pw = await client.post("/api/auth/mfa/disable",
                                 json={"password": "nope", "code": codes[0]}, headers=hdrs)
    assert wrong_pw.status_code == 403
    wrong_code = await client.post("/api/auth/mfa/disable",
                                   json={"password": "Admin@1234", "code": "000000"}, headers=hdrs)
    assert wrong_code.status_code == 403
    ok = await client.post("/api/auth/mfa/disable",
                           json={"password": "Admin@1234", "code": codes[0]}, headers=hdrs)
    assert ok.status_code == 200
    r = await client.post("/api/auth/token", data=LOGIN)
    assert "access_token" in r.json()                                    # back to password-only


async def test_regenerate_recovery_codes_invalidates_old_ones(client: AsyncClient, admin_user, make_token):
    secret, codes, hdrs = await _enrol(client, admin_user, make_token)
    r = await client.post("/api/auth/mfa/recovery-codes", json={"code": codes[0]}, headers=hdrs)
    assert r.status_code == 200
    new_codes = r.json()["recovery_codes"]
    assert set(new_codes).isdisjoint(codes)
    client.cookies.clear()
    ch = (await client.post("/api/auth/token", data=LOGIN)).json()
    old = await client.post("/api/auth/mfa/verify", json={"mfa_token": ch["mfa_token"], "code": codes[1]})
    assert old.status_code == 401


async def test_admin_can_reset_another_users_mfa_but_viewer_cannot(
    client: AsyncClient, admin_user, viewer_user, make_token,
):
    # enrol the viewer
    vh = auth_headers(viewer_user, make_token)
    secret = (await client.post("/api/auth/mfa/setup", headers=vh)).json()["secret"]
    await client.post("/api/auth/mfa/enable", json={"code": totp.code_at(secret)}, headers=vh)
    assert (await client.get("/api/auth/me", headers=vh)).json()["totp_enabled"] is True

    denied = await client.post(f"/api/auth/users/{viewer_user.id}/mfa/reset", headers=vh)
    assert denied.status_code == 403
    ah = auth_headers(admin_user, make_token)
    ok = await client.post(f"/api/auth/users/{viewer_user.id}/mfa/reset", headers=ah)
    assert ok.status_code == 200
    # the reset also revoked the viewer's sessions, so read the state as the admin
    users = (await client.get("/api/auth/users", headers=ah)).json()
    assert next(u for u in users if u["id"] == viewer_user.id)["totp_enabled"] is False
    # and the revoked viewer token no longer works
    assert (await client.get("/api/auth/me", headers=vh)).status_code == 401


async def test_enrollment_required_flag_for_configured_roles(
    client: AsyncClient, admin_user, monkeypatch,
):
    from app.core import auth as auth_mod
    monkeypatch.setattr(auth_mod.cfg, "mfa_required_roles_str", "admin")
    r = await client.post("/api/auth/token", data=LOGIN)
    assert r.json()["mfa_enrollment_required"] is True


async def test_mfa_verify_has_its_own_lockout(client: AsyncClient, admin_user, make_token, monkeypatch):
    from app.core import security
    monkeypatch.setattr(security.cfg, "login_max_failures", 3)
    await _enrol(client, admin_user, make_token)
    client.cookies.clear()
    ch = (await client.post("/api/auth/token", data=LOGIN)).json()
    codes = []
    for _ in range(3):
        codes.append((await client.post("/api/auth/mfa/verify",
                                        json={"mfa_token": ch["mfa_token"], "code": "000000"})).status_code)
    assert codes == [401, 401, 401]
    locked = await client.post("/api/auth/mfa/verify",
                               json={"mfa_token": ch["mfa_token"], "code": "000000"})
    assert locked.status_code == 429
    # and logging in again with the password does NOT reset the MFA counter
    ch2 = (await client.post("/api/auth/token", data=LOGIN)).json()
    still = await client.post("/api/auth/mfa/verify",
                              json={"mfa_token": ch2["mfa_token"], "code": "000000"})
    assert still.status_code == 429
