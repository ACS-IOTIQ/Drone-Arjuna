"""
Operator-confirmed database restore.

With BACKUP_AUTO_RESTORE=false the system only *reports* detected data loss
(a RESTORE_REQUIRED system event); a person then confirms here. Restores only
ever fill tables that are currently empty, and only from dumps whose signature
verifies.
"""
import asyncio
from datetime import datetime, timezone
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict

from app.core import backup
from app.core.rbac import Role, require_min_role
from app.core.security import client_ip
from app.models.user import User

router = APIRouter()


class RestoreRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    confirm: bool
    database: Literal["all", "main", "telemetry"] = "all"


def _list_dumps(target: backup.DumpTarget) -> list[dict]:
    """Newest-first dump metadata from MinIO, falling back to local disk."""
    try:
        client = backup._minio_client()
        backup._ensure_bucket(client, target.minio_bucket)
        objs = client.list_objects_v2(Bucket=target.minio_bucket).get("Contents", [])
        items = [{"name": o["Key"], "size": o["Size"],
                  "modified": o["LastModified"].isoformat(), "source": "minio"} for o in objs]
    except Exception:
        items = [{"name": p.name, "size": p.stat().st_size,
                  "modified": datetime.fromtimestamp(p.stat().st_mtime, timezone.utc).isoformat(),
                  "source": "local"} for p in target.backup_dir.glob("dump_*.json")]
    return sorted(items, key=lambda i: i["name"], reverse=True)


@router.get("/backup/list")
async def list_backups(
    admin: Annotated[User, Depends(require_min_role(Role.ADMIN))],
):
    return {
        t.name: await asyncio.to_thread(_list_dumps, t) for t in backup.ALL_TARGETS
    }


@router.post("/backup/restore")
async def confirm_restore(
    body: RestoreRequest,
    request: Request,
    admin: Annotated[User, Depends(require_min_role(Role.ADMIN))],
):
    if not body.confirm:
        raise HTTPException(status_code=400, detail="Set confirm=true to run the restore")
    targets = [t for t in backup.ALL_TARGETS if body.database in ("all", t.name)]
    restored = {}
    for target in targets:
        restored[target.name] = await backup.restore_latest_dump(target)   # operator-initiated
    backup.log.warning("Operator-confirmed restore", admin_id=admin.id,
                       ip=client_ip(request), result=restored)
    return {"detail": "Restore finished", "restored": restored}
