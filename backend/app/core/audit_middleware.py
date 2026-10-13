"""
Audit trail for every state-changing API call.

One middleware instead of per-endpoint calls, so a new route cannot be
forgotten: any POST/PUT/PATCH/DELETE under /api/ is recorded with who
(user id from the verified JWT), what (route template, category), which
drone/mission, from where (client IP) and the outcome (HTTP status).

Query strings are never logged (they can carry single-use WebSocket tickets),
and request bodies are not read here — richer events (e.g. the command name
for /drone-control/command) are written explicitly by the endpoint.
"""
import re
from typing import Optional

import structlog
import jwt
from jwt import PyJWTError as JWTError

from app.config import get_settings
from app.core.security import AuditLogger, client_ip

log = structlog.get_logger()
cfg = get_settings()

_MUTATING = {"POST", "PUT", "PATCH", "DELETE"}

# Already audited by dedicated events, or pure plumbing with no state change.
_SKIP_PREFIXES = (
    "/api/auth/token",
    "/api/auth/refresh",
    "/api/auth/logout",
    "/api/auth/ws-ticket",
)

_DRONE_RE = re.compile(r"/(?:drones?|disconnect|live-sync|apply)/(\d+)")
_MISSION_RE = re.compile(r"/missions/(\d+)")

_COMMAND_HINTS = ("/command", "/connect", "/disconnect", "/autoconnect",
                  "/simulate", "/geofence", "/upload", "/assign-fleet", "/live-sync")


def categorise(path: str) -> str:
    if path.startswith("/api/auth"):
        return AuditLogger.USER
    if "/missions" in path and not any(h in path for h in ("/upload", "/live-sync")):
        return AuditLogger.MISSION
    if any(h in path for h in _COMMAND_HINTS):
        return AuditLogger.COMMAND
    return AuditLogger.DATA


def _ids(path: str) -> tuple[Optional[int], Optional[int]]:
    d = _DRONE_RE.search(path)
    m = _MISSION_RE.search(path)
    return (int(d.group(1)) if d else None, int(m.group(1)) if m else None)


def _user_id_from_request(request) -> Optional[int]:
    """Signature- and expiry-verified subject of the presented access token, if any."""
    auth = request.headers.get("authorization", "")
    token = auth[7:] if auth.lower().startswith("bearer ") else request.cookies.get("da_access")
    if not token:
        return None
    try:
        payload = jwt.decode(token, cfg.secret_key, algorithms=[cfg.algorithm])
        return int(payload["sub"])
    except (JWTError, KeyError, ValueError, TypeError):
        return None


async def record_mutation(*, user_id, method: str, route: str, path: str,
                          status_code: int, ip: str) -> None:
    """Write one audit row using its own session (the request session is closed by now)."""
    from app.database import AsyncSessionLocal
    drone_id, mission_id = _ids(path)
    if status_code in (401, 403):
        severity = "WARNING"          # attempted action without the right to do it
    elif status_code >= 500:
        severity = "ERROR"
    else:
        severity = "INFO"
    async with AsyncSessionLocal() as db:
        await AuditLogger(db).log(
            categorise(path), f"{method} {route}",
            user_id=user_id, drone_id=drone_id, mission_id=mission_id,
            ip_address=ip,
            detail={"path": path, "status": status_code},
            severity=severity,
        )


async def audit_mutations(request, call_next):
    response = await call_next(request)
    try:
        path = request.url.path
        if (cfg.audit_mutations and request.method in _MUTATING
                and path.startswith("/api/") and not path.startswith(_SKIP_PREFIXES)):
            route_obj = request.scope.get("route")
            await record_mutation(
                user_id=_user_id_from_request(request),
                method=request.method,
                route=getattr(route_obj, "path", path),
                path=path,
                status_code=response.status_code,
                ip=client_ip(request),
            )
    except Exception as e:                      # auditing must never break a request
        log.error("Audit middleware failed", error=str(e))
    return response
