"""
M-07: backup integrity.

  - every dump is HMAC-signed; any modification is rejected
  - a different signing key (attacker re-signing without SECRET_KEY) is rejected
  - optional encryption at rest (Fernet) hides content and is authenticated
  - a tampered dump is skipped during restore, never inserted
  - automatic restore can be switched to operator-confirmed (admin endpoint)
"""
import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest
from cryptography.fernet import Fernet
from httpx import AsyncClient

from app.core import backup
from app.core.backup import BackupIntegrityError
from app.tests.helpers import auth_headers

DATA = {"users": [{"id": 1, "username": "admin", "created": datetime(2026, 10, 1, tzinfo=timezone.utc)}],
        "missions": []}


# ── signing ──────────────────────────────────────────────────────────

def test_signed_roundtrip_returns_original_data():
    out = backup._unpack_dump(backup._pack_dump(DATA))
    assert out["users"][0]["username"] == "admin"
    assert "__sig__" not in out


def test_modified_value_is_rejected():
    obj = json.loads(backup._pack_dump(DATA))
    obj["users"][0]["username"] = "attacker"
    with pytest.raises(BackupIntegrityError, match="signature mismatch"):
        backup._unpack_dump(json.dumps(obj))


def test_injected_row_is_rejected():
    obj = json.loads(backup._pack_dump(DATA))
    obj["users"].append({"id": 2, "username": "backdoor", "role": "admin"})
    with pytest.raises(BackupIntegrityError):
        backup._unpack_dump(json.dumps(obj))


def test_resigned_with_other_key_is_rejected(monkeypatch):
    packed = backup._pack_dump(DATA)
    monkeypatch.setattr(backup.cfg, "backup_signing_key", "z" * 40)
    with pytest.raises(BackupIntegrityError):
        backup._unpack_dump(packed)


def test_signature_does_not_depend_on_key_order():
    a = backup._pack_dump({"a": [{"x": 1, "y": 2}], "b": []})
    reordered = json.loads(a)
    reordered = {"b": reordered["b"], "a": [{"y": 2, "x": 1}], "__sig__": reordered["__sig__"]}
    assert backup._unpack_dump(json.dumps(reordered))["a"] == [{"x": 1, "y": 2}]


def test_unsigned_legacy_dump_accepted_by_default_but_rejected_when_required(monkeypatch):
    legacy = json.dumps({"users": [{"id": 1}]})
    assert backup._unpack_dump(legacy) == {"users": [{"id": 1}]}
    monkeypatch.setattr(backup.cfg, "backup_require_signature", True)
    with pytest.raises(BackupIntegrityError, match="unsigned"):
        backup._unpack_dump(legacy)


def test_invalid_json_is_an_integrity_error():
    with pytest.raises(BackupIntegrityError):
        backup._unpack_dump("{not json")


# ── encryption ───────────────────────────────────────────────────────

@pytest.fixture
def enc_key(monkeypatch):
    key = Fernet.generate_key().decode()
    monkeypatch.setattr(backup.cfg, "backup_encryption_key", key)
    return key


def test_encrypted_dump_hides_content_and_roundtrips(enc_key):
    packed = backup._pack_dump(DATA)
    assert "admin" not in packed and "users" not in packed
    assert backup._unpack_dump(packed)["users"][0]["username"] == "admin"


def test_encrypted_dump_with_wrong_key_fails(enc_key, monkeypatch):
    packed = backup._pack_dump(DATA)
    monkeypatch.setattr(backup.cfg, "backup_encryption_key", Fernet.generate_key().decode())
    with pytest.raises(BackupIntegrityError, match="decryption"):
        backup._unpack_dump(packed)


def test_encrypted_dump_without_key_fails(enc_key, monkeypatch):
    packed = backup._pack_dump(DATA)
    monkeypatch.setattr(backup.cfg, "backup_encryption_key", "")
    with pytest.raises(BackupIntegrityError, match="not set"):
        backup._unpack_dump(packed)


