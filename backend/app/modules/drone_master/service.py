"""
Drone Master Service
====================
Business logic layer for Drone Master module.
Routers call into here — never touch the ORM directly from routers.

Responsibilities:
  - Drone type CRUD with business rule enforcement
  - Drone instance lifecycle management
  - Payload compatibility checks
  - Cross-entity validation (e.g. cannot archive a type
    while active drone instances reference it)
"""
import structlog
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from fastapi import HTTPException

from app.models.drone import DroneType, DroneInstance
from app.schemas.drone import (
    DroneTypeCreate, DroneTypeUpdate,
    DroneInstanceCreate, DroneInstanceUpdate,
)

log = structlog.get_logger()


# ── Drone Types ───────────────────────────────────────────────────

class DroneTypeService:

    def __init__(self, db: AsyncSession):
        self.db = db

    async def list_active(self) -> list[DroneType]:
        result = await self.db.execute(
            select(DroneType)
            .where(DroneType.is_active == True)
            .order_by(DroneType.name)
        )
        return result.scalars().all()

    async def get_by_id(self, type_id: int) -> DroneType:
        dt = await self.db.get(DroneType, type_id)
        if not dt or not dt.is_active:
            raise HTTPException(404, f"Drone type #{type_id} not found")
        return dt

    async def create(self, body: DroneTypeCreate) -> DroneType:
        # Enforce unique name
        existing = await self.db.execute(
            select(DroneType).where(
                DroneType.name == body.name,
                DroneType.is_active == True,
            )
        )
        if existing.scalar_one_or_none():
            raise HTTPException(409, f"Drone type '{body.name}' already exists")

        dt = DroneType(**body.model_dump())
        self.db.add(dt)
        await self.db.flush()
        await self.db.refresh(dt)
        log.info("Drone type created", name=dt.name, id=dt.id)
        return dt

    async def update(self, type_id: int, body: DroneTypeUpdate) -> DroneType:
        dt = await self.get_by_id(type_id)

        # If renaming, check no clash with another active type
        if body.name and body.name != dt.name:
            clash = await self.db.execute(
                select(DroneType).where(
                    DroneType.name == body.name,
                    DroneType.id != type_id,
                    DroneType.is_active == True,
                )
            )
            if clash.scalar_one_or_none():
                raise HTTPException(409, f"Drone type '{body.name}' already exists")

        for field, value in body.model_dump(exclude_unset=True).items():
            setattr(dt, field, value)

        await self.db.flush()
        await self.db.refresh(dt)
        log.info("Drone type updated", id=type_id)
        return dt

    async def archive(self, type_id: int) -> None:
        """
        Soft-delete. Blocked if any DroneInstance still references this type
        — master data must never be hard-deleted per spec section 5.7.
        """
        dt = await self.get_by_id(type_id)

        # Check for active instances referencing this type
        count_result = await self.db.execute(
            select(func.count(DroneInstance.id)).where(
                DroneInstance.drone_type_id == type_id
            )
        )
        instance_count = count_result.scalar_one()
        if instance_count > 0:
            raise HTTPException(
                409,
                f"Cannot archive drone type '{dt.name}': "
                f"{instance_count} registered drone(s) still reference it. "
                f"Reassign or deregister them first."
            )

        dt.is_active = False
        await self.db.flush()
        log.info("Drone type archived", name=dt.name, id=type_id)

    async def get_summary_stats(self) -> dict:
        """Quick stats used by the Settings workspace header."""
        total = await self.db.execute(
            select(func.count(DroneType.id)).where(DroneType.is_active == True)
        )
        by_class = await self.db.execute(
            select(DroneType.size_class, func.count(DroneType.id))
            .where(DroneType.is_active == True)
            .group_by(DroneType.size_class)
        )
        return {
            "total_active_types": total.scalar_one(),
            "by_size_class": {row[0]: row[1] for row in by_class.all()},
        }


# ── Drone Instances ───────────────────────────────────────────────

class DroneInstanceService:

    def __init__(self, db: AsyncSession):
        self.db = db

    async def list_all(self) -> list[DroneInstance]:
        result = await self.db.execute(
            select(DroneInstance).order_by(DroneInstance.call_sign)
        )
        return result.scalars().all()

    async def get_by_id(self, drone_id: int) -> DroneInstance:
        inst = await self.db.get(DroneInstance, drone_id)
        if not inst:
            raise HTTPException(404, f"Drone #{drone_id} not found")
        return inst

    async def get_by_call_sign(self, call_sign: str) -> DroneInstance:
        result = await self.db.execute(
            select(DroneInstance).where(
                DroneInstance.call_sign == call_sign.upper()
            )
        )
        inst = result.scalar_one_or_none()
        if not inst:
            raise HTTPException(404, f"Drone '{call_sign}' not found")
        return inst

    async def register(self, body: DroneInstanceCreate) -> DroneInstance:
        # Verify drone type exists and is active
        type_svc = DroneTypeService(self.db)
        await type_svc.get_by_id(body.drone_type_id)   # raises 404 if missing

        # Enforce unique call sign
        clash = await self.db.execute(
            select(DroneInstance).where(
                DroneInstance.call_sign == body.call_sign.upper()
            )
        )
        if clash.scalar_one_or_none():
            raise HTTPException(409, f"Call sign '{body.call_sign}' is already registered")

        # Enforce unique serial number
        serial_clash = await self.db.execute(
            select(DroneInstance).where(
                DroneInstance.serial_number == body.serial_number
            )
        )
        if serial_clash.scalar_one_or_none():
            raise HTTPException(409, f"Serial number '{body.serial_number}' is already registered")

        inst = DroneInstance(**body.model_dump())
        inst.call_sign = inst.call_sign.upper()
        self.db.add(inst)
        await self.db.flush()
        await self.db.refresh(inst)
        log.info("Drone registered", call_sign=inst.call_sign, id=inst.id)
        return inst

    async def update(self, drone_id: int, body: DroneInstanceUpdate) -> DroneInstance:
        inst = await self.get_by_id(drone_id)
        for field, value in body.model_dump(exclude_unset=True).items():
            setattr(inst, field, value)
        await self.db.flush()
        await self.db.refresh(inst)
        return inst

    async def update_status(self, drone_id: int, status: str) -> DroneInstance:
        valid = {"online", "offline", "maintenance", "mission"}
        if status not in valid:
            raise HTTPException(400, f"Status must be one of {valid}")
        inst = await self.get_by_id(drone_id)
        inst.status = status
        await self.db.flush()
        return inst

    async def get_type_spec(self, drone_id: int) -> DroneType:
        """
        Returns the DroneType spec for a given instance.
        Used by HealthMonitor and mission planning to check
        performance limits against actual telemetry.
        """
        inst = await self.get_by_id(drone_id)
        type_svc = DroneTypeService(self.db)
        return await type_svc.get_by_id(inst.drone_type_id)