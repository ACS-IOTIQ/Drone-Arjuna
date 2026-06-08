from typing import Annotated, Optional
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_db
from app.core.rbac import require_min_role, Role
from app.models.user import User
from app.modules.drone_inventory.service import InventoryService

router = APIRouter()
DbDep     = Annotated[AsyncSession, Depends(get_db)]
ViewerDep = Annotated[User, Depends(require_min_role(Role.VIEWER))]


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