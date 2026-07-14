"""
Infrastructure configuration tests
====================================
Validates the four infrastructure gaps fixed:

  Gap 1  — docker-compose.yml: backend now waits for Elasticsearch
  Gap 2  — .env.example: ALLOWED_ORIGINS_STR (not ALLOWED_ORIGINS),
            ELASTICSEARCH_URL, and SMTP/MailHog vars added
  Gap 3  — vite.config.ts: usePolling: true for Windows Docker HMR (DEF-07)
  Gap 4  — .github/workflows/ci.yml: three-job CI pipeline

Tests are pure file-inspection / config tests.  They never hit live
services — no async fixtures, no database, no network.
"""
import os
import re
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml

# Project root resolved relative to this file:
#   backend/app/tests/test_infra_config.py  →  ../../..
def _find_project_root() -> Path:
    """
    Resolve the repository root, handling three execution contexts:

    1. Inside Docker (docker compose exec backend pytest):
       ./backend is mounted at /app; project-root files are bind-mounted
       read-only at /project by docker-compose.yml.

    2. CI / host (cd backend && pytest):
       Walk up from this file until docker-compose.yml is found.

    3. Fallback: parents[3] (best-effort, may be wrong).
    """
    # Context 1 — Docker: project root bind-mounted at /project
    docker_root = Path("/project")
    if (docker_root / "docker-compose.yml").exists():
        return docker_root

    # Context 2 — Host / CI: walk upward from this file
    start = Path(__file__).resolve()
    for candidate in start.parents:
        if (
            (candidate / "docker-compose.yml").exists()
            and (candidate / ".env.example").exists()
            and (candidate / "frontend" / "vite.config.ts").exists()
        ):
            return candidate

    # Context 3 — Fallback
    return start.parents[3]


PROJECT_ROOT = _find_project_root()


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _fresh_settings(**overrides):
    """
    Instantiate a brand-new Settings() with the given env-var overrides
    without touching the lru_cache singleton used by the running app.

    _env_file=None prevents pydantic-settings from reading the live .env
    file, which may contain values (e.g. SMTP_ENABLED=true) that would
    override the code-level defaults under test.  The required fields
    (DATABASE_URL, SECRET_KEY, etc.) are already set in os.environ by
    conftest.py, so Settings() instantiates cleanly without .env.
    """
    from app.config import Settings

    saved = {}
    for k, v in overrides.items():
        saved[k] = os.environ.get(k)
        os.environ[k] = v
    try:
        return Settings(_env_file=None)
    finally:
        for k, original in saved.items():
            if original is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = original


# ─────────────────────────────────────────────────────────────────────────────
# Gap 2a — Settings: ALLOWED_ORIGINS_STR
# ─────────────────────────────────────────────────────────────────────────────

class TestAllowedOriginsStr:
    """ALLOWED_ORIGINS_STR must be the live pydantic-settings field name."""

    def test_allowed_origins_str_is_read(self):
        s = _fresh_settings(ALLOWED_ORIGINS_STR="http://example.com,http://test.local")
        assert "http://example.com" in s.allowed_origins
        assert "http://test.local" in s.allowed_origins

    def test_allowed_origins_property_strips_whitespace(self):
        s = _fresh_settings(ALLOWED_ORIGINS_STR="http://a.com , http://b.com")
        assert s.allowed_origins == ["http://a.com", "http://b.com"]

    def test_allowed_origins_single_origin(self):
        s = _fresh_settings(ALLOWED_ORIGINS_STR="http://only.one")
        assert s.allowed_origins == ["http://only.one"]

    def test_old_allowed_origins_key_is_silently_ignored(self):
        """
        The old key ALLOWED_ORIGINS does not match any Settings field.
        pydantic-settings has extra='ignore', so it must be a no-op —
        the default value is returned unchanged.
        """
        default = _fresh_settings().allowed_origins
        s = _fresh_settings(ALLOWED_ORIGINS="http://injected.bad")
        assert "http://injected.bad" not in s.allowed_origins
        assert s.allowed_origins == default


# ─────────────────────────────────────────────────────────────────────────────
# Gap 2b — Settings: ELASTICSEARCH_URL
# ─────────────────────────────────────────────────────────────────────────────

class TestElasticsearchUrl:
    """ELASTICSEARCH_URL must be configurable and used by the search client."""

    def test_default_is_valid_url(self):
        s = _fresh_settings()
        assert s.elasticsearch_url.startswith("http")

    def test_env_override_is_read(self):
        s = _fresh_settings(ELASTICSEARCH_URL="http://elasticsearch:9200")
        assert s.elasticsearch_url == "http://elasticsearch:9200"

    def test_custom_host_override(self):
        s = _fresh_settings(ELASTICSEARCH_URL="http://es-node1:9201")
        assert s.elasticsearch_url == "http://es-node1:9201"

    def test_search_get_client_uses_settings_url(self):
        """
        get_client() must pass settings.elasticsearch_url to
        AsyncElasticsearch — not a hardcoded string.
        """
        from app.core import search

        captured_args = {}

        class _FakeES:
            def __init__(self, url, **kwargs):
                captured_args["url"] = url

        search._client = None
        s = _fresh_settings(ELASTICSEARCH_URL="http://es-custom:9200")

        with patch("app.core.search.get_settings", return_value=s), \
             patch("app.core.search.AsyncElasticsearch", _FakeES):
            search._client = None
            search.get_client()

        assert captured_args["url"] == "http://es-custom:9200"
        search._client = None  # restore global state


# ─────────────────────────────────────────────────────────────────────────────
# Gap 2c — Settings: SMTP / MailHog
# ─────────────────────────────────────────────────────────────────────────────

class TestSmtpSettings:
    """All SMTP vars must be configurable via environment."""

    def test_smtp_disabled_by_default(self):
        """
        The Settings class must declare smtp_enabled=False as the code default.

        We check the field declaration rather than instantiating Settings because
        Docker Compose injects all .env variables (including SMTP_ENABLED) into
        os.environ via `env_file: .env` before the process starts.  Instantiating
        Settings() — even with _env_file=None — would still read that injected
        value from os.environ, masking the actual code default.
        """
        from app.config import Settings
        assert Settings.model_fields["smtp_enabled"].default is False

    def test_smtp_enabled_flag(self):
        s = _fresh_settings(SMTP_ENABLED="true")
        assert s.smtp_enabled is True

    def test_smtp_host_override(self):
        s = _fresh_settings(SMTP_HOST="mailhog")
        assert s.smtp_host == "mailhog"

    def test_smtp_port_override(self):
        s = _fresh_settings(SMTP_PORT="1025")
        assert s.smtp_port == 1025

    def test_smtp_user_and_password(self):
        s = _fresh_settings(SMTP_USER="ops@example.com", SMTP_PASSWORD="s3cr3t")
        assert s.smtp_user == "ops@example.com"
        assert s.smtp_password == "s3cr3t"

    async def test_send_approval_email_is_noop_when_disabled(self):
        """
        When SMTP_ENABLED=false send_approval_email must return without
        calling aiosmtplib.send — even if credentials are wrong.

        Declared async so pytest-asyncio manages the event loop; avoids the
        asyncio.run() / session-loop conflict in asyncio_mode=auto.
        """
        from app.core.email import send_approval_email

        s = _fresh_settings(SMTP_ENABLED="false")

        with patch("app.core.email.get_settings", return_value=s), \
             patch("app.core.email.aiosmtplib") as mock_smtp:

            await send_approval_email(
                to_email="x@example.com",
                full_name="X",
                username="x",
                temp_password="X@123456",
                role="viewer",
            )
            mock_smtp.send.assert_not_called()

    async def test_send_approval_email_calls_smtp_when_enabled(self):
        """
        When enabled, aiosmtplib.send must be awaited with the correct
        hostname and port from settings.

        Declared async so pytest-asyncio manages the event loop.
        """
        from app.core.email import send_approval_email

        s = _fresh_settings(
            SMTP_ENABLED="true",
            SMTP_HOST="mailhog",
            SMTP_PORT="1025",
            SMTP_USER="",
            SMTP_PASSWORD="",
        )

        captured: dict = {}

        async def _fake_send(msg, **kwargs):
            captured.update(kwargs)

        with patch("app.core.email.get_settings", return_value=s), \
             patch("app.core.email.aiosmtplib.send", side_effect=_fake_send):

            await send_approval_email(
                to_email="user@example.com",
                full_name="Test User",
                username="testuser",
                temp_password="Test@1234",
                role="viewer",
            )

        assert captured, "aiosmtplib.send was never called"
        assert captured["hostname"] == "mailhog"
        assert captured["port"] == 1025


