from typing import Annotated, Optional
from fastapi import APIRouter, Depends, Query, Body
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_db
from app.core.rbac import require_min_role, require_role, Role
from app.models.user import User
from app.modules.drone_inventory.service import InventoryService
from app.modules.drone_inventory.kb_service import InventoryKBService
from app.schemas.threat import ThreatSystemCreate, ThreatSystemUpdate, ThreatNotesPatch
from app.schemas.inventory_link import (
    DronePayloadLinkCreate, DronePayloadLinkUpdate,
    DroneThreatLinkCreate, DroneThreatLinkUpdate,
    PayloadThreatLinkCreate, PayloadThreatLinkUpdate,
)
from app.schemas.inventory_kb import (
    InventorySearchQuery, InventoryHealthReport
)

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


# ── Inventory Links: drone <-> payload <-> threat ──────────────────────────────
# Read: any viewer+ (knowledge-base browsing). Write: admin only.

@router.get("/links/drones/{drone_type_id}/payloads")
async def list_payloads_for_drone(drone_type_id: int, db: DbDep, _: ViewerDep):
    items = await InventoryService(db).list_payloads_for_drone(drone_type_id)
    return {"items": items, "total": len(items)}


@router.get("/links/payloads/{payload_type_id}/drones")
async def list_drones_for_payload(payload_type_id: int, db: DbDep, _: ViewerDep):
    items = await InventoryService(db).list_drones_for_payload(payload_type_id)
    return {"items": items, "total": len(items)}


@router.post("/links/drone-payload", status_code=201, dependencies=[_ThreatWriteDep])
async def create_drone_payload_link(body: DronePayloadLinkCreate, db: DbDep):
    link = await InventoryService(db).create_drone_payload_link(body.model_dump())
    return InventoryService._link_card(link)


@router.put("/links/drone-payload/{link_id}", dependencies=[_ThreatWriteDep])
async def update_drone_payload_link(link_id: int, body: DronePayloadLinkUpdate, db: DbDep):
    link = await InventoryService(db).update_drone_payload_link(
        link_id, body.model_dump(exclude_none=True)
    )
    return InventoryService._link_card(link)


@router.delete("/links/drone-payload/{link_id}", status_code=204, dependencies=[_ThreatWriteDep])
async def delete_drone_payload_link(link_id: int, db: DbDep):
    await InventoryService(db).delete_drone_payload_link(link_id)


@router.get("/links/drones/{drone_type_id}/threats")
async def list_threats_for_drone(drone_type_id: int, db: DbDep, _: ViewerDep):
    items = await InventoryService(db).list_threats_for_drone(drone_type_id)
    return {"items": items, "total": len(items)}


@router.get("/links/threats/{threat_system_id}/drones")
async def list_drones_for_threat(threat_system_id: int, db: DbDep, _: ViewerDep):
    items = await InventoryService(db).list_drones_for_threat(threat_system_id)
    return {"items": items, "total": len(items)}


@router.post("/links/drone-threat", status_code=201, dependencies=[_ThreatWriteDep])
async def create_drone_threat_link(body: DroneThreatLinkCreate, db: DbDep):
    link = await InventoryService(db).create_drone_threat_link(body.model_dump())
    return InventoryService._link_card(link)


@router.put("/links/drone-threat/{link_id}", dependencies=[_ThreatWriteDep])
async def update_drone_threat_link(link_id: int, body: DroneThreatLinkUpdate, db: DbDep):
    link = await InventoryService(db).update_drone_threat_link(
        link_id, body.model_dump(exclude_none=True)
    )
    return InventoryService._link_card(link)


@router.delete("/links/drone-threat/{link_id}", status_code=204, dependencies=[_ThreatWriteDep])
async def delete_drone_threat_link(link_id: int, db: DbDep):
    await InventoryService(db).delete_drone_threat_link(link_id)


@router.get("/links/payloads/{payload_type_id}/threats")
async def list_threats_for_payload(payload_type_id: int, db: DbDep, _: ViewerDep):
    items = await InventoryService(db).list_threats_for_payload(payload_type_id)
    return {"items": items, "total": len(items)}


@router.get("/links/threats/{threat_system_id}/payloads")
async def list_payloads_for_threat(threat_system_id: int, db: DbDep, _: ViewerDep):
    items = await InventoryService(db).list_payloads_for_threat(threat_system_id)
    return {"items": items, "total": len(items)}


@router.post("/links/payload-threat", status_code=201, dependencies=[_ThreatWriteDep])
async def create_payload_threat_link(body: PayloadThreatLinkCreate, db: DbDep):
    link = await InventoryService(db).create_payload_threat_link(body.model_dump())
    return InventoryService._link_card(link)


@router.put("/links/payload-threat/{link_id}", dependencies=[_ThreatWriteDep])
async def update_payload_threat_link(link_id: int, body: PayloadThreatLinkUpdate, db: DbDep):
    link = await InventoryService(db).update_payload_threat_link(
        link_id, body.model_dump(exclude_none=True)
    )
    return InventoryService._link_card(link)


@router.delete("/links/payload-threat/{link_id}", status_code=204, dependencies=[_ThreatWriteDep])
async def delete_payload_threat_link(link_id: int, db: DbDep):
    await InventoryService(db).delete_payload_threat_link(link_id)


