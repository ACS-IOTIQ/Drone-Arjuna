"""
Tamper-evident audit trail (M-03):

  - hash chain: intact chain verifies; edit / delete / reorder is detected
  - middleware records every state-changing /api call (who, route, status) and
    nothing for reads or already-audited auth plumbing
  - the command endpoint writes an explicit command_sent event
"""
import copy
import json
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient

from app.core import audit_middleware
from app.core.security import (
    AUDIT_GENESIS, audit_canonical, audit_row_hash, verify_audit_chain,
)
from app.tests.helpers import auth_headers


def _chain(n=4):
    rows, prev = [], AUDIT_GENESIS
    base = datetime(2026, 10, 1, 12, 0, 0, tzinfo=timezone.utc)
    for i in range(1, n + 1):
        detail = {"command": "arm", "result": "accepted", "n": i}
        row = {"id": i, "timestamp": base + timedelta(seconds=i), "category": "command",
               "action": "command_sent", "user_id": 7, "drone_id": 3, "mission_id": None,
               "ip_address": "10.0.0.5", "detail": detail, "severity": "INFO", "prev_hash": prev}
        canon = audit_canonical(row["timestamp"], row["category"], row["action"], 7, 3, None,
                                "10.0.0.5", json.dumps(detail), "INFO")
        row["row_hash"] = audit_row_hash(prev, canon)
        prev = row["row_hash"]
        rows.append(row)
    return rows


# ── hash chain ───────────────────────────────────────────────────────

def test_intact_chain_verifies():
    assert verify_audit_chain(_chain()) is None


def test_modified_row_is_detected():
    rows = _chain()
    rows[1]["detail"]["result"] = "rejected"
    assert verify_audit_chain(rows) == 2


def test_modified_user_is_detected():
    rows = _chain()
    rows[2]["user_id"] = 1
    assert verify_audit_chain(rows) == 3


def test_deleted_row_is_detected():
    rows = _chain()
    del rows[1]
    assert verify_audit_chain(rows) == 3     # row 3's prev_hash no longer matches row 1


def test_reordered_rows_are_detected():
    rows = _chain()
    rows[1], rows[2] = rows[2], rows[1]
    assert verify_audit_chain(rows) is not None


def test_recomputing_one_hash_still_breaks_the_next_link():
    rows = _chain()
    rows[1] = copy.deepcopy(rows[1])
    rows[1]["detail"]["result"] = "rejected"
    canon = audit_canonical(rows[1]["timestamp"], "command", "command_sent", 7, 3, None,
                            "10.0.0.5", json.dumps(rows[1]["detail"]), "INFO")
    rows[1]["row_hash"] = audit_row_hash(rows[1]["prev_hash"], canon)
    assert verify_audit_chain(rows) == 3


def test_legacy_unchained_rows_are_skipped():
    legacy = [{"id": 0, "row_hash": None}]
    assert verify_audit_chain(legacy + _chain()) is None


# ── categorisation / id extraction ──────────────────────────────────

@pytest.mark.parametrize("path,cat", [
    ("/api/drone-control/command", "command"),
    ("/api/drone-control/simulate/start", "command"),
    ("/api/drone-flight/missions/5", "mission"),
    ("/api/drone-flight/missions/5/status", "mission"),
    ("/api/auth/register", "user"),
    ("/api/drone-master/drone-types", "data"),
])
def test_categorise(path, cat):
    assert audit_middleware.categorise(path) == cat


def test_id_extraction():
    assert audit_middleware._ids("/api/drone-master/drones/12/payload") == (12, None)
    assert audit_middleware._ids("/api/drone-flight/missions/9") == (None, 9)
    assert audit_middleware._ids("/api/drone-control/disconnect/4") == (4, None)


# ── middleware ───────────────────────────────────────────────────────

@pytest.fixture
def audit_on(monkeypatch):
    monkeypatch.setattr(audit_middleware.cfg, "audit_mutations", True)
    rec = AsyncMock()
    monkeypatch.setattr(audit_middleware, "record_mutation", rec)
    return rec


async def test_mutation_is_recorded_with_user_route_and_status(
    client: AsyncClient, flight_controller_user, make_token, audit_on,
):
    resp = await client.post(
        "/api/drone-control/command",
        json={"drone_id": 7, "command": "arm", "params": {}},
        headers=auth_headers(flight_controller_user, make_token),
    )
    assert resp.status_code == 503
    audit_on.assert_awaited_once()
    kw = audit_on.await_args.kwargs
    assert kw["user_id"] == flight_controller_user.id
    assert kw["method"] == "POST"
    assert kw["route"] == "/api/drone-control/command"
    assert kw["status_code"] == 503


async def test_forbidden_attempt_is_recorded_against_the_caller(
    client: AsyncClient, viewer_user, make_token, audit_on,
):
    resp = await client.post(
        "/api/drone-control/command",
        json={"drone_id": 1, "command": "arm", "params": {}},
        headers=auth_headers(viewer_user, make_token),
    )
    assert resp.status_code == 403
    assert audit_on.await_args.kwargs["user_id"] == viewer_user.id
    assert audit_on.await_args.kwargs["status_code"] == 403


async def test_unauthenticated_attempt_is_recorded_without_user(client: AsyncClient, audit_on):
    resp = await client.post("/api/drone-control/command",
                             json={"drone_id": 1, "command": "arm", "params": {}})
    assert resp.status_code == 401
    assert audit_on.await_args.kwargs["user_id"] is None


async def test_reads_and_auth_plumbing_are_not_recorded(
    client: AsyncClient, admin_user, make_token, audit_on,
):
    await client.get("/api/auth/users", headers=auth_headers(admin_user, make_token))
    await client.post("/api/auth/token", data={"username": "admin_test", "password": "Admin@1234"})
    await client.post("/api/auth/ws-ticket", headers=auth_headers(admin_user, make_token))
    audit_on.assert_not_awaited()


async def test_audit_failure_never_breaks_the_request(
    client: AsyncClient, viewer_user, make_token, monkeypatch,
):
    monkeypatch.setattr(audit_middleware.cfg, "audit_mutations", True)
    monkeypatch.setattr(audit_middleware, "record_mutation",
                        AsyncMock(side_effect=RuntimeError("db down")))
    resp = await client.post("/api/drone-control/command",
                             json={"drone_id": 1, "command": "arm", "params": {}},
                             headers=auth_headers(viewer_user, make_token))
    assert resp.status_code == 403


# ── explicit command event ───────────────────────────────────────────

async def test_command_endpoint_writes_command_sent_event(
    client: AsyncClient, flight_controller_user, make_token,
):
    with patch("app.modules.drone_control.router.AuditLogger") as cls:
        cls.return_value.command_sent = AsyncMock()
        await client.post(
            "/api/drone-control/command",
            json={"drone_id": 7, "command": "arm", "params": {}},
            headers=auth_headers(flight_controller_user, make_token),
        )
    args = cls.return_value.command_sent.await_args.args
    assert args[0] == flight_controller_user.id
    assert args[1] == 7
    assert args[2] == "arm"
    assert args[3] == "failed"          # drone not connected in the test environment
