"""
Inventory Knowledge-Base Service
=================================
Cross-reference queries and relationship navigation for inventory entities.
Supports complex queries: threat mitigation chains, drone capabilities, mission planning.
"""

import structlog
from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, or_
from fastapi import HTTPException

from app.models.drone import DroneType, DroneInstance
from app.models.payload import PayloadType
from app.models.threat import ThreatSystem
from app.models.inventory_link import DronePayloadLink, DroneThreatLink, PayloadThreatLink
from app.schemas.inventory_kb import (
    DroneTypeWithInventory, PayloadTypeWithInventory, ThreatSystemWithInventory,
    DroneCapabilityProfile, ThreatMitigationProfile, DroneVulnerabilityProfile,
    MissionInventoryProfile, InventorySearchQuery, InventorySearchResult,
    InventoryHealthReport, EntityRelationshipStats,
    DroneTypeRef, DroneInstanceRef, PayloadTypeRef, ThreatSystemRef,
    DronePayloadLinkDetail, DroneThreatLinkDetail, PayloadThreatLinkDetail,
)

log = structlog.get_logger()


class InventoryKBService:
    """Cross-reference query service for inventory knowledge base."""

    def __init__(self, db: AsyncSession):
        self.db = db

    # ────────────────────────────────────────────────────────────────────────────
    # CROSS-REFERENCE QUERIES — CAPABILITY PROFILES
    # ────────────────────────────────────────────────────────────────────────────

    async def get_payload_capability_profile(self, payload_id: int) -> DroneCapabilityProfile:
        """
        Query: Which drones can carry payload X?
        Used for: Mission planning — "I need sensor Y deployed, which drones fit?"
        """
        # Verify payload exists
        payload = await self.db.get(PayloadType, payload_id)
        if not payload:
            raise HTTPException(404, f"Payload type #{payload_id} not found")

        # Get all drone-payload links for this payload
        links_result = await self.db.execute(
            select(DronePayloadLink, DroneType).join(
                DroneType, DronePayloadLink.drone_type_id == DroneType.id
            ).where(
                and_(
                    DronePayloadLink.payload_type_id == payload_id,
                    DroneType.is_active == True,
                )
            )
        )
        links_data = links_result.all()

        # Build detailed link objects
        capability_links = []
        primary_links = []
        
        for link, drone_type in links_data:
            link_detail = DronePayloadLinkDetail(
                id=link.id,
                is_primary=link.is_primary,
                max_qty=link.max_qty,
                notes=link.notes,
                created_at=link.created_at,
                drone=DroneTypeRef.model_validate(drone_type),
                payload=PayloadTypeRef.model_validate(payload),
            )
            capability_links.append(link_detail)
            if link.is_primary:
                primary_links.append(link_detail)

        return DroneCapabilityProfile(
            payload_id=payload_id,
            payload_name=payload.name,
            capable_drones=capability_links,
            total_capable=len(capability_links),
            primary_carrier_drones=primary_links,
        )

    async def get_drone_capability_profile(self, drone_id: int) -> dict:
        """
        Query: What payloads can drone D carry?
        Returns list of compatible payloads with constraints.
        """
        # Verify drone exists
        drone = await self.db.get(DroneType, drone_id)
        if not drone:
            raise HTTPException(404, f"Drone type #{drone_id} not found")

        # Get all drone-payload links for this drone
        links_result = await self.db.execute(
            select(DronePayloadLink, PayloadType).join(
                PayloadType, DronePayloadLink.payload_type_id == PayloadType.id
            ).where(
                and_(
                    DronePayloadLink.drone_type_id == drone_id,
                    PayloadType.is_active == True,
                )
            )
        )
        links_data = links_result.all()

        # Group by primary/secondary
        primary_payloads = []
        secondary_payloads = []
        
        for link, payload_type in links_data:
            link_detail = DronePayloadLinkDetail(
                id=link.id,
                is_primary=link.is_primary,
                max_qty=link.max_qty,
                notes=link.notes,
                created_at=link.created_at,
                drone=DroneTypeRef.model_validate(drone),
                payload=PayloadTypeRef.model_validate(payload_type),
            )
            if link.is_primary:
                primary_payloads.append(link_detail)
            else:
                secondary_payloads.append(link_detail)

        return {
            "drone_id": drone_id,
            "drone_name": drone.name,
            "max_payload_weight_kg": drone.max_payload_weight_kg,
            "primary_payloads": primary_payloads,
            "secondary_payloads": secondary_payloads,
            "total_payload_options": len(primary_payloads) + len(secondary_payloads),
        }

    # ────────────────────────────────────────────────────────────────────────────
    # CROSS-REFERENCE QUERIES — THREAT ANALYSIS
    # ────────────────────────────────────────────────────────────────────────────

    async def get_threat_mitigation_profile(self, threat_id: int) -> ThreatMitigationProfile:
        """
        Query: How do we defeat threat T?
        Multi-hop: Threat → Effective Payloads → Capable Drones
        Used for: Threat analysis, countermeasure planning.
        """
        # Verify threat exists
        threat = await self.db.get(ThreatSystem, threat_id)
        if not threat:
            raise HTTPException(404, f"Threat system #{threat_id} not found")

        # Step 1: Find all payloads effective against this threat
        payload_links_result = await self.db.execute(
            select(PayloadThreatLink, PayloadType).join(
                PayloadType, PayloadThreatLink.payload_type_id == PayloadType.id
            ).where(
                and_(
                    PayloadThreatLink.threat_system_id == threat_id,
                    PayloadType.is_active == True,
                )
            )
        )
        payload_links = payload_links_result.all()

        effective_payloads = []
        payload_ids = []
        
        for link, payload_type in payload_links:
            link_detail = PayloadThreatLinkDetail(
                id=link.id,
                effectiveness=link.effectiveness,
                notes=link.notes,
                created_at=link.created_at,
                payload=PayloadTypeRef.model_validate(payload_type),
                threat=ThreatSystemRef.model_validate(threat),
            )
            effective_payloads.append(link_detail)
            payload_ids.append(payload_type.id)

        # Step 2: For each effective payload, find capable drones
        capable_drones_for_payloads = {}
        total_capable_drones = set()
        
        if payload_ids:
            drone_links_result = await self.db.execute(
                select(DronePayloadLink, DroneType, PayloadType).join(
                    DroneType, DronePayloadLink.drone_type_id == DroneType.id
                ).join(
                    PayloadType, DronePayloadLink.payload_type_id == PayloadType.id
                ).where(
                    and_(
                        DronePayloadLink.payload_type_id.in_(payload_ids),
                        DroneType.is_active == True,
                        PayloadType.is_active == True,
                    )
                )
            )
            drone_links = drone_links_result.all()
            
            for link, drone_type, payload_type in drone_links:
                link_detail = DronePayloadLinkDetail(
                    id=link.id,
                    is_primary=link.is_primary,
                    max_qty=link.max_qty,
                    notes=link.notes,
                    created_at=link.created_at,
                    drone=DroneTypeRef.model_validate(drone_type),
                    payload=PayloadTypeRef.model_validate(payload_type),
                )
                
                if payload_type.id not in capable_drones_for_payloads:
                    capable_drones_for_payloads[payload_type.id] = []
                
                capable_drones_for_payloads[payload_type.id].append(link_detail)
                total_capable_drones.add(drone_type.id)

        # Coverage analysis: payloads with no capable drone are mitigation gaps;
        # payloads with multiple capable drones give redundant coverage.
        unmitigated_payload_ids = [
            pid for pid in payload_ids if not capable_drones_for_payloads.get(pid)
        ]
        redundant_payload_ids = [
            pid for pid, drones in capable_drones_for_payloads.items() if len(drones) > 1
        ]
        coverage_analysis = {
            "payloads_with_no_capable_drone": unmitigated_payload_ids,
            "payloads_with_redundant_drones": redundant_payload_ids,
            "fully_covered": len(unmitigated_payload_ids) == 0 and len(effective_payloads) > 0,
        }

        return ThreatMitigationProfile(
            threat_id=threat_id,
            threat_name=threat.name,
            threat_category=threat.category,
            effective_payloads=effective_payloads,
            payload_count=len(effective_payloads),
            capable_drones_for_payloads=capable_drones_for_payloads,
            total_capable_drones=len(total_capable_drones),
            coverage_analysis=coverage_analysis,
        )

    async def get_drone_vulnerability_profile(self, drone_id: int) -> DroneVulnerabilityProfile:
        """
        Query: What threats threaten drone D?
        Includes available payloads and their counter-effectiveness.
        Used for: Mission planning — "Deploy drone X in hostile area — what's the threat?"
        """
        # Verify drone exists
        drone = await self.db.get(DroneType, drone_id)
        if not drone:
            raise HTTPException(404, f"Drone type #{drone_id} not found")

        # Step 1: Get all threats this drone is exposed to
        threat_links_result = await self.db.execute(
            select(DroneThreatLink, ThreatSystem).join(
                ThreatSystem, DroneThreatLink.threat_system_id == ThreatSystem.id
            ).where(DroneThreatLink.drone_type_id == drone_id)
        )
        threat_links = threat_links_result.all()

        exposed_threats = []
        threat_ids = []
        
        for link, threat_system in threat_links:
            link_detail = DroneThreatLinkDetail(
                id=link.id,
                exposure_level=link.exposure_level,
                notes=link.notes,
                created_at=link.created_at,
                drone=DroneTypeRef.model_validate(drone),
                threat=ThreatSystemRef.model_validate(threat_system),
            )
            exposed_threats.append(link_detail)
            threat_ids.append(threat_system.id)

        # Step 2: Get all payloads this drone can carry
        payload_links_result = await self.db.execute(
            select(DronePayloadLink, PayloadType).join(
                PayloadType, DronePayloadLink.payload_type_id == PayloadType.id
            ).where(
                and_(
                    DronePayloadLink.drone_type_id == drone_id,
                    PayloadType.is_active == True,
                )
            )
        )
        payload_links = payload_links_result.all()

        available_payloads = []
        payload_ids = []
        
        for link, payload_type in payload_links:
            link_detail = DronePayloadLinkDetail(
                id=link.id,
                is_primary=link.is_primary,
                max_qty=link.max_qty,
                notes=link.notes,
                created_at=link.created_at,
                drone=DroneTypeRef.model_validate(drone),
                payload=PayloadTypeRef.model_validate(payload_type),
            )
            available_payloads.append(link_detail)
            payload_ids.append(payload_type.id)

        # Step 3: For each available payload, check effectiveness against threats
        payload_threat_mitigation = {}
        
        if payload_ids and threat_ids:
            mitig_result = await self.db.execute(
                select(PayloadThreatLink, PayloadType, ThreatSystem).join(
                    PayloadType, PayloadThreatLink.payload_type_id == PayloadType.id
                ).join(
                    ThreatSystem, PayloadThreatLink.threat_system_id == ThreatSystem.id
                ).where(
                    and_(
                        PayloadThreatLink.payload_type_id.in_(payload_ids),
                        PayloadThreatLink.threat_system_id.in_(threat_ids),
                    )
                )
            )
            mitig_links = mitig_result.all()
            
            for link, payload_type, threat_system in mitig_links:
                link_detail = PayloadThreatLinkDetail(
                    id=link.id,
                    effectiveness=link.effectiveness,
                    notes=link.notes,
                    created_at=link.created_at,
                    payload=PayloadTypeRef.model_validate(payload_type),
                    threat=ThreatSystemRef.model_validate(threat_system),
                )
                
                if payload_type.id not in payload_threat_mitigation:
                    payload_threat_mitigation[payload_type.id] = []
                
                payload_threat_mitigation[payload_type.id].append(link_detail)

        # Coverage analysis: threats with no mitigating payload are exposure gaps;
        # threats mitigated by multiple payloads give redundant coverage.
        mitigated_threat_ids = {
            threat_system.id
            for links in payload_threat_mitigation.values()
            for link_detail in links
            for threat_system in [link_detail.threat]
        }
        unmitigated_threat_ids = [tid for tid in threat_ids if tid not in mitigated_threat_ids]
        threat_mitigation_counts = {}
        for links in payload_threat_mitigation.values():
            for link_detail in links:
                threat_mitigation_counts[link_detail.threat.id] = (
                    threat_mitigation_counts.get(link_detail.threat.id, 0) + 1
                )
        redundant_threat_ids = [
            tid for tid, count in threat_mitigation_counts.items() if count > 1
        ]
        coverage_analysis = {
            "threats_with_no_mitigating_payload": unmitigated_threat_ids,
            "threats_with_redundant_mitigation": redundant_threat_ids,
            "fully_mitigated": len(unmitigated_threat_ids) == 0 and len(exposed_threats) > 0,
        }

        return DroneVulnerabilityProfile(
            drone_id=drone_id,
            drone_name=drone.name,
            drone_size_class=drone.size_class,
            exposed_threats=exposed_threats,
            threat_count=len(exposed_threats),
            available_payloads=available_payloads,
            payload_threat_mitigation=payload_threat_mitigation,
            coverage_analysis=coverage_analysis,
        )

    # ────────────────────────────────────────────────────────────────────────────
    # MULTI-DIMENSIONAL SEARCH & FILTERING
    # ────────────────────────────────────────────────────────────────────────────

    async def search_inventory(self, query: InventorySearchQuery) -> InventorySearchResult:
        """
        Multi-faceted search across drones, payloads, threats.
        Supports free-text search and multiple dimension filters.
        """
        results = InventorySearchResult(query=query.q or "")

        # Build drone query
        drone_q = select(DroneType).where(DroneType.is_active == True)
        
        if query.q:
            drone_q = drone_q.where(
                or_(
                    DroneType.name.ilike(f"%{query.q}%"),
                    DroneType.manufacturer.ilike(f"%{query.q}%"),
                    DroneType.model.ilike(f"%{query.q}%"),
                )
            )
        
        if query.drone_size_class:
            drone_q = drone_q.where(DroneType.size_class.in_(query.drone_size_class))
        
        if query.drone_mission_type:
            drone_q = drone_q.where(DroneType.mission_type.in_(query.drone_mission_type))
        
        if query.drone_min_endurance_h is not None:
            drone_q = drone_q.where(DroneType.endurance_h >= query.drone_min_endurance_h)
        
        if query.drone_max_weight_kg is not None:
            drone_q = drone_q.where(DroneType.max_takeoff_weight_kg <= query.drone_max_weight_kg)

        drone_result = await self.db.execute(
            drone_q.offset(query.offset).limit(query.limit)
        )
        results.drones = [
            await self._hydrate_drone_with_inventory(dt)
            for dt in drone_result.scalars().all()
        ]
        results.total_drones = len(results.drones)

        # Build payload query
        payload_q = select(PayloadType).where(PayloadType.is_active == True)
        
        if query.q:
            payload_q = payload_q.where(
                or_(
                    PayloadType.name.ilike(f"%{query.q}%"),
                    PayloadType.manufacturer.ilike(f"%{query.q}%"),
                    PayloadType.model.ilike(f"%{query.q}%"),
                )
            )
        
        if query.payload_category:
            payload_q = payload_q.where(PayloadType.category.in_(query.payload_category))
        
        if query.payload_max_weight_kg is not None:
            payload_q = payload_q.where(PayloadType.weight_kg <= query.payload_max_weight_kg)

        payload_result = await self.db.execute(
            payload_q.offset(query.offset).limit(query.limit)
        )
        results.payloads = [
            await self._hydrate_payload_with_inventory(pt)
            for pt in payload_result.scalars().all()
        ]
        results.total_payloads = len(results.payloads)

        # Build threat query
        threat_q = select(ThreatSystem)
        
        if query.q:
            threat_q = threat_q.where(
                or_(
                    ThreatSystem.name.ilike(f"%{query.q}%"),
                    ThreatSystem.manufacturer.ilike(f"%{query.q}%"),
                    ThreatSystem.country.ilike(f"%{query.q}%"),
                )
            )
        
        if query.threat_category:
            threat_q = threat_q.where(ThreatSystem.category.in_(query.threat_category))
        
        if query.threat_country:
            threat_q = threat_q.where(ThreatSystem.country.in_(query.threat_country))

        threat_result = await self.db.execute(
            threat_q.offset(query.offset).limit(query.limit)
        )
        results.threats = [
            await self._hydrate_threat_with_inventory(ts)
            for ts in threat_result.scalars().all()
        ]
        results.total_threats = len(results.threats)

        results.executed_at = datetime.utcnow()
        return results

    # ────────────────────────────────────────────────────────────────────────────
    # INVENTORY HEALTH & ANALYTICS
    # ────────────────────────────────────────────────────────────────────────────

    async def get_inventory_health_report(self) -> InventoryHealthReport:
        """
        Generate inventory completeness metrics:
        - Coverage (% drones with payloads/threats)
        - Gaps (unmapped entities)
        - Link density
        """
        # Count all entities
        drones_result = await self.db.execute(select(DroneType))
        total_drones = len(drones_result.scalars().all())

        instances_result = await self.db.execute(select(DroneInstance))
        total_instances = len(instances_result.scalars().all())

        payloads_result = await self.db.execute(select(PayloadType))
        total_payloads = len(payloads_result.scalars().all())

        threats_result = await self.db.execute(select(ThreatSystem))
        total_threats = len(threats_result.scalars().all())

        # Count links
        drone_payload_result = await self.db.execute(select(DronePayloadLink))
        drone_payload_count = len(drone_payload_result.scalars().all())

        drone_threat_result = await self.db.execute(select(DroneThreatLink))
        drone_threat_count = len(drone_threat_result.scalars().all())

        payload_threat_result = await self.db.execute(select(PayloadThreatLink))
        payload_threat_count = len(payload_threat_result.scalars().all())

        # Find mapped/unmapped entities
        unmapped_drones = []
        unmapped_threats = []
        drones_with_payloads = 0
        drones_with_threats = 0
        payloads_with_threats = 0

        if total_drones > 0:
            drones_with_payload_result = await self.db.execute(
                select(DronePayloadLink.drone_type_id.distinct())
            )
            drone_payload_ids = set(drones_with_payload_result.scalars().all())
            drones_with_payloads = len(drone_payload_ids)

            drones_with_threat_result = await self.db.execute(
                select(DroneThreatLink.drone_type_id.distinct())
            )
            drone_threat_ids = set(drones_with_threat_result.scalars().all())
            drones_with_threats = len(drone_threat_ids)

            drones_with_links_result = await self.db.execute(
                select(DronePayloadLink.drone_type_id.distinct())
                .union(select(DroneThreatLink.drone_type_id.distinct()))
            )
            mapped_drone_ids = set(drones_with_links_result.scalars().all())
            
            all_drones_result = await self.db.execute(select(DroneType.id))
            all_drone_ids = set(all_drones_result.scalars().all())
            unmapped_drones = list(all_drone_ids - mapped_drone_ids)

        if total_threats > 0:
            threats_with_links_result = await self.db.execute(
                select(DroneThreatLink.threat_system_id.distinct())
                .union(select(PayloadThreatLink.threat_system_id.distinct()))
            )
            mapped_threat_ids = set(threats_with_links_result.scalars().all())
            
            all_threats_result = await self.db.execute(select(ThreatSystem.id))
            all_threat_ids = set(all_threats_result.scalars().all())
            unmapped_threats = list(all_threat_ids - mapped_threat_ids)

        if total_payloads > 0:
            payloads_with_threat_result = await self.db.execute(
                select(PayloadThreatLink.payload_type_id.distinct())
            )
            payloads_with_threats = len(set(payloads_with_threat_result.scalars().all()))

        return InventoryHealthReport(
            total_drone_types=total_drones,
            total_drone_instances=total_instances,
            total_payload_types=total_payloads,
            total_threat_systems=total_threats,
            drone_payload_links=drone_payload_count,
            drone_threat_links=drone_threat_count,
            payload_threat_links=payload_threat_count,
            drones_with_payloads=drones_with_payloads,
            drones_with_threats=drones_with_threats,
            payloads_with_threats=payloads_with_threats,
            unmapped_drones=unmapped_drones,
            unmapped_threats=unmapped_threats,
        )

    async def get_entity_relationship_stats(self, entity_type: str, entity_id: int) -> EntityRelationshipStats:
        """Get relationship statistics for a specific entity."""
        if entity_type == "drone":
            entity = await self.db.get(DroneType, entity_id)
            if not entity:
                raise HTTPException(404, f"Drone type #{entity_id} not found")
            
            # Count outgoing links
            payload_links_result = await self.db.execute(
                select(DronePayloadLink).where(DronePayloadLink.drone_type_id == entity_id)
            )
            payload_link_count = len(payload_links_result.scalars().all())
            
            threat_links_result = await self.db.execute(
                select(DroneThreatLink).where(DroneThreatLink.drone_type_id == entity_id)
            )
            threat_link_count = len(threat_links_result.scalars().all())
            
            return EntityRelationshipStats(
                entity_type="drone",
                entity_id=entity_id,
                entity_name=entity.name,
                outgoing_links=payload_link_count + threat_link_count,
                connected_entity_counts={
                    "payloads": payload_link_count,
                    "threats": threat_link_count,
                },
            )
        
        elif entity_type == "payload":
            entity = await self.db.get(PayloadType, entity_id)
            if not entity:
                raise HTTPException(404, f"Payload type #{entity_id} not found")
            
            # Count outgoing links
            drone_links_result = await self.db.execute(
                select(DronePayloadLink).where(DronePayloadLink.payload_type_id == entity_id)
            )
            drone_link_count = len(drone_links_result.scalars().all())
            
            threat_links_result = await self.db.execute(
                select(PayloadThreatLink).where(PayloadThreatLink.payload_type_id == entity_id)
            )
            threat_link_count = len(threat_links_result.scalars().all())
            
            return EntityRelationshipStats(
                entity_type="payload",
                entity_id=entity_id,
                entity_name=entity.name,
                outgoing_links=drone_link_count + threat_link_count,
                connected_entity_counts={
                    "drones": drone_link_count,
                    "threats": threat_link_count,
                },
            )
        
        elif entity_type == "threat":
            entity = await self.db.get(ThreatSystem, entity_id)
            if not entity:
                raise HTTPException(404, f"Threat system #{entity_id} not found")
            
            # Count incoming links
            drone_links_result = await self.db.execute(
                select(DroneThreatLink).where(DroneThreatLink.threat_system_id == entity_id)
            )
            drone_link_count = len(drone_links_result.scalars().all())
            
            payload_links_result = await self.db.execute(
                select(PayloadThreatLink).where(PayloadThreatLink.threat_system_id == entity_id)
            )
            payload_link_count = len(payload_links_result.scalars().all())
            
            return EntityRelationshipStats(
                entity_type="threat",
                entity_id=entity_id,
                entity_name=entity.name,
                incoming_links=drone_link_count + payload_link_count,
                connected_entity_counts={
                    "drones": drone_link_count,
                    "payloads": payload_link_count,
                },
            )
        else:
            raise HTTPException(400, f"Unknown entity type: {entity_type}")

    # ────────────────────────────────────────────────────────────────────────────
    # HELPER METHODS — ENTITY HYDRATION
    # ────────────────────────────────────────────────────────────────────────────

    async def _hydrate_drone_with_inventory(self, drone: DroneType) -> DroneTypeWithInventory:
        """Hydrate a drone type with all its inventory relationships."""
        # Get payload links
        payload_links_result = await self.db.execute(
            select(DronePayloadLink, PayloadType).join(
                PayloadType, DronePayloadLink.payload_type_id == PayloadType.id
            ).where(DronePayloadLink.drone_type_id == drone.id)
        )
        payload_links = [
            DronePayloadLinkDetail(
                id=link.id,
                is_primary=link.is_primary,
                max_qty=link.max_qty,
                notes=link.notes,
                created_at=link.created_at,
                drone=DroneTypeRef.model_validate(drone),
                payload=PayloadTypeRef.model_validate(payload),
            )
            for link, payload in payload_links_result.all()
        ]

        # Get threat links
        threat_links_result = await self.db.execute(
            select(DroneThreatLink, ThreatSystem).join(
                ThreatSystem, DroneThreatLink.threat_system_id == ThreatSystem.id
            ).where(DroneThreatLink.drone_type_id == drone.id)
        )
        threat_links = [
            DroneThreatLinkDetail(
                id=link.id,
                exposure_level=link.exposure_level,
                notes=link.notes,
                created_at=link.created_at,
                drone=DroneTypeRef.model_validate(drone),
                threat=ThreatSystemRef.model_validate(threat),
            )
            for link, threat in threat_links_result.all()
        ]

        # Get instances
        instances_result = await self.db.execute(
            select(DroneInstance).where(DroneInstance.drone_type_id == drone.id)
        )
        instances = [
            DroneInstanceRef.model_validate(i)
            for i in instances_result.scalars().all()
        ]

        return DroneTypeWithInventory(
            id=drone.id,
            name=drone.name,
            manufacturer=drone.manufacturer,
            model=drone.model,
            size_class=drone.size_class,
            mission_type=drone.mission_type,
            is_vtol=drone.is_vtol,
            max_speed_ms=drone.max_speed_ms,
            cruise_speed_ms=drone.cruise_speed_ms,
            max_altitude_m=drone.max_altitude_m,
            endurance_h=drone.endurance_h,
            range_km=drone.range_km,
            max_takeoff_weight_kg=drone.max_takeoff_weight_kg,
            max_payload_weight_kg=drone.max_payload_weight_kg,
            autopilot_type=drone.autopilot_type,
            notes=drone.notes,
            is_active=drone.is_active,
            created_at=drone.created_at,
            compatible_payloads=payload_links,
            exposed_threats=threat_links,
            registered_instances=instances,
        )

    async def _hydrate_payload_with_inventory(self, payload: PayloadType) -> PayloadTypeWithInventory:
        """Hydrate a payload type with all its inventory relationships."""
        # Get drone links
        drone_links_result = await self.db.execute(
            select(DronePayloadLink, DroneType).join(
                DroneType, DronePayloadLink.drone_type_id == DroneType.id
            ).where(DronePayloadLink.payload_type_id == payload.id)
        )
        drone_links = [
            DronePayloadLinkDetail(
                id=link.id,
                is_primary=link.is_primary,
                max_qty=link.max_qty,
                notes=link.notes,
                created_at=link.created_at,
                drone=DroneTypeRef.model_validate(drone),
                payload=PayloadTypeRef.model_validate(payload),
            )
            for link, drone in drone_links_result.all()
        ]

        # Get threat links
        threat_links_result = await self.db.execute(
            select(PayloadThreatLink, ThreatSystem).join(
                ThreatSystem, PayloadThreatLink.threat_system_id == ThreatSystem.id
            ).where(PayloadThreatLink.payload_type_id == payload.id)
        )
        threat_links = [
            PayloadThreatLinkDetail(
                id=link.id,
                effectiveness=link.effectiveness,
                notes=link.notes,
                created_at=link.created_at,
                payload=PayloadTypeRef.model_validate(payload),
                threat=ThreatSystemRef.model_validate(threat),
            )
            for link, threat in threat_links_result.all()
        ]

        return PayloadTypeWithInventory(
            id=payload.id,
            name=payload.name,
            manufacturer=payload.manufacturer,
            model=payload.model,
            category=payload.category,
            weight_kg=payload.weight_kg,
            voltage_v=payload.voltage_v,
            max_current_a=payload.max_current_a,
            has_gimbal=payload.has_gimbal,
            sensor_type=payload.sensor_type,
            resolution=payload.resolution,
            frame_rate_fps=payload.frame_rate_fps,
            payload_function=payload.payload_function,
            effective_range_m=payload.effective_range_m,
            notes=payload.notes,
            is_active=payload.is_active,
            created_at=payload.created_at,
            compatible_drones=drone_links,
            effective_against_threats=threat_links,
        )

    async def _hydrate_threat_with_inventory(self, threat: ThreatSystem) -> ThreatSystemWithInventory:
        """Hydrate a threat system with all its inventory relationships."""
        # Get drone vulnerability links
        drone_links_result = await self.db.execute(
            select(DroneThreatLink, DroneType).join(
                DroneType, DroneThreatLink.drone_type_id == DroneType.id
            ).where(DroneThreatLink.threat_system_id == threat.id)
        )
        drone_links = [
            DroneThreatLinkDetail(
                id=link.id,
                exposure_level=link.exposure_level,
                notes=link.notes,
                created_at=link.created_at,
                drone=DroneTypeRef.model_validate(drone),
                threat=ThreatSystemRef.model_validate(threat),
            )
            for link, drone in drone_links_result.all()
        ]

        # Get payload mitigation links
        payload_links_result = await self.db.execute(
            select(PayloadThreatLink, PayloadType).join(
                PayloadType, PayloadThreatLink.payload_type_id == PayloadType.id
            ).where(PayloadThreatLink.threat_system_id == threat.id)
        )
        payload_links = [
            PayloadThreatLinkDetail(
                id=link.id,
                effectiveness=link.effectiveness,
                notes=link.notes,
                created_at=link.created_at,
                payload=PayloadTypeRef.model_validate(payload),
                threat=ThreatSystemRef.model_validate(threat),
            )
            for link, payload in payload_links_result.all()
        ]

        return ThreatSystemWithInventory(
            id=threat.id,
            name=threat.name,
            category=threat.category,
            manufacturer=threat.manufacturer,
            country=threat.country,
            max_range_km=threat.max_range_km,
            max_altitude_m=threat.max_altitude_m,
            max_speed_kmh=threat.max_speed_kmh,
            radar_cross_section_m2=threat.radar_cross_section_m2,
            countermeasures=threat.countermeasures or [],
            notes=threat.notes,
            classification=threat.classification,
            created_at=threat.created_at,
            updated_at=threat.updated_at,
            vulnerable_drones=drone_links,
            mitigating_payloads=payload_links,
        )
