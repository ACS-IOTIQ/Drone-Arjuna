from typing import Annotated, Optional
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_db
from app.core.rbac import require_min_role, require_role, Role
from app.models.user import User
from app.modules.drone_inventory.service import InventoryService
from app.schemas.threat import ThreatSystemCreate, ThreatSystemUpdate, ThreatNotesPatch

router = APIRouter()
DbDep     = Annotated[AsyncSession, Depends(get_db)]
ViewerDep = Annotated[User, Depends(require_min_role(Role.VIEWER))]
AdminDep  = Annotated[User, Depends(require_min_role(Role.ADMIN))]

# Threat read: intelligence_analyst, mission_commander, admin (and above)
_ThreatReadDep = Depends(require_role(
    Role.INTELLIGENCE_ANALYST, Role.MISSION_COMMANDER, Role.ADMIN,
))
# Threat write: admin only
_ThreatWriteDep = Depends(require_min_role(Role.ADMIN))
# Notes patch: intelligence_analyst OR admin
_NotesDep = Depends(require_role(Role.INTELLIGENCE_ANALYST, Role.ADMIN))


@router.get("/drones")
async def list_inventory_drones(
    db: DbDep,
    _: ViewerDep,
    size_class:   Optional[str] = Query(None),
    mission_type: Optional[str] = Query(None),
    autopilot:    Optional[str] = Query(None),
):
    """Drone catalogue with optional facet filters."""
    items = await InventoryService(db).list_drones(size_class, mission_type, autopilot)
    return {"items": items, "total": len(items)}


@router.get("/drones/{type_id}")
async def get_inventory_drone(type_id: int, db: DbDep, _: ViewerDep):
    """Full detail view for a single drone type."""
    return await InventoryService(db).get_drone_detail(type_id)


@router.get("/drones/{type_id}/quick-ref")
async def drone_quick_reference(type_id: int, db: DbDep, _: ViewerDep):
    """Compact spec card for mission planning panel."""
    return await InventoryService(db).quick_reference(type_id)


@router.get("/compare")
async def compare_drones(
    db: DbDep,
    _: ViewerDep,
    ids: list[int] = Query(..., description="2–4 drone type IDs to compare"),
):
    """Side-by-side performance comparison of 2–4 drone types."""
    return await InventoryService(db).compare_drones(ids)


@router.get("/search")
async def search_inventory(
    db: DbDep,
    _: ViewerDep,
    q:     str = Query("", description="Search query"),
    limit: int = Query(20, ge=1, le=100),
):
    """
    V1: SQL ILIKE search across name, manufacturer, model, notes.
    V2: Elasticsearch full-text search with facets and relevance ranking.
    """
    return await InventoryService(db).search(q, limit)


@router.get("/payloads")
async def list_inventory_payloads(_: ViewerDep):
    """V1 stub — payload knowledge base implemented in V2."""
    return {
        "items": [],
        "total": 0,
        "note": "Payload inventory with rich specs available in V2",
    }


# ── Threat Systems ────────────────────────────────────────────────────────────

@router.get("/threat-systems", dependencies=[_ThreatReadDep])
async def list_threat_systems(
    db: DbDep,
    category: Optional[str] = Query(None, description="Filter by category: UAV/RADAR/SAM/EW"),
    country:  Optional[str] = Query(None, description="Filter by country of origin"),
):
    items = await InventoryService(db).list_threats(category, country)
    return {"items": items, "total": len(items)}


@router.get("/threat-systems/{threat_id}", dependencies=[_ThreatReadDep])
async def get_threat_system(threat_id: int, db: DbDep):
    return await InventoryService(db).get_threat(threat_id)


@router.post("/threat-systems", status_code=201, dependencies=[_ThreatWriteDep])
async def create_threat_system(body: ThreatSystemCreate, db: DbDep):
    return await InventoryService(db).create_threat(body.model_dump())


@router.put("/threat-systems/{threat_id}", dependencies=[_ThreatWriteDep])
async def update_threat_system(threat_id: int, body: ThreatSystemUpdate, db: DbDep):
    return await InventoryService(db).update_threat(threat_id, body.model_dump(exclude_none=True))


@router.patch("/threat-systems/{threat_id}/notes", dependencies=[_NotesDep])
async def patch_threat_notes(threat_id: int, body: ThreatNotesPatch, db: DbDep):
    return await InventoryService(db).update_threat(threat_id, {"notes": body.notes})


@router.delete("/threat-systems/{threat_id}", status_code=204, dependencies=[_ThreatWriteDep])
async def delete_threat_system(threat_id: int, db: DbDep):
    await InventoryService(db).delete_threat(threat_id)