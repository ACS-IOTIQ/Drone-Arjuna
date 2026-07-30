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
from datetime import datetime, timedelta, timezone
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, delete, update
from fastapi import HTTPException

from app.models.drone import DroneType, DroneInstance, DroneConfigTemplate
from app.models.mission import Mission
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
        """Permanently delete a type and every registered drone using it."""
        dt = await self.get_by_id(type_id)

        instance_result = await self.db.execute(
            select(DroneInstance.id).where(DroneInstance.drone_type_id == type_id)
        )
        instance_ids = list(instance_result.scalars().all())

        if instance_ids:
            # Keep mission history, but remove references to drones being deleted.
            await self.db.execute(
                update(Mission)
                .where(Mission.drone_instance_id.in_(instance_ids))
                .values(drone_instance_id=None)
            )
            await self.db.execute(
                delete(DroneInstance).where(DroneInstance.id.in_(instance_ids))
            )

        await self.db.execute(
            delete(DroneConfigTemplate).where(DroneConfigTemplate.drone_type_id == type_id)
        )
        await self.db.delete(dt)
        await self.db.flush()
        log.info("Drone type permanently deleted", name=dt.name, id=type_id,
                 deleted_instances=len(instance_ids))

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

    STALE_AFTER_DAYS = 30

    def __init__(self, db: AsyncSession):
        self.db = db

    async def list_all(self) -> list[DroneInstance]:
        result = await self.db.execute(
            select(DroneInstance)
            .where(DroneInstance.is_active == True)  # noqa: E712
            .order_by(DroneInstance.last_seen.desc().nullslast(), DroneInstance.call_sign)
        )
        return result.scalars().all()

    async def get_by_id(self, drone_id: int) -> DroneInstance:
        inst = await self.db.get(DroneInstance, drone_id)
        if not inst or not inst.is_active:
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

        # MAVLink identifies vehicles by system_id, not by our drone_instance_id —
        # two drones sharing one (e.g. both left at the schema default of 1) show
        # up as a single merged/overwritten vehicle in any external GCS (Mission
        # Planner, QGroundControl) once both are connected/simulating at once.
        existing_ids = {
            row[0] for row in
            (await self.db.execute(select(DroneInstance.mavlink_system_id))).all()
            if row[0] is not None
        }
        if inst.mavlink_system_id in existing_ids:
            next_id = max(existing_ids, default=0) + 1
            while next_id in existing_ids:
                next_id += 1
            log.warning(
                "mavlink_system_id collision on registration — reassigning",
                call_sign=inst.call_sign, requested=inst.mavlink_system_id, assigned=next_id,
            )
            inst.mavlink_system_id = next_id

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

    async def mark_used(self, drone_id: int) -> DroneInstance:
        """Record a confirmed connection or flight as real drone activity."""
        inst = await self.get_by_id(drone_id)
        inst.last_seen = datetime.now(timezone.utc)
        await self.db.flush()
        return inst

    async def archive_if_stale(self, drone_id: int) -> dict:
        """Soft-remove a drone only after 30 full days without confirmed use."""
        inst = await self.get_by_id(drone_id)

        try:
            from app.modules.drone_control.mavlink_manager import mavlink_manager
            connection = mavlink_manager._connections.get(drone_id)
            if connection and connection.connected:
                raise HTTPException(409, "A connected drone cannot be removed")
        except HTTPException:
            raise
        except Exception:
            # Runtime connection state may be unavailable during maintenance jobs;
            # the persisted activity check below still protects recent drones.
            pass

        last_activity = inst.last_seen or inst.created_at
        if last_activity is not None and last_activity.tzinfo is None:
            # SQLite-based tests and some legacy rows can return naive values.
            last_activity = last_activity.replace(tzinfo=timezone.utc)
        cutoff = datetime.now(timezone.utc) - timedelta(days=self.STALE_AFTER_DAYS)
        if last_activity is None or last_activity > cutoff:
            raise HTTPException(
                409,
                f"Drone can be removed from Fleet Overview only after "
                f"{self.STALE_AFTER_DAYS} days without use",
            )

        return await self.archive(drone_id)

    async def get_type_spec(self, drone_id: int) -> DroneType:
        """
        Returns the DroneType spec for a given instance.
        Used by HealthMonitor and mission planning to check
        performance limits against actual telemetry.
        """
        inst = await self.get_by_id(drone_id)
        type_svc = DroneTypeService(self.db)
        return await type_svc.get_by_id(inst.drone_type_id)

    async def archive(self, drone_id: int) -> dict:
        """
        Soft-delete (removes it from the registered-drone list). Master data
        must never be hard-deleted per spec section 5.7 — so instead of
        blocking on referencing missions, this unassigns the drone from
        them (mission rows are kept, just detached) and stops any live
        simulation/connection first, then removes the drone.
        """
        inst = await self.get_by_id(drone_id)

        # Stop a live simulation/connection first, if any, so we don't
        # remove a drone out from under an active flight.
        try:
            from app.modules.drone_control.mavlink_manager import mavlink_manager
            from app.modules.drone_control.mission_simulator import mission_simulator
            if mission_simulator.is_active(drone_id):
                await mission_simulator.stop(drone_id)
            mavlink_manager.detach_simulation(drone_id)
            await mavlink_manager.disconnect(drone_id)
        except Exception:
            pass  # best-effort — never block removal on live-state cleanup

        # Unassign (not delete) any missions that reference this drone
        unassign_result = await self.db.execute(
            select(Mission).where(Mission.drone_instance_id == drone_id)
        )
        missions = unassign_result.scalars().all()
        for m in missions:
            m.drone_instance_id = None

        inst.is_active = False
        await self.db.flush()
        log.info("Drone removed", call_sign=inst.call_sign, id=drone_id,
                 unassigned_missions=len(missions))
        return {"unassigned_missions": len(missions)}

    async def assign_payload(self, drone_id: int, payload_type_id: int | None) -> DroneInstance:
        """
        Attach or detach a payload type from a drone instance.
        Pass payload_type_id=None to clear the current payload.
        Validates that the payload type exists when assigning.
        """
        from app.models.payload import PayloadType
        inst = await self.get_by_id(drone_id)
        if payload_type_id is not None:
            pt = await self.db.get(PayloadType, payload_type_id)
            if pt is None or not pt.is_active:
                raise HTTPException(404, f"Payload type #{payload_type_id} not found")
        inst.payload_type_id = payload_type_id
        await self.db.flush()
        action = f"payload_type_id={payload_type_id}" if payload_type_id else "cleared"
        log.info("drone_instance.payload_updated", id=drone_id, call_sign=inst.call_sign, payload=action)
        return inst


# ── Config Template helpers ───────────────────────────────────────

def _validate_settings_vs_type(settings: dict, drone_type: DroneType) -> None:
    """
    Raise 422 if any setting exceeds the drone type's physical limits.
    Called on both create and update so limits are always enforced.
    """
    errors: list[str] = []
    m  = settings.get("mavlink", {})
    g  = settings.get("geofence", {})
    ms = settings.get("mission", {})

    ceiling = drone_type.max_altitude_m
    top_spd = drone_type.max_speed_ms

    if (v := m.get("rtl_altitude_m")) and v > ceiling:
        errors.append(f"mavlink.rtl_altitude_m {v} m exceeds type ceiling {ceiling} m")
    if (v := m.get("wpnav_speed_ms")) and v > top_spd:
        errors.append(f"mavlink.wpnav_speed_ms {v} m/s exceeds type max {top_spd} m/s")
    if (v := g.get("alt_max_m")) and v > ceiling:
        errors.append(f"geofence.alt_max_m {v} m exceeds type ceiling {ceiling} m")
    if (v := ms.get("max_waypoint_alt_m")) and v > ceiling:
        errors.append(f"mission.max_waypoint_alt_m {v} m exceeds type ceiling {ceiling} m")
    if (v := ms.get("default_cruise_speed_ms")) and v > top_spd:
        errors.append(f"mission.default_cruise_speed_ms {v} m/s exceeds type max {top_spd} m/s")

    if errors:
        raise HTTPException(422, "; ".join(errors))


# ── Config Templates ──────────────────────────────────────────────

class DroneConfigTemplateService:
    """
    CRUD for DroneConfigTemplate.
    Templates are soft-deleted (is_active flag) so historical references
    from drone instances are preserved per spec section 5.7.
    """

    def __init__(self, db: AsyncSession):
        self.db = db

    async def list_active(
        self, drone_type_id: Optional[int] = None
    ) -> list[DroneConfigTemplate]:
        q = (
            select(DroneConfigTemplate)
            .where(DroneConfigTemplate.is_active == True)
            .order_by(DroneConfigTemplate.name)
        )
        if drone_type_id is not None:
            q = q.where(DroneConfigTemplate.drone_type_id == drone_type_id)
        result = await self.db.execute(q)
        return result.scalars().all()

    async def get_by_id(self, tid: int) -> DroneConfigTemplate:
        t = await self.db.get(DroneConfigTemplate, tid)
        if not t or not t.is_active:
            raise HTTPException(404, f"Config template #{tid} not found")
        return t

    async def create(self, body: DroneConfigTemplateCreate) -> DroneConfigTemplate:
        # Verify the target drone type exists and is active
        dt = await self.db.get(DroneType, body.drone_type_id)
        if not dt or not dt.is_active:
            raise HTTPException(404, f"Drone type #{body.drone_type_id} not found")

        # Compact serialise (exclude None values) then validate against type limits
        settings_dict = body.settings.model_dump(exclude_none=True)
        _validate_settings_vs_type(settings_dict, dt)

        # Unique name (active templates only — allows reuse of archived names)
        existing = await self.db.execute(
            select(DroneConfigTemplate).where(
                DroneConfigTemplate.name == body.name,
                DroneConfigTemplate.is_active == True,
            )
        )
        if existing.scalar_one_or_none():
            raise HTTPException(409, f"Config template '{body.name}' already exists")

        dump = body.model_dump()
        dump["settings"] = settings_dict
        t = DroneConfigTemplate(**dump)
        self.db.add(t)
        await self.db.flush()
        await self.db.refresh(t)
        log.info("config_template.created", id=t.id, name=t.name,
                 drone_type_id=t.drone_type_id)
        return t

    async def update(
        self, tid: int, body: DroneConfigTemplateUpdate
    ) -> DroneConfigTemplate:
        t = await self.get_by_id(tid)
        update_data = body.model_dump(exclude_unset=True)

        # Resolve the drone type that will apply after the update and validate
        if "drone_type_id" in update_data or "settings" in update_data:
            effective_type_id = update_data.get("drone_type_id", t.drone_type_id)
            dt = await self.db.get(DroneType, effective_type_id)
            if not dt or not dt.is_active:
                raise HTTPException(404, f"Drone type #{effective_type_id} not found")

            if "settings" in update_data and body.settings is not None:
                settings_dict = body.settings.model_dump(exclude_none=True)
                _validate_settings_vs_type(settings_dict, dt)
                update_data["settings"] = settings_dict

        for field, value in update_data.items():
            setattr(t, field, value)
        t.updated_at = datetime.now(timezone.utc)

        await self.db.flush()
        await self.db.refresh(t)
        log.info("config_template.updated", id=tid)
        return t

    async def archive(self, tid: int) -> None:
        t = await self.get_by_id(tid)
        t.is_active = False
        await self.db.flush()
        log.info("config_template.archived", id=tid, name=t.name)

    async def apply_to_drone(self, tid: int, drone_id: int) -> dict:
        """
        Validates template–drone compatibility and returns the resolved
        settings dict. The caller (router or frontend) is responsible for
        pushing the settings to the drone via MAVLink.
        """
        t = await self.get_by_id(tid)
        drone = await self.db.get(DroneInstance, drone_id)
        if not drone:
            raise HTTPException(404, f"Drone instance #{drone_id} not found")

        if drone.drone_type_id != t.drone_type_id:
            raise HTTPException(
                422,
                f"Template '{t.name}' is for drone type #{t.drone_type_id} but "
                f"drone '{drone.call_sign}' is type #{drone.drone_type_id}",
            )

        return {
            "template_id":   t.id,
            "template_name": t.name,
            "drone_id":      drone_id,
            "call_sign":     drone.call_sign,
            "settings":      t.settings,
        }
