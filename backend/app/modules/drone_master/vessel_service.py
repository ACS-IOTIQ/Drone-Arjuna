"""
Naval Vessel Service
====================
CRUD and position management for naval vessels acting as floating home bases.
"""
from datetime import datetime, timezone
import structlog
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from fastapi import HTTPException

from app.models.vessel import NavalVessel
from app.models.drone import DroneInstance
from app.schemas.vessel import NavalVesselCreate, NavalVesselUpdate, VesselPositionUpdate

log = structlog.get_logger()


class NavalVesselService:

    def __init__(self, db: AsyncSession):
        self.db = db

    async def list_active(self) -> list[NavalVessel]:
        result = await self.db.execute(
            select(NavalVessel)
            .where(NavalVessel.is_active == True)
            .order_by(NavalVessel.vessel_id)
        )
        return result.scalars().all()

    async def get_by_id(self, vessel_id: int) -> NavalVessel:
        v = await self.db.get(NavalVessel, vessel_id)
        if not v or not v.is_active:
            raise HTTPException(404, f"Naval vessel #{vessel_id} not found")
        return v

    async def get_by_vessel_id(self, vessel_id: str) -> NavalVessel:
        result = await self.db.execute(
            select(NavalVessel).where(
                NavalVessel.vessel_id == vessel_id.upper(),
                NavalVessel.is_active == True,
            )
        )
        v = result.scalar_one_or_none()
        if not v:
            raise HTTPException(404, f"Naval vessel '{vessel_id}' not found")
        return v

    async def create(self, body: NavalVesselCreate) -> NavalVessel:
        clash = await self.db.execute(
            select(NavalVessel).where(
                NavalVessel.vessel_id == body.vessel_id.upper(),
                NavalVessel.is_active == True,
            )
        )
        if clash.scalar_one_or_none():
            raise HTTPException(409, f"Vessel ID '{body.vessel_id}' already exists")

        data = body.model_dump()
        data["vessel_id"] = data["vessel_id"].upper()
        v = NavalVessel(**data)
        self.db.add(v)
        await self.db.flush()
        await self.db.refresh(v)
        log.info("Naval vessel created", vessel_id=v.vessel_id, id=v.id)
        return v

    async def update(self, pk: int, body: NavalVesselUpdate) -> NavalVessel:
        v = await self.get_by_id(pk)
        for field, value in body.model_dump(exclude_unset=True).items():
            setattr(v, field, value)
        await self.db.flush()
        await self.db.refresh(v)
        log.info("Naval vessel updated", id=pk)
        return v

    async def update_position(self, pk: int, pos: VesselPositionUpdate) -> NavalVessel:
        """
        Update vessel GPS position from the HF position feed.
        Called by the vessel_position_feed background task and exposed as
        a POST endpoint for manual/test updates.
        """
        v = await self.get_by_id(pk)
        v.latitude           = pos.latitude
        v.longitude          = pos.longitude
        if pos.heading_deg is not None:
            v.heading_deg    = pos.heading_deg
        if pos.speed_kts is not None:
            v.speed_kts      = pos.speed_kts
        v.position_updated_at = datetime.now(timezone.utc)
        await self.db.flush()
        return v

    async def assign_drone(self, drone_pk: int, vessel_pk: int) -> DroneInstance:
        """Assign a drone instance to a home vessel."""
        drone = await self.db.get(DroneInstance, drone_pk)
        if not drone:
            raise HTTPException(404, f"Drone #{drone_pk} not found")
        await self.get_by_id(vessel_pk)  # raises 404 if vessel missing
        drone.home_vessel_id = vessel_pk
        await self.db.flush()
        log.info("Drone assigned to vessel", drone_id=drone_pk, vessel_id=vessel_pk)
        return drone

    async def unassign_drone(self, drone_pk: int) -> DroneInstance:
        """Remove a drone's vessel assignment (back to fixed home point)."""
        drone = await self.db.get(DroneInstance, drone_pk)
        if not drone:
            raise HTTPException(404, f"Drone #{drone_pk} not found")
        drone.home_vessel_id = None
        await self.db.flush()
        return drone

    async def archive(self, pk: int) -> None:
        v = await self.get_by_id(pk)
        # Check no drones are still assigned
        result = await self.db.execute(
            select(DroneInstance).where(DroneInstance.home_vessel_id == pk)
        )
        assigned = result.scalars().all()
        if assigned:
            call_signs = ", ".join(d.call_sign for d in assigned)
            raise HTTPException(
                409,
                f"Cannot archive vessel '{v.vessel_id}': "
                f"drones [{call_signs}] are still assigned. Reassign them first."
            )
        v.is_active = False
        await self.db.flush()
        log.info("Naval vessel archived", vessel_id=v.vessel_id, id=pk)