@router.get("/drones/{drone_type_id}/cross-reference")
async def drone_cross_reference(drone_type_id: int, db: DbDep, _: ViewerDep):
    """Full relational neighborhood: compatible payloads, threat exposure, counterable threats."""
    return await InventoryService(db).drone_cross_reference(drone_type_id)


# ──────────────────────────────────────────────────────────────────────────────
# KNOWLEDGE-BASE: CROSS-REFERENCE QUERIES
# ──────────────────────────────────────────────────────────────────────────────
# All KB queries are read-only. Roles: VIEWER+

@router.get("/kb/capabilities/payload/{payload_id}")
async def kb_payload_capability_profile(
    payload_id: int,
    db: DbDep,
    _: ViewerDep,
):
    """
    Query: Which drones can carry payload X?
    Returns: Detailed capability profile with all compatible drones and constraints.
    """
    return await InventoryKBService(db).get_payload_capability_profile(payload_id)


@router.get("/kb/capabilities/drone/{drone_id}")
async def kb_drone_capability_profile(
    drone_id: int,
    db: DbDep,
    _: ViewerDep,
):
    """
    Query: What payloads can drone D carry?
    Returns: List of compatible payloads grouped by primary/secondary.
    """
    return await InventoryKBService(db).get_drone_capability_profile(drone_id)


@router.get("/kb/threats/mitigation/{threat_id}")
async def kb_threat_mitigation_profile(
    threat_id: int,
    db: DbDep,
    _: ViewerDep,
):
    """
    Query: How do we defeat threat T?
    Multi-hop chain: Threat → Effective Payloads → Capable Drones
    Returns: Complete mitigation profile with coverage analysis.
    """
    return await InventoryKBService(db).get_threat_mitigation_profile(threat_id)


@router.get("/kb/threats/vulnerability/{drone_id}")
async def kb_drone_vulnerability_profile(
    drone_id: int,
    db: DbDep,
    _: ViewerDep,
):
    """
    Query: What threats threaten drone D?
    Includes available payloads and their counter-effectiveness.
    Returns: Threat exposure profile with mitigation options.
    """
    return await InventoryKBService(db).get_drone_vulnerability_profile(drone_id)


@router.post("/kb/search")
async def kb_search_inventory(
    query: InventorySearchQuery,
    db: DbDep,
    _: ViewerDep,
):
    """
    Multi-faceted inventory search with cross-reference results.
    Supports free-text search and dimensional filters (size class, mission type, category, etc.).
    """
    return await InventoryKBService(db).search_inventory(query)


@router.get("/kb/analytics/health")
async def kb_inventory_health_report(
    db: DbDep,
    _: ViewerDep,
):
    """
    Inventory knowledge-base health metrics:
    - Entity counts (drones, payloads, threats)
    - Link coverage (% of entities with relationships)
    - Gap analysis (unmapped entities)
    - Link density
    """
    return await InventoryKBService(db).get_inventory_health_report()


@router.get("/kb/analytics/entity/{entity_type}/{entity_id}")
async def kb_entity_relationship_stats(
    entity_type: str,
    entity_id: int,
    db: DbDep,
    _: ViewerDep,
):
    """
    Relationship statistics for a specific entity (drone, payload, or threat).
    Shows connection counts, transitive paths, and entity neighborhood.
    """
    return await InventoryKBService(db).get_entity_relationship_stats(entity_type, entity_id)


# ──────────────────────────────────────────────────────────────────────────────
# KNOWLEDGE-BASE: ENRICHED ENTITY VIEWS
# ──────────────────────────────────────────────────────────────────────────────

@router.get("/kb/drones/{drone_id}/full")
async def kb_get_drone_with_inventory(
    drone_id: int,
    db: DbDep,
    _: ViewerDep,
):
    """
    Full enriched drone type view with all inventory relationships embedded:
    - Compatible payloads (with constraints)
    - Exposed threats (with exposure levels)
    - Registered instances
    """
    service = InventoryKBService(db)
    from app.models.drone import DroneType
    drone = await db.get(DroneType, drone_id)
    if not drone:
        from fastapi import HTTPException
        raise HTTPException(404, f"Drone type #{drone_id} not found")
    return await service._hydrate_drone_with_inventory(drone)


@router.get("/kb/payloads/{payload_id}/full")
async def kb_get_payload_with_inventory(
    payload_id: int,
    db: DbDep,
    _: ViewerDep,
):
    """
    Full enriched payload type view with all inventory relationships embedded:
    - Compatible drones (with quantities)
    - Effective against threats (with effectiveness levels)
    """
    service = InventoryKBService(db)
    from app.models.payload import PayloadType
    payload = await db.get(PayloadType, payload_id)
    if not payload:
        from fastapi import HTTPException
        raise HTTPException(404, f"Payload type #{payload_id} not found")
    return await service._hydrate_payload_with_inventory(payload)


@router.get("/kb/threats/{threat_id}/full")
async def kb_get_threat_with_inventory(
    threat_id: int,
    db: DbDep,
    _: ViewerDep,
):
    """
    Full enriched threat system view with all inventory relationships embedded:
    - Vulnerable drones (with exposure levels)
    - Mitigating payloads (with effectiveness levels)
    """
    service = InventoryKBService(db)
    from app.models.threat import ThreatSystem
    threat = await db.get(ThreatSystem, threat_id)
    if not threat:
        from fastapi import HTTPException
        raise HTTPException(404, f"Threat system #{threat_id} not found")
    return await service._hydrate_threat_with_inventory(threat)