# ─────────────────────────────────────────────────────────────────────────────
# Gap 1 — docker-compose.yml
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def compose():
    path = PROJECT_ROOT / "docker-compose.yml"
    assert path.exists(), f"docker-compose.yml not found at {path}"
    return yaml.safe_load(path.read_text())


class TestDockerCompose:
    """docker-compose.yml structural checks."""

    def test_elasticsearch_service_present(self, compose):
        assert "elasticsearch" in compose["services"], \
            "elasticsearch service is missing from docker-compose.yml"

    def test_elasticsearch_has_healthcheck(self, compose):
        svc = compose["services"]["elasticsearch"]
        assert "healthcheck" in svc, \
            "elasticsearch service must have a healthcheck so depends_on works"

    def test_backend_depends_on_elasticsearch(self, compose):
        depends = compose["services"]["backend"].get("depends_on", {})
        assert "elasticsearch" in depends, (
            "backend.depends_on must include elasticsearch — without it "
            "bulk_index_all silently fails on every cold start"
        )

    def test_backend_elasticsearch_condition_service_healthy(self, compose):
        condition = (
            compose["services"]["backend"]["depends_on"]["elasticsearch"]
            .get("condition")
        )
        assert condition == "service_healthy", (
            f"Expected 'service_healthy', got {condition!r} — "
            "the backend will race ES on startup"
        )

    def test_all_services_on_da_network(self, compose):
        missing = [
            name
            for name, svc in compose["services"].items()
            if "da_network" not in (svc.get("networks") or [])
        ]
        assert not missing, \
            f"Services missing da_network (breaks inter-container DNS): {missing}"

    def test_es_data_volume_declared(self, compose):
        assert "es_data" in compose.get("volumes", {}), \
            "es_data volume must be declared so Elasticsearch data survives restarts"

    def test_backend_elasticsearch_url_env_set(self, compose):
        env = compose["services"]["backend"].get("environment", {})
        # docker-compose environment can be dict or list of "KEY=VALUE"
        if isinstance(env, list):
            keys = [e.split("=", 1)[0] for e in env]
        else:
            keys = list(env.keys())
        assert "ELASTICSEARCH_URL" in keys, \
            "backend environment must set ELASTICSEARCH_URL=http://elasticsearch:9200"


# ─────────────────────────────────────────────────────────────────────────────
# Gap 2 — .env.example
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def env_example_keys():
    path = PROJECT_ROOT / ".env.example"
    assert path.exists(), ".env.example not found at project root"
    keys = set()
    for line in path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            keys.add(line.split("=", 1)[0].strip())
    return keys


class TestEnvExample:
    """.env.example must document every configurable variable."""

    def test_allowed_origins_str_present(self, env_example_keys):
        assert "ALLOWED_ORIGINS_STR" in env_example_keys, \
            "Must use ALLOWED_ORIGINS_STR — pydantic-settings ignores ALLOWED_ORIGINS"

    def test_old_allowed_origins_absent(self, env_example_keys):
        assert "ALLOWED_ORIGINS" not in env_example_keys, \
            "ALLOWED_ORIGINS is silently ignored; remove it to avoid confusion"

    def test_elasticsearch_url_present(self, env_example_keys):
        assert "ELASTICSEARCH_URL" in env_example_keys, \
            "ELASTICSEARCH_URL must be in .env.example (defaults to localhost:9200 " \
            "which breaks inside Docker)"

    def test_smtp_enabled_present(self, env_example_keys):
        assert "SMTP_ENABLED" in env_example_keys

    def test_smtp_host_present(self, env_example_keys):
        assert "SMTP_HOST" in env_example_keys

    def test_smtp_port_present(self, env_example_keys):
        assert "SMTP_PORT" in env_example_keys

    def test_smtp_user_present(self, env_example_keys):
        assert "SMTP_USER" in env_example_keys

    def test_smtp_password_present(self, env_example_keys):
        assert "SMTP_PASSWORD" in env_example_keys


# ─────────────────────────────────────────────────────────────────────────────
# Gap 3 — vite.config.ts (DEF-07)
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def vite_source():
    path = PROJECT_ROOT / "frontend" / "vite.config.ts"
    assert path.exists(), "frontend/vite.config.ts not found"
    return path.read_text()


class TestViteConfig:
    """vite.config.ts must satisfy all DEF-07 / DEF-08 requirements."""

    def test_use_polling_key_present(self, vite_source):
        assert "usePolling" in vite_source, \
            "usePolling missing — HMR will not work on Windows Docker volume mounts (DEF-07)"

    def test_use_polling_is_true(self, vite_source):
        assert re.search(r"usePolling\s*:\s*true", vite_source), \
            "usePolling must be true, not false (DEF-07)"

    def test_host_binds_to_0000(self, vite_source):
        assert re.search(r"host\s*:\s*['\"]0\.0\.0\.0['\"]", vite_source), \
            "server.host must be '0.0.0.0' so Docker Desktop can reach Vite (DEF-07)"

    def test_api_proxy_present(self, vite_source):
        assert re.search(r"['\"/]api['\"/]", vite_source), \
            "/api proxy missing — frontend calls will hit CORS errors (DEF-08)"

    def test_no_direct_backend_url(self, vite_source):
        """No hardcoded backend URL — all calls must go through the proxy (DEF-08)."""
        assert "http://backend:8000" not in vite_source or "proxy" in vite_source, \
            "Direct backend URL in vite config bypasses proxy and causes CORS errors"


# ─────────────────────────────────────────────────────────────────────────────
# Gap 4 — .github/workflows/ci.yml
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def ci():
    path = PROJECT_ROOT / ".github" / "workflows" / "ci.yml"
    assert path.exists(), ".github/workflows/ci.yml not found"
    return yaml.safe_load(path.read_text())


class TestCIWorkflow:
    """CI pipeline must run tests, type-check, and validate Docker builds."""

    def test_triggers_on_push_to_main(self, ci):
        branches = ci["on"]["push"]["branches"]
        assert "main" in branches

    def test_triggers_on_pull_request_to_main(self, ci):
        branches = ci["on"]["pull_request"]["branches"]
        assert "main" in branches

    def test_backend_job_exists(self, ci):
        assert "backend" in ci["jobs"], "CI must include a backend job"

    def test_frontend_job_exists(self, ci):
        assert "frontend" in ci["jobs"], "CI must include a frontend job"

    def test_docker_build_job_exists(self, ci):
        assert "docker-build" in ci["jobs"], "CI must include a docker-build job"

    def test_backend_job_runs_pytest(self, ci):
        steps = ci["jobs"]["backend"]["steps"]
        all_commands = " ".join(
            s.get("run", "") for s in steps if isinstance(s, dict)
        )
        assert "pytest" in all_commands, \
            "backend CI job must run pytest"

    def test_frontend_job_runs_tsc(self, ci):
        steps = ci["jobs"]["frontend"]["steps"]
        all_commands = " ".join(
            s.get("run", "") for s in steps if isinstance(s, dict)
        )
        assert "tsc" in all_commands, \
            "frontend CI job must run tsc (TypeScript type-check)"

    def test_frontend_job_runs_build(self, ci):
        steps = ci["jobs"]["frontend"]["steps"]
        all_commands = " ".join(
            s.get("run", "") for s in steps if isinstance(s, dict)
        )
        assert "build" in all_commands, \
            "frontend CI job must run a production build"

    def test_docker_build_needs_both_upstream_jobs(self, ci):
        needs = ci["jobs"]["docker-build"].get("needs", [])
        assert "backend" in needs, \
            "docker-build must wait for the backend job to pass"
        assert "frontend" in needs, \
            "docker-build must wait for the frontend job to pass"

    def test_backend_job_uses_python_311(self, ci):
        steps = ci["jobs"]["backend"]["steps"]
        for step in steps:
            if isinstance(step, dict) and "setup-python" in step.get("uses", ""):
                assert step["with"]["python-version"] == "3.11"
                return
        pytest.fail("backend CI job must pin Python to 3.11 via setup-python action")

    def test_frontend_job_uses_node_20(self, ci):
        steps = ci["jobs"]["frontend"]["steps"]
        for step in steps:
            if isinstance(step, dict) and "setup-node" in step.get("uses", ""):
                node_ver = str(step["with"]["node-version"])
                assert node_ver.startswith("20"), \
                    f"frontend CI must use Node 20, got {node_ver!r}"
                return
        pytest.fail("frontend CI job must pin Node version via setup-node action")
