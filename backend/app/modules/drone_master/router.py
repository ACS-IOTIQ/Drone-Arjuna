from typing import Annotated
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_db, Pagination
from app.core.rbac import require_min_role, Role
from app.models.user import User
from app.schemas.drone import (
    DroneTypeCreate, DroneTypeUpdate, DroneTypeOut,
    DroneInstanceCreate, DroneInstanceUpdate, DroneInstanceOut,
)
from app.schemas.vessel import (
    NavalVesselCreate, NavalVesselUpdate, NavalVesselOut, VesselPositionUpdate,
)
from app.modules.drone_master.service import DroneTypeService, DroneInstanceService
from app.modules.drone_master.vessel_service import NavalVesselService

router = APIRouter()
DbDep     = Annotated[AsyncSession, Depends(get_db)]
AdminDep  = Annotated[User, Depends(require_min_role(Role.MISSION_COMMANDER))]
ViewerDep = Annotated[User, Depends(require_min_role(Role.VIEWER))]


# ── Drone Types ───────────────────────────────────────────────────

@router.get("/drone-types", response_model=list[DroneTypeOut])
async def list_drone_types(db: DbDep, _: ViewerDep):
    return await DroneTypeService(db).list_active()


@router.get("/drone-types/stats")
async def drone_type_stats(db: DbDep, _: ViewerDep):
    return await DroneTypeService(db).get_summary_stats()


@router.get("/drone-types/{tid}", response_model=DroneTypeOut)
async def get_drone_type(tid: int, db: DbDep, _: ViewerDep):
    return await DroneTypeService(db).get_by_id(tid)


@router.post("/drone-types", response_model=DroneTypeOut, status_code=201)
async def create_drone_type(body: DroneTypeCreate, db: DbDep, _: AdminDep):
    return await DroneTypeService(db).create(body)


@router.put("/drone-types/{tid}", response_model=DroneTypeOut)
async def update_drone_type(tid: int, body: DroneTypeUpdate, db: DbDep, _: AdminDep):
    return await DroneTypeService(db).update(tid, body)


@router.delete("/drone-types/{tid}", status_code=204)
async def archive_drone_type(tid: int, db: DbDep, _: AdminDep):
    await DroneTypeService(db).archive(tid)


# ── Drone Instances ───────────────────────────────────────────────

@router.get("/drones", response_model=list[DroneInstanceOut])
async def list_drones(db: DbDep, _: ViewerDep):
    return await DroneInstanceService(db).list_all()


@router.get("/drones/{did}", response_model=DroneInstanceOut)
async def get_drone(did: int, db: DbDep, _: ViewerDep):
    return await DroneInstanceService(db).get_by_id(did)


@router.post("/drones", response_model=DroneInstanceOut, status_code=201)
async def register_drone(body: DroneInstanceCreate, db: DbDep, _: AdminDep):
    return await DroneInstanceService(db).register(body)


@router.put("/drones/{did}", response_model=DroneInstanceOut)
async def update_drone(did: int, body: DroneInstanceUpdate, db: DbDep, _: AdminDep):
    return await DroneInstanceService(db).update(did, body)


@router.patch("/drones/{did}/status")
async def set_drone_status(
    did: int, body: dict, db: DbDep,
    _: Annotated[User, Depends(require_min_role(Role.FLIGHT_CONTROLLER))],
):
    inst = await DroneInstanceService(db).update_status(did, body.get("status", ""))
    return {"detail": "Status updated", "status": inst.status}


@router.get("/drones/{did}/type-spec", response_model=DroneTypeOut)
async def get_drone_type_spec(did: int, db: DbDep, _: ViewerDep):
    """Returns the full DroneType spec for a given drone instance.
    Used by mission planner and health monitor."""
    return await DroneInstanceService(db).get_type_spec(did)


# ── Naval Vessels ─────────────────────────────────────────────────

@router.get("/vessels", response_model=list[NavalVesselOut])
async def list_vessels(db: DbDep, _: ViewerDep):
    return await NavalVesselService(db).list_active()


@router.get("/vessels/{vid}", response_model=NavalVesselOut)
async def get_vessel(vid: int, db: DbDep, _: ViewerDep):
    return await NavalVesselService(db).get_by_id(vid)


@router.post("/vessels", response_model=NavalVesselOut, status_code=201)
async def create_vessel(body: NavalVesselCreate, db: DbDep, _: AdminDep):
    return await NavalVesselService(db).create(body)


@router.put("/vessels/{vid}", response_model=NavalVesselOut)
async def update_vessel(vid: int, body: NavalVesselUpdate, db: DbDep, _: AdminDep):
    return await NavalVesselService(db).update(vid, body)


@router.post("/vessels/{vid}/position", response_model=NavalVesselOut)
async def update_vessel_position(
    vid: int, body: VesselPositionUpdate, db: DbDep,
    _: Annotated[User, Depends(require_min_role(Role.FLIGHT_CONTROLLER))],
):
    """Update vessel GPS position. Called by the HF position feed ingestor."""
    return await NavalVesselService(db).update_position(vid, body)


@router.post("/vessels/{vid}/assign-drone/{did}", response_model=DroneInstanceOut)
async def assign_drone_to_vessel(vid: int, did: int, db: DbDep, _: AdminDep):
    """Assign a drone instance to a home vessel for ship-based operations."""
    return await NavalVesselService(db).assign_drone(did, vid)


@router.post("/vessels/{vid}/unassign-drone/{did}", response_model=DroneInstanceOut)
async def unassign_drone_from_vessel(vid: int, did: int, db: DbDep, _: AdminDep):
    """Remove a drone's vessel assignment, reverting to fixed home point."""
    return await NavalVesselService(db).unassign_drone(did)


@router.delete("/vessels/{vid}", status_code=204)
async def archive_vessel(vid: int, db: DbDep, _: AdminDep):
    await NavalVesselService(db).archive(vid)