"""
Vessel Position Feed
====================
Background task that ingests periodic vessel GPS position updates
arriving over the HF link as MAVLink GLOBAL_POSITION_INT messages
with a reserved system ID range (200-239) assigned to naval vessels.

When the HF link carries a position message from a vessel system ID,
this module updates the corresponding NavalVessel record in the DB
so the mission planner always has the current ship position for
dynamic return-to-ship calculations.

Vessel system ID assignment convention:
    system_id 200 → naval_vessel.id 1
    system_id 201 → naval_vessel.id 2
    ...
    system_id 239 → naval_vessel.id 40

This range does not overlap with drone IDs (1–199) or GCS (255).
"""
import asyncio
import structlog
from datetime import datetime, timezone

log = structlog.get_logger()

# system_id → vessel DB primary key mapping (populated at startup from DB)
_vessel_sys_id_map: dict[int, int] = {}

# Registered callback for DB update (injected at startup to avoid circular imports)
_position_update_cb = None


VESSEL_SYS_ID_BASE = 200
VESSEL_SYS_ID_MAX  = 239


def register_update_callback(cb) -> None:
    """
    Register the async callback used to persist vessel positions.
    Called from core/events.py on startup:

        from app.modules.drone_control.vessel_position_feed import register_update_callback

        async def _vessel_position_update(vessel_pk, lat, lon, heading, speed_kts):
            async with get_async_session() as db:
                from app.modules.drone_master.vessel_service import NavalVesselService
                from app.schemas.vessel import VesselPositionUpdate
                await NavalVesselService(db).update_position(
                    vessel_pk,
                    VesselPositionUpdate(latitude=lat, longitude=lon,
                                        heading_deg=heading, speed_kts=speed_kts)
                )
                await db.commit()

        register_update_callback(_vessel_position_update)
    """
    global _position_update_cb
    _position_update_cb = cb


def load_vessel_map(sys_id_to_pk: dict[int, int]) -> None:
    """Populate the system_id → vessel PK lookup from DB at startup."""
    _vessel_sys_id_map.clear()
    _vessel_sys_id_map.update(sys_id_to_pk)


def is_vessel_sys_id(system_id: int) -> bool:
    return VESSEL_SYS_ID_BASE <= system_id <= VESSEL_SYS_ID_MAX


async def handle_position_message(system_id: int, msg) -> None:
    """
    Called by MAVLinkManager._read_loop for any GLOBAL_POSITION_INT message
    whose source system_id falls in the vessel range.

    msg fields (MAVLink GLOBAL_POSITION_INT):
        lat  — degrees × 1e7
        lon  — degrees × 1e7
        hdg  — centidegrees (0–36000, UINT16_MAX if unknown)
        vx   — m/s × 100 (north component)
        vy   — m/s × 100 (east component)
    """
    vessel_pk = _vessel_sys_id_map.get(system_id)
    if vessel_pk is None:
        log.debug("Vessel position from unknown system_id", system_id=system_id)
        return

    lat = msg.lat / 1e7
    lon = msg.lon / 1e7
    heading = (msg.hdg / 100.0) if msg.hdg != 65535 else None

    # Ground speed from vx/vy components (cm/s → knots)
    vx_ms = msg.vx / 100.0
    vy_ms = msg.vy / 100.0
    speed_ms  = (vx_ms**2 + vy_ms**2) ** 0.5
    speed_kts = speed_ms * 1.94384

    log.debug("Vessel position update", vessel_pk=vessel_pk,
              lat=round(lat, 6), lon=round(lon, 6),
              heading=heading, speed_kts=round(speed_kts, 1))

    if _position_update_cb:
        try:
            await _position_update_cb(vessel_pk, lat, lon, heading, speed_kts)
        except Exception as e:
            log.error("Vessel position DB update failed", vessel_pk=vessel_pk, error=str(e))
