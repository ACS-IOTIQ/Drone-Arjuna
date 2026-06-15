"""
System health endpoint tests
==============================
GET /api/health

Covers:
  - Health endpoint responds 200 without authentication
  - Response contains {status, version} fields
  - Status value is "ok"
  - Version follows semver pattern
"""
import re
from httpx import AsyncClient


async def test_health_200_unauthenticated(client: AsyncClient):
    """Health endpoint must return 200 without any auth token."""
    resp = await client.get("/api/health")
    assert resp.status_code == 200


async def test_health_returns_status_ok(client: AsyncClient):
    resp = await client.get("/api/health")
    body = resp.json()
    assert body["status"] == "ok"


async def test_health_returns_version(client: AsyncClient):
    resp = await client.get("/api/health")
    body = resp.json()
    assert "version" in body
    # Version should match semver pattern e.g. "1.0.0" or "2.0.0"
    assert re.match(r"^\d+\.\d+\.\d+", body["version"])
