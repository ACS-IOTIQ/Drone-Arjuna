"""
Drone Inventory Service
=======================
Business logic for the Drone Inventory knowledge base module.

V1 scope:
  - Wraps Drone Master data (DroneType, DroneInstance) and enriches
    it with formatted display structures for the Inventory UI.
  - Provides comparison and quick-reference card endpoints.
  - All heavy content (rich HTML pages, user contributions,
    Elasticsearch full-text search) is deferred to V2.

V2 will replace the lightweight wrappers here with:
  - Elasticsearch-backed full-text search across article content
  - CMS workflow (draft → review → publish) for contributed articles
  - Rich HTML5 formatted drone/payload detail pages
  - Comparative analysis (side-by-side spec charts)
"""
import structlog
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from fastapi import HTTPException

from app.models.drone import DroneType, DroneInstance

log = structlog.get_logger()


class InventoryService:

    def __init__(self, db: AsyncSession):
        self.db = db

    # ── Drone catalogue ───────────────────────────────────────────

    async def list_drones(
        self,
        size_class: str | None = None,
        mission_type: str | None = None,
        autopilot: str | None = None,
    ) -> list[dict]:
        """
        Returns enriched drone type cards for the Inventory listing view.
        Filters are optional facets — V2 will push these into Elasticsearch.
        """
        q = select(DroneType).where(DroneType.is_active == True)
        if size_class:
            q = q.where(DroneType.size_class == size_class)
        if mission_type:
            q = q.where(DroneType.mission_type == mission_type)
        if autopilot:
            q = q.where(DroneType.autopilot_type == autopilot)

        result = await self.db.execute(q.order_by(DroneType.name))
        types = result.scalars().all()
        return [self._drone_card(dt) for dt in types]

    async def get_drone_detail(self, type_id: int) -> dict:
        """
        Full detail view for a single drone type.
        In V1 this is a structured dict; V2 will return rich HTML.
        """
        dt = await self.db.get(DroneType, type_id)
        if not dt or not dt.is_active:
            raise HTTPException(404, f"Drone type #{type_id} not found in inventory")

        # Count registered instances of this type
        instances_result = await self.db.execute(
            select(DroneInstance).where(DroneInstance.drone_type_id == type_id)
        )
        instances = instances_result.scalars().all()

        return {
            **self._drone_card(dt),
            "performance": {
                "max_speed_ms":      dt.max_speed_ms,
                "cruise_speed_ms":   dt.cruise_speed_ms,
                "max_altitude_m":    dt.max_altitude_m,
                "endurance_h":       dt.endurance_h,
                "range_km":          dt.range_km,
            },
            "physical": {
                "max_takeoff_weight_kg":  dt.max_takeoff_weight_kg,
                "max_payload_weight_kg":  dt.max_payload_weight_kg,
                "is_vtol":                dt.is_vtol,
            },
            "registered_instances": [
                {
                    "id":         i.id,
                    "call_sign":  i.call_sign,
                    "status":     i.status,
                    "flight_hours": i.total_flight_hours,
                }
                for i in instances
            ],
            "notes": dt.notes,
        }

    async def compare_drones(self, type_ids: list[int]) -> dict:
        """
        Side-by-side comparison of up to 4 drone types.
        Returns a structured table the frontend can render directly.
        """
        if len(type_ids) < 2:
            raise HTTPException(400, "Provide at least 2 drone type IDs to compare")
        if len(type_ids) > 4:
            raise HTTPException(400, "Maximum 4 drone types can be compared at once")

        types = []
        for tid in type_ids:
            dt = await self.db.get(DroneType, tid)
            if not dt or not dt.is_active:
                raise HTTPException(404, f"Drone type #{tid} not found")
            types.append(dt)

        # Build comparison matrix
        metrics = [
            ("max_speed_ms",            "Max Speed",      "m/s"),
            ("cruise_speed_ms",         "Cruise Speed",   "m/s"),
            ("max_altitude_m",          "Max Altitude",   "m"),
            ("endurance_h",             "Endurance",      "h"),
            ("range_km",                "Range",          "km"),
            ("max_takeoff_weight_kg",   "Max Takeoff Wt", "kg"),
            ("max_payload_weight_kg",   "Max Payload Wt", "kg"),
        ]

        rows = []
        for attr, label, unit in metrics:
            values = [getattr(dt, attr) for dt in types]
            best_idx = values.index(max(values))
            rows.append({
                "metric":    label,
                "unit":      unit,
                "values":    values,
                "best_idx":  best_idx,   # frontend highlights winner
            })

        return {
            "drones":  [{"id": dt.id, "name": dt.name, "manufacturer": dt.manufacturer}
                        for dt in types],
            "metrics": rows,
        }

    # ── Search (V1 lightweight, V2 Elasticsearch) ─────────────────

    async def search(self, query: str, limit: int = 20) -> dict:
        """
        V1: Simple SQL ILIKE search across name, manufacturer, model, notes.
        V2: Replace this entire method body with an Elasticsearch query.
        """
        if not query.strip():
            return {"results": [], "query": query, "total": 0}

        pattern = f"%{query.strip()}%"
        q = (
            select(DroneType)
            .where(DroneType.is_active == True)
            .where(
                DroneType.name.ilike(pattern)
                | DroneType.manufacturer.ilike(pattern)
                | DroneType.model.ilike(pattern)
                | DroneType.mission_type.ilike(pattern)
                | DroneType.notes.ilike(pattern)
            )
            .limit(limit)
        )
        result = await self.db.execute(q)
        types = result.scalars().all()

        return {
            "query":   query,
            "total":   len(types),
            "results": [self._drone_card(dt) for dt in types],
            "note":    "V1 SQL search — full-text Elasticsearch search available in V2",
        }

    # ── Quick-reference card ──────────────────────────────────────

    async def quick_reference(self, type_id: int) -> dict:
        """
        Compact spec card embedded in the Mission Planning panel
        when an operator selects a drone for a mission.
        """
        dt = await self.db.get(DroneType, type_id)
        if not dt:
            raise HTTPException(404, f"Drone type #{type_id} not found")
        return {
            "id":           dt.id,
            "name":         dt.name,
            "size_class":   dt.size_class,
            "mission_type": dt.mission_type,
            "autopilot":    dt.autopilot_type,
            "key_specs": {
                "endurance_h":    dt.endurance_h,
                "range_km":       dt.range_km,
                "max_altitude_m": dt.max_altitude_m,
                "cruise_speed_ms": dt.cruise_speed_ms,
                "max_payload_kg": dt.max_payload_weight_kg,
            },
        }

    # ── Internal helpers ──────────────────────────────────────────

    @staticmethod
    def _drone_card(dt: DroneType) -> dict:
        """Minimal card dict used in list views."""
        return {
            "id":           dt.id,
            "name":         dt.name,
            "manufacturer": dt.manufacturer,
            "model":        dt.model,
            "size_class":   dt.size_class,
            "mission_type": dt.mission_type,
            "autopilot":    dt.autopilot_type,
            "is_vtol":      dt.is_vtol,
            "max_speed_ms": dt.max_speed_ms,
            "endurance_h":  dt.endurance_h,
            "range_km":     dt.range_km,
        }