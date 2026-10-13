"""
Backup list endpoint tests
==========================
GET /api/system/backup/list   (feeds Settings -> Backups)

(Restore is covered in test_backup_integrity.py; dump creation / rotation in
test_backup.py.)

Covers:
  - _list_dumps: reads MinIO newest-first with name/size/modified/source fields,
    falls back to local disk when MinIO is unreachable, ignores non-dump files,
    empty bucket / empty directory
  - endpoint: one list per backed-up database (main + telemetry), shape of each entry
  - endpoint keeps working when MinIO is down (local fallback) and when a database has
    no dumps at all
  - RBAC: admin only (viewer / flight_controller / mission_commander -> 403),
    unauthenticated -> 401
"""
import os
from datetime import datetime, timezone

import pytest
from httpx import AsyncClient

from app.core import backup, backup_router
from app.tests.test_backup import _fake_target


def _auth(user, make_token) -> dict:
    return {"Authorization": f"Bearer {make_token(user.id, user.role)}"}


class _FakeMinio:
    """list_objects_v2 stand-in returning the configured objects (or failing)."""

    def __init__(self, objects=None, fail=False):
        self.objects = objects or []
        self.fail = fail
        self.listed_buckets = []

    def list_objects_v2(self, Bucket):
        self.listed_buckets.append(Bucket)
        if self.fail:
            raise RuntimeError("MinIO unreachable")
        return {"Contents": self.objects} if self.objects else {}


def _obj(key, size, when):
    return {"Key": key, "Size": size, "LastModified": when}


T1 = datetime(2026, 10, 1, 8, 0, 0, tzinfo=timezone.utc)
T2 = datetime(2026, 10, 2, 8, 0, 0, tzinfo=timezone.utc)
T3 = datetime(2026, 10, 3, 8, 0, 0, tzinfo=timezone.utc)


@pytest.fixture
def minio(monkeypatch):
    """Install a fake MinIO; tests set `.objects` / `.fail` on the returned client."""
    client = _FakeMinio()
    monkeypatch.setattr(backup, "_minio_client", lambda: client)
    monkeypatch.setattr(backup, "_ensure_bucket", lambda c, bucket: None)
    return client


def _touch(path, size=10, mtime=None):
    path.write_text("x" * size)
    if mtime is not None:
        os.utime(path, (mtime, mtime))


# ══════════════════════════════════════════════════════════════════════
# _list_dumps
# ══════════════════════════════════════════════════════════════════════

def test_list_dumps_from_minio_is_newest_first_with_all_fields(tmp_path, minio):
    minio.objects = [
        _obj("dump_20261001T080000Z.json", 111, T1),
        _obj("dump_20261003T080000Z.json", 333, T3),
        _obj("dump_20261002T080000Z.json", 222, T2),
    ]
    target = _fake_target(tmp_path)

    items = backup_router._list_dumps(target)

    assert [i["name"] for i in items] == [
        "dump_20261003T080000Z.json",
        "dump_20261002T080000Z.json",
        "dump_20261001T080000Z.json",
    ]
    assert items[0] == {
        "name": "dump_20261003T080000Z.json",
        "size": 333,
        "modified": T3.isoformat(),
        "source": "minio",
    }
    assert minio.listed_buckets == [target.minio_bucket]        # asked the right bucket


def test_list_dumps_ordering_follows_the_timestamp_in_the_name(tmp_path, minio):
    """Newest-first is by name (UTC stamp), not by upload order."""
    minio.objects = [
        _obj("dump_20260101T000000Z.json", 1, T3),               # newest upload, oldest stamp
        _obj("dump_20261231T000000Z.json", 1, T1),
    ]
    items = backup_router._list_dumps(_fake_target(tmp_path))
    assert items[0]["name"] == "dump_20261231T000000Z.json"


def test_list_dumps_empty_bucket(tmp_path, minio):
    minio.objects = []
    assert backup_router._list_dumps(_fake_target(tmp_path)) == []


def test_list_dumps_falls_back_to_local_disk_when_minio_is_down(tmp_path, minio):
    minio.fail = True
    target = _fake_target(tmp_path)
    target.backup_dir.mkdir(parents=True)
    _touch(target.backup_dir / "dump_20261001T080000Z.json", size=40, mtime=T1.timestamp())
    _touch(target.backup_dir / "dump_20261002T080000Z.json", size=80, mtime=T2.timestamp())

    items = backup_router._list_dumps(target)

    assert [i["name"] for i in items] == [
        "dump_20261002T080000Z.json",
        "dump_20261001T080000Z.json",
    ]
    assert all(i["source"] == "local" for i in items)
    assert items[0]["size"] == 80
    assert items[0]["modified"] == T2.isoformat()


def test_list_dumps_local_fallback_ignores_files_that_are_not_dumps(tmp_path, minio):
    minio.fail = True
    target = _fake_target(tmp_path)
    target.backup_dir.mkdir(parents=True)
    _touch(target.backup_dir / "dump_20261001T080000Z.json")
    _touch(target.backup_dir / "sql_fallback_applied.json")      # marker written by the SQL fallback
    _touch(target.backup_dir / "notes.txt")
    _touch(target.backup_dir / "dump_20261001T080000Z.json.tmp")

    names = [i["name"] for i in backup_router._list_dumps(target)]
    assert names == ["dump_20261001T080000Z.json"]


def test_list_dumps_minio_down_and_no_local_dumps_is_empty(tmp_path, minio):
    minio.fail = True
    target = _fake_target(tmp_path)
    target.backup_dir.mkdir(parents=True)
    assert backup_router._list_dumps(target) == []


def test_list_dumps_minio_down_and_directory_missing_is_empty(tmp_path, minio):
    """A fresh install has no backup folder yet — listing must not raise."""
    minio.fail = True
    target = _fake_target(tmp_path)                              # backup_dir never created
    assert backup_router._list_dumps(target) == []


# ══════════════════════════════════════════════════════════════════════
# GET /api/system/backup/list
# ══════════════════════════════════════════════════════════════════════

@pytest.fixture
def two_targets(tmp_path, monkeypatch, minio):
    main = _fake_target(tmp_path, name="main")
    tele = _fake_target(tmp_path, name="telemetry")
    monkeypatch.setattr(backup, "ALL_TARGETS", (main, tele))
    return main, tele


async def test_list_returns_one_list_per_database(
    client: AsyncClient, admin_user, make_token, two_targets, minio
):
    minio.objects = [
        _obj("dump_20261002T080000Z.json", 222, T2),
        _obj("dump_20261001T080000Z.json", 111, T1),
    ]
    r = await client.get("/api/system/backup/list", headers=_auth(admin_user, make_token))
    assert r.status_code == 200, r.text
    body = r.json()
    assert set(body) == {"main", "telemetry"}
    for dumps in body.values():
        assert [d["name"] for d in dumps] == [
            "dump_20261002T080000Z.json",
            "dump_20261001T080000Z.json",
        ]


async def test_list_entries_have_the_fields_the_ui_renders(
    client: AsyncClient, admin_user, make_token, two_targets, minio
):
    minio.objects = [_obj("dump_20261001T080000Z.json", 2048, T1)]
    r = await client.get("/api/system/backup/list", headers=_auth(admin_user, make_token))
    entry = r.json()["main"][0]
    assert set(entry) == {"name", "size", "modified", "source"}   # BackupManager.tsx `Dump`
    assert entry["size"] == 2048
    assert entry["source"] == "minio"
    datetime.fromisoformat(entry["modified"])                      # parseable by `new Date()`


async def test_list_queries_each_databases_own_bucket(
    client: AsyncClient, admin_user, make_token, two_targets, minio
):
    main, tele = two_targets
    await client.get("/api/system/backup/list", headers=_auth(admin_user, make_token))
    assert sorted(minio.listed_buckets) == sorted([main.minio_bucket, tele.minio_bucket])


async def test_list_database_without_dumps_is_an_empty_list(
    client: AsyncClient, admin_user, make_token, two_targets, minio
):
    r = await client.get("/api/system/backup/list", headers=_auth(admin_user, make_token))
    assert r.status_code == 200
    assert r.json() == {"main": [], "telemetry": []}


async def test_list_works_from_local_disk_when_minio_is_down(
    client: AsyncClient, admin_user, make_token, two_targets, minio
):
    main, tele = two_targets
    minio.fail = True
    main.backup_dir.mkdir(parents=True)
    _touch(main.backup_dir / "dump_20261001T080000Z.json", size=64, mtime=T1.timestamp())

    r = await client.get("/api/system/backup/list", headers=_auth(admin_user, make_token))

    assert r.status_code == 200, r.text
    body = r.json()
    assert [d["source"] for d in body["main"]] == ["local"]
    assert body["telemetry"] == []                                 # no folder, still no error


async def test_list_includes_the_real_targets_by_default(
    client: AsyncClient, admin_user, make_token, minio
):
    """Without patching ALL_TARGETS the endpoint reports exactly the backed-up databases."""
    r = await client.get("/api/system/backup/list", headers=_auth(admin_user, make_token))
    assert r.status_code == 200
    assert set(r.json()) == {t.name for t in backup.ALL_TARGETS} == {"main", "telemetry"}


async def test_list_forbidden_for_viewer(client: AsyncClient, viewer_user, make_token):
    r = await client.get("/api/system/backup/list", headers=_auth(viewer_user, make_token))
    assert r.status_code == 403


async def test_list_forbidden_for_flight_controller(
    client: AsyncClient, flight_controller_user, make_token
):
    r = await client.get("/api/system/backup/list", headers=_auth(flight_controller_user, make_token))
    assert r.status_code == 403


async def test_list_forbidden_for_mission_commander(
    client: AsyncClient, mission_commander_user, make_token
):
    r = await client.get("/api/system/backup/list", headers=_auth(mission_commander_user, make_token))
    assert r.status_code == 403


async def test_list_unauthenticated_401(client: AsyncClient):
    assert (await client.get("/api/system/backup/list")).status_code == 401


async def test_list_rejects_non_get_methods(client: AsyncClient, admin_user, make_token):
    for method in ("post", "put", "delete"):
        r = await getattr(client, method)(
            "/api/system/backup/list", headers=_auth(admin_user, make_token)
        )
        assert r.status_code == 405