def test_encrypted_dump_tampering_is_detected(enc_key):
    packed = backup._pack_dump(DATA)
    flipped = packed[:-6] + ("AAAAAA" if not packed.endswith("AAAAAA") else "BBBBBB")
    with pytest.raises(BackupIntegrityError):
        backup._unpack_dump(flipped)


# ── restore skips tampered dumps ─────────────────────────────────────

def test_tampered_dump_is_skipped_valid_one_is_used(tmp_path):
    good = tmp_path / "dump_20260101T000000Z.json"
    bad = tmp_path / "dump_20260102T000000Z.json"
    good.write_text(backup._pack_dump({"users": [{"id": 1}]}))
    obj = json.loads(backup._pack_dump({"users": [{"id": 1}]}))
    obj["users"][0]["id"] = 999
    bad.write_text(json.dumps(obj))
    loaded = backup._read_dumps_skipping_invalid([(bad, bad.name), (good, good.name)])
    assert [n for n, _ in loaded] == [good.name]


async def test_restore_with_only_tampered_dumps_restores_nothing(tmp_path, monkeypatch):
    bad = tmp_path / "dump_20260102T000000Z.json"
    obj = json.loads(backup._pack_dump({"users": [{"id": 1}]}))
    obj["users"][0]["id"] = 999
    bad.write_text(json.dumps(obj))
    monkeypatch.setattr(backup, "_fetch_recent_dumps", lambda t, n: [(bad, bad.name)])
    bc = AsyncMock()
    monkeypatch.setattr(backup, "broadcast_system_event", bc)
    target = backup.DumpTarget(name="main", metadata=None, session_factory=None,
                               backup_dir=tmp_path, minio_bucket="b")
    assert await backup.restore_latest_dump(target) is False
    assert bc.await_args.args[0] == "BACKUP_MISSING"


# ── automatic restore gating ─────────────────────────────────────────

async def test_automatic_restore_held_back_when_disabled(tmp_path, monkeypatch):
    monkeypatch.setattr(backup.cfg, "backup_auto_restore", False)
    fetch = lambda *a, **k: pytest.fail("must not read dumps when restore is held back")  # noqa: E731
    monkeypatch.setattr(backup, "_fetch_recent_dumps", fetch)
    bc = AsyncMock()
    monkeypatch.setattr(backup, "broadcast_system_event", bc)
    target = backup.DumpTarget(name="main", metadata=None, session_factory=None,
                               backup_dir=tmp_path, minio_bucket="b")
    assert await backup.restore_latest_dump(target, automatic=True) is False
    assert bc.await_args.args[0] == "RESTORE_REQUIRED"


# ── operator-confirmed restore endpoint ──────────────────────────────

async def test_restore_endpoint_requires_admin(client: AsyncClient, flight_controller_user, make_token):
    r = await client.post("/api/system/backup/restore", json={"confirm": True},
                          headers=auth_headers(flight_controller_user, make_token))
    assert r.status_code == 403


async def test_restore_endpoint_unauthenticated_401(client: AsyncClient):
    assert (await client.post("/api/system/backup/restore", json={"confirm": True})).status_code == 401


async def test_restore_endpoint_needs_explicit_confirmation(client: AsyncClient, admin_user, make_token):
    r = await client.post("/api/system/backup/restore", json={"confirm": False},
                          headers=auth_headers(admin_user, make_token))
    assert r.status_code == 400


async def test_restore_endpoint_runs_operator_restore(client: AsyncClient, admin_user, make_token, monkeypatch):
    restore = AsyncMock(return_value=True)
    monkeypatch.setattr(backup, "restore_latest_dump", restore)
    r = await client.post("/api/system/backup/restore", json={"confirm": True, "database": "main"},
                          headers=auth_headers(admin_user, make_token))
    assert r.status_code == 200
    assert r.json()["restored"] == {"main": True}
    restore.assert_awaited_once()
    assert restore.await_args.kwargs.get("automatic", False) is False


async def test_restore_endpoint_rejects_unknown_database(client: AsyncClient, admin_user, make_token):
    r = await client.post("/api/system/backup/restore", json={"confirm": True, "database": "users"},
                          headers=auth_headers(admin_user, make_token))
    assert r.status_code == 422
