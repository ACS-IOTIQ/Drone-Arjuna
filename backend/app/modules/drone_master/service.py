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
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from fastapi import HTTPException

from app.models.drone import DroneType, DroneInstance, DroneConfigTemplate
from app.schemas.drone import (
    DroneTypeCreate, DroneTypeUpdate,
    DroneInstanceCreate, DroneInstanceUpdate,
    DroneConfigTemplateCreate, DroneConfigTemplateUpdate,
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


# ── Config Templates ──────────────────────────────────────────────

class DroneConfigTemplateService:

    def __init__(self, db: AsyncSession):
        self.db = db

    async def list_active(self, drone_type_id: int | None = None) -> list[DroneConfigTemplate]:
        q = select(DroneConfigTemplate).where(DroneConfigTemplate.is_active == True)
        if drone_type_id is not None:
            q = q.where(DroneConfigTemplate.drone_type_id == drone_type_id)
        result = await self.db.execute(q.order_by(DroneConfigTemplate.name))
        return result.scalars().all()

    async def get_by_id(self, tid: int) -> DroneConfigTemplate:
        ct = await self.db.get(DroneConfigTemplate, tid)
        if not ct or not ct.is_active:
            raise HTTPException(404, f"Config template #{tid} not found")
        return ct

    async def create(self, body: DroneConfigTemplateCreate) -> DroneConfigTemplate:
        # Verify drone type exists
        dt = await self.db.get(DroneType, body.drone_type_id)
        if not dt or not dt.is_active:
            raise HTTPException(404, f"Drone type #{body.drone_type_id} not found")

        # Enforce unique name
        clash = await self.db.execute(
            select(DroneConfigTemplate).where(
                DroneConfigTemplate.name == body.name,
                DroneConfigTemplate.is_active == True,
            )
        )
        if clash.scalar_one_or_none():
            raise HTTPException(409, f"Config template '{body.name}' already exists")

        ct = DroneConfigTemplate(**body.model_dump())
        self.db.add(ct)
        await self.db.flush()
        await self.db.refresh(ct)
        log.info("Config template created", name=ct.name, id=ct.id)
        return ct

    async def update(self, tid: int, body: DroneConfigTemplateUpdate) -> DroneConfigTemplate:
        ct = await self.get_by_id(tid)

        # If drone_type_id is being changed, verify new type exists
        if body.drone_type_id is not None and body.drone_type_id != ct.drone_type_id:
            dt = await self.db.get(DroneType, body.drone_type_id)
            if not dt or not dt.is_active:
                raise HTTPException(404, f"Drone type #{body.drone_type_id} not found")

        for field, value in body.model_dump(exclude_unset=True).items():
            setattr(ct, field, value)
        ct.updated_at = datetime.now(timezone.utc)

        await self.db.flush()
        await self.db.refresh(ct)
        log.info("Config template updated", id=tid)
        return ct

    async def archive(self, tid: int) -> None:
        ct = await self.get_by_id(tid)
        ct.is_active = False
        await self.db.flush()
        log.info("Config template archived", id=tid)

    async def apply(self, tid: int, drone_id: int) -> dict:
        ct = await self.get_by_id(tid)
        drone = await self.db.get(DroneInstance, drone_id)
        if not drone:
            raise HTTPException(404, f"Drone #{drone_id} not found")

        if drone.drone_type_id != ct.drone_type_id:
            raise HTTPException(
                422,
                f"Template is for drone type #{ct.drone_type_id} but drone is "
                f"type #{drone.drone_type_id}. Type must match."
            )

        log.info("Config template applied", template_id=tid, drone_id=drone_id)
        return {
            "template_id": tid,
            "drone_id": drone_id,
            "settings": ct.settings,
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