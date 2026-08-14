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
import asyncio
import structlog
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from fastapi import HTTPException

from app.models.drone import DroneType, DroneInstance
from app.models.payload import PayloadType
from app.models.threat import ThreatSystem
from app.models.inventory_link import DronePayloadLink, DroneThreatLink, PayloadThreatLink

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
        if not query.strip():
            return {"results": [], "query": query, "total": 0}

        # V2: Elasticsearch full-text search (P4-06)
        try:
            from app.core.search import search_inventory
            results = await search_inventory(query, limit)
            if results:
                return {"query": query, "total": len(results), "results": results}
        except Exception:
            pass

        # V1 SQL ILIKE fallback — used when ES unavailable or returns nothing
        pattern = f"%{query.strip()}%"
        drone_q = (
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
        payload_q = (
            select(PayloadType)
            .where(PayloadType.is_active == True)
            .where(
                PayloadType.name.ilike(pattern)
                | PayloadType.manufacturer.ilike(pattern)
                | PayloadType.model.ilike(pattern)
                | PayloadType.notes.ilike(pattern)
            )
            .limit(limit)
        )
        drone_result = await self.db.execute(drone_q)
        payload_result = await self.db.execute(payload_q)
        drones = drone_result.scalars().all()
        payloads = payload_result.scalars().all()
        results = (
            [{"type": "drone",   **self._drone_card(dt)} for dt in drones]
            + [{"type": "payload", **self._payload_card(pt)} for pt in payloads]
        )
        return {"query": query, "total": len(results), "results": results}

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

    # ── Threat system CRUD ────────────────────────────────────────

    async def list_threats(
        self,
        category: str | None = None,
        country: str | None = None,
    ) -> list[dict]:
        q = select(ThreatSystem).order_by(ThreatSystem.name)
        if category:
            q = q.where(ThreatSystem.category == category)
        if country:
            q = q.where(ThreatSystem.country == country)
        result = await self.db.execute(q)
        return [self._threat_card(t) for t in result.scalars().all()]

    async def get_threat(self, threat_id: int) -> dict:
        ts = await self.db.get(ThreatSystem, threat_id)
        if not ts:
            raise HTTPException(404, f"Threat system #{threat_id} not found")
        return self._threat_card(ts)

    async def create_threat(self, data: dict) -> dict:
        from app.core.search import index_threat_system
        existing = await self.db.execute(
            select(ThreatSystem).where(ThreatSystem.name == data["name"])
        )
        if existing.scalar_one_or_none():
            raise HTTPException(409, f"Threat system '{data['name']}' already exists")
        ts = ThreatSystem(**data)
        self.db.add(ts)
        await self.db.flush()
        await self.db.refresh(ts)
        card = self._threat_card(ts)
        asyncio.create_task(index_threat_system(card))
        return card

    async def update_threat(self, threat_id: int, data: dict) -> dict:
        from app.core.search import index_threat_system
        ts = await self.db.get(ThreatSystem, threat_id)
        if not ts:
            raise HTTPException(404, f"Threat system #{threat_id} not found")
        for key, value in data.items():
            setattr(ts, key, value)
        await self.db.flush()
        await self.db.refresh(ts)
        card = self._threat_card(ts)
        asyncio.create_task(index_threat_system(card))
        return card

    async def delete_threat(self, threat_id: int) -> None:
        from app.core.search import delete_document, INDEX_THREAT
        ts = await self.db.get(ThreatSystem, threat_id)
        if not ts:
            raise HTTPException(404, f"Threat system #{threat_id} not found")
        doc_id = ts.id
        await self.db.delete(ts)
        asyncio.create_task(delete_document(INDEX_THREAT, doc_id))
        await self.db.flush()

    # ── Inventory links: drone <-> payload <-> threat ──────────────

    async def _get_or_404(self, model, obj_id: int, label: str):
        obj = await self.db.get(model, obj_id)
        if not obj:
            raise HTTPException(404, f"{label} #{obj_id} not found")
        return obj

    # -- drone <-> payload --

    async def create_drone_payload_link(self, data: dict) -> DronePayloadLink:
        await self._get_or_404(DroneType, data["drone_type_id"], "Drone type")
        await self._get_or_404(PayloadType, data["payload_type_id"], "Payload type")
        existing = await self.db.execute(
            select(DronePayloadLink).where(
                DronePayloadLink.drone_type_id == data["drone_type_id"],
                DronePayloadLink.payload_type_id == data["payload_type_id"],
            )
        )
        if existing.scalar_one_or_none():
            raise HTTPException(409, "Link between this drone type and payload type already exists")
        link = DronePayloadLink(**data)
        self.db.add(link)
        await self.db.flush()
        await self.db.refresh(link)
        return link

    async def update_drone_payload_link(self, link_id: int, data: dict) -> DronePayloadLink:
        link = await self._get_or_404(DronePayloadLink, link_id, "Drone-payload link")
        for key, value in data.items():
            setattr(link, key, value)
        await self.db.flush()
        await self.db.refresh(link)
        return link

    async def delete_drone_payload_link(self, link_id: int) -> None:
        link = await self._get_or_404(DronePayloadLink, link_id, "Drone-payload link")
        await self.db.delete(link)
        await self.db.flush()

    async def list_payloads_for_drone(self, drone_type_id: int) -> list[dict]:
        await self._get_or_404(DroneType, drone_type_id, "Drone type")
        result = await self.db.execute(
            select(DronePayloadLink, PayloadType)
            .join(PayloadType, PayloadType.id == DronePayloadLink.payload_type_id)
            .where(DronePayloadLink.drone_type_id == drone_type_id)
        )
        return [
            {**self._link_card(link), "payload": self._payload_card(pt)}
            for link, pt in result.all()
        ]

    async def list_drones_for_payload(self, payload_type_id: int) -> list[dict]:
        await self._get_or_404(PayloadType, payload_type_id, "Payload type")
        result = await self.db.execute(
            select(DronePayloadLink, DroneType)
            .join(DroneType, DroneType.id == DronePayloadLink.drone_type_id)
            .where(DronePayloadLink.payload_type_id == payload_type_id)
        )
        return [
            {**self._link_card(link), "drone": self._drone_card(dt)}
            for link, dt in result.all()
        ]

    # -- drone <-> threat --

    async def create_drone_threat_link(self, data: dict) -> DroneThreatLink:
        await self._get_or_404(DroneType, data["drone_type_id"], "Drone type")
        await self._get_or_404(ThreatSystem, data["threat_system_id"], "Threat system")
        existing = await self.db.execute(
            select(DroneThreatLink).where(
                DroneThreatLink.drone_type_id == data["drone_type_id"],
                DroneThreatLink.threat_system_id == data["threat_system_id"],
            )
        )
        if existing.scalar_one_or_none():
            raise HTTPException(409, "Link between this drone type and threat system already exists")
        link = DroneThreatLink(**data)
        self.db.add(link)
        await self.db.flush()
        await self.db.refresh(link)
        return link

    async def update_drone_threat_link(self, link_id: int, data: dict) -> DroneThreatLink:
        link = await self._get_or_404(DroneThreatLink, link_id, "Drone-threat link")
        for key, value in data.items():
            setattr(link, key, value)
        await self.db.flush()
        await self.db.refresh(link)
        return link

    async def delete_drone_threat_link(self, link_id: int) -> None:
        link = await self._get_or_404(DroneThreatLink, link_id, "Drone-threat link")
        await self.db.delete(link)
        await self.db.flush()

    async def list_threats_for_drone(self, drone_type_id: int) -> list[dict]:
        await self._get_or_404(DroneType, drone_type_id, "Drone type")
        result = await self.db.execute(
            select(DroneThreatLink, ThreatSystem)
            .join(ThreatSystem, ThreatSystem.id == DroneThreatLink.threat_system_id)
            .where(DroneThreatLink.drone_type_id == drone_type_id)
        )
        return [
            {**self._link_card(link), "threat": self._threat_card(ts)}
            for link, ts in result.all()
        ]

    async def list_drones_for_threat(self, threat_system_id: int) -> list[dict]:
        await self._get_or_404(ThreatSystem, threat_system_id, "Threat system")
        result = await self.db.execute(
            select(DroneThreatLink, DroneType)
            .join(DroneType, DroneType.id == DroneThreatLink.drone_type_id)
            .where(DroneThreatLink.threat_system_id == threat_system_id)
        )
        return [
            {**self._link_card(link), "drone": self._drone_card(dt)}
            for link, dt in result.all()
        ]

    # -- payload <-> threat --

    async def create_payload_threat_link(self, data: dict) -> PayloadThreatLink:
        await self._get_or_404(PayloadType, data["payload_type_id"], "Payload type")
        await self._get_or_404(ThreatSystem, data["threat_system_id"], "Threat system")
        existing = await self.db.execute(
            select(PayloadThreatLink).where(
                PayloadThreatLink.payload_type_id == data["payload_type_id"],
                PayloadThreatLink.threat_system_id == data["threat_system_id"],
            )
        )
        if existing.scalar_one_or_none():
            raise HTTPException(409, "Link between this payload type and threat system already exists")
        link = PayloadThreatLink(**data)
        self.db.add(link)
        await self.db.flush()
        await self.db.refresh(link)
        return link

    async def update_payload_threat_link(self, link_id: int, data: dict) -> PayloadThreatLink:
        link = await self._get_or_404(PayloadThreatLink, link_id, "Payload-threat link")
        for key, value in data.items():
            setattr(link, key, value)
        await self.db.flush()
        await self.db.refresh(link)
        return link

    async def delete_payload_threat_link(self, link_id: int) -> None:
        link = await self._get_or_404(PayloadThreatLink, link_id, "Payload-threat link")
        await self.db.delete(link)
        await self.db.flush()

    async def list_threats_for_payload(self, payload_type_id: int) -> list[dict]:
        await self._get_or_404(PayloadType, payload_type_id, "Payload type")
        result = await self.db.execute(
            select(PayloadThreatLink, ThreatSystem)
            .join(ThreatSystem, ThreatSystem.id == PayloadThreatLink.threat_system_id)
            .where(PayloadThreatLink.payload_type_id == payload_type_id)
        )
        return [
            {**self._link_card(link), "threat": self._threat_card(ts)}
            for link, ts in result.all()
        ]

    async def list_payloads_for_threat(self, threat_system_id: int) -> list[dict]:
        await self._get_or_404(ThreatSystem, threat_system_id, "Threat system")
        result = await self.db.execute(
            select(PayloadThreatLink, PayloadType)
            .join(PayloadType, PayloadType.id == PayloadThreatLink.payload_type_id)
            .where(PayloadThreatLink.threat_system_id == threat_system_id)
        )
        return [
            {**self._link_card(link), "payload": self._payload_card(pt)}
            for link, pt in result.all()
        ]

    # -- cross-reference: full relational neighborhood of a drone type --

    async def drone_cross_reference(self, drone_type_id: int) -> dict:
        """
        Everything linked to a drone type: compatible payloads, threats it's
        exposed to, and — via those payloads — threats it can counter.
        """
        dt = await self._get_or_404(DroneType, drone_type_id, "Drone type")
        payloads = await self.list_payloads_for_drone(drone_type_id)
        threats = await self.list_threats_for_drone(drone_type_id)

        payload_ids = [p["payload"]["id"] for p in payloads]
        countered_threats: list[dict] = []
        if payload_ids:
            result = await self.db.execute(
                select(PayloadThreatLink, ThreatSystem, PayloadType)
                .join(ThreatSystem, ThreatSystem.id == PayloadThreatLink.threat_system_id)
                .join(PayloadType, PayloadType.id == PayloadThreatLink.payload_type_id)
                .where(PayloadThreatLink.payload_type_id.in_(payload_ids))
            )
            countered_threats = [
                {
                    **self._link_card(link),
                    "via_payload": self._payload_card(pt),
                    "threat": self._threat_card(ts),
                }
                for link, ts, pt in result.all()
            ]

        return {
            "drone": self._drone_card(dt),
            "compatible_payloads": payloads,
            "exposed_to_threats": threats,
            "can_counter_threats": countered_threats,
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

    @staticmethod
    def _threat_card(ts: ThreatSystem) -> dict:
        return {
            "id":                     ts.id,
            "name":                   ts.name,
            "category":               ts.category,
            "manufacturer":           ts.manufacturer,
            "country":                ts.country,
            "max_range_km":           ts.max_range_km,
            "max_altitude_m":         ts.max_altitude_m,
            "max_speed_kmh":          ts.max_speed_kmh,
            "radar_cross_section_m2": ts.radar_cross_section_m2,
            "countermeasures":        ts.countermeasures,
            "notes":                  ts.notes,
            "classification":         ts.classification,
        }

    @staticmethod
    def _link_card(link) -> dict:
        """Generic card for any of the three link types (excludes FK id columns)."""
        card = {"id": link.id, "notes": link.notes, "created_at": link.created_at}
        if isinstance(link, DronePayloadLink):
            card.update(is_primary=link.is_primary, max_qty=link.max_qty)
        elif isinstance(link, DroneThreatLink):
            card.update(exposure_level=link.exposure_level)
        elif isinstance(link, PayloadThreatLink):
            card.update(effectiveness=link.effectiveness)
        return card

    @staticmethod
    def _payload_card(pt: PayloadType) -> dict:
        """Minimal card dict for payload search results."""
        return {
            "id":           pt.id,
            "name":         pt.name,
            "manufacturer": pt.manufacturer,
            "model":        pt.model,
            "category":     pt.category,
            "weight_kg":    pt.weight_kg,
            "has_gimbal":   pt.has_gimbal,
            "sensor_type":  pt.sensor_type,
        }