"""
Inventory Knowledge-Base Schemas
==================================
Rich, nested schemas for cross-reference queries and knowledge-base operations.
Supports relationship navigation: drone → payloads → threats, etc.
"""

from typing import Optional, Literal
from datetime import datetime
from pydantic import BaseModel, Field


# ──────────────────────────────────────────────────────────────────────────────
# SIMPLE/REFERENCE SCHEMAS (used in aggregated responses)
# ──────────────────────────────────────────────────────────────────────────────

class DroneTypeRef(BaseModel):
    """Minimal drone type reference."""
    id: int
    name: str
    manufacturer: str
    model: str
    size_class: str
    mission_type: str

    model_config = {"from_attributes": True}


class DroneInstanceRef(BaseModel):
    """Minimal drone instance reference."""
    id: int
    call_sign: str
    status: str
    total_flight_hours: float

    model_config = {"from_attributes": True}


class PayloadTypeRef(BaseModel):
    """Minimal payload type reference."""
    id: int
    name: str
    manufacturer: str
    model: str
    category: str
    weight_kg: float

    model_config = {"from_attributes": True}


class ThreatSystemRef(BaseModel):
    """Minimal threat system reference."""
    id: int
    name: str
    category: str
    manufacturer: str
    country: str
    max_range_km: Optional[float] = None

    model_config = {"from_attributes": True}


# ──────────────────────────────────────────────────────────────────────────────
# LINK SCHEMAS WITH RELATIONSHIP DATA
# ──────────────────────────────────────────────────────────────────────────────

class DronePayloadLinkDetail(BaseModel):
    """Drone-Payload link with full details of both entities."""
    id: int
    is_primary: bool
    max_qty: int
    notes: Optional[str] = None
    created_at: datetime
    drone: DroneTypeRef
    payload: PayloadTypeRef

    model_config = {"from_attributes": True}


class DroneThreatLinkDetail(BaseModel):
    """Drone-Threat link with exposure level and details."""
    id: int
    exposure_level: Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"]
    notes: Optional[str] = None
    created_at: datetime
    drone: DroneTypeRef
    threat: ThreatSystemRef

    model_config = {"from_attributes": True}


class PayloadThreatLinkDetail(BaseModel):
    """Payload-Threat link with effectiveness and details."""
    id: int
    effectiveness: Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"]
    notes: Optional[str] = None
    created_at: datetime
    payload: PayloadTypeRef
    threat: ThreatSystemRef

    model_config = {"from_attributes": True}


# ──────────────────────────────────────────────────────────────────────────────
# ENRICHED ENTITY SCHEMAS (with related data embedded)
# ──────────────────────────────────────────────────────────────────────────────

class DroneTypeWithInventory(BaseModel):
    """Drone type with full inventory relationships."""
    id: int
    name: str
    manufacturer: str
    model: str
    size_class: str
    mission_type: str
    is_vtol: bool
    max_speed_ms: float
    cruise_speed_ms: float
    max_altitude_m: float
    endurance_h: float
    range_km: float
    max_takeoff_weight_kg: float
    max_payload_weight_kg: float
    autopilot_type: str
    notes: Optional[str] = None
    is_active: bool
    created_at: datetime

    # Relationships
    compatible_payloads: list[DronePayloadLinkDetail] = Field(default_factory=list)
    exposed_threats: list[DroneThreatLinkDetail] = Field(default_factory=list)
    registered_instances: list[DroneInstanceRef] = Field(default_factory=list)

    model_config = {"from_attributes": True}


class PayloadTypeWithInventory(BaseModel):
    """Payload type with full inventory relationships."""
    id: int
    name: str
    manufacturer: str
    model: str
    category: str
    weight_kg: float
    voltage_v: float
    max_current_a: float
    has_gimbal: bool
    sensor_type: Optional[str] = None
    resolution: Optional[str] = None
    frame_rate_fps: Optional[float] = None
    payload_function: Optional[str] = None
    effective_range_m: Optional[float] = None
    notes: Optional[str] = None
    is_active: bool
    created_at: datetime

    # Relationships
    compatible_drones: list[DronePayloadLinkDetail] = Field(default_factory=list)
    effective_against_threats: list[PayloadThreatLinkDetail] = Field(default_factory=list)

    model_config = {"from_attributes": True}


class ThreatSystemWithInventory(BaseModel):
    """Threat system with full inventory relationships."""
    id: int
    name: str
    category: str
    manufacturer: str
    country: str
    max_range_km: Optional[float] = None
    max_altitude_m: Optional[float] = None
    max_speed_kmh: Optional[float] = None
    radar_cross_section_m2: Optional[float] = None
    countermeasures: list[str] = Field(default_factory=list)
    notes: Optional[str] = None
    classification: str
    created_at: datetime
    updated_at: Optional[datetime] = None

    # Relationships
    vulnerable_drones: list[DroneThreatLinkDetail] = Field(default_factory=list)
    mitigating_payloads: list[PayloadThreatLinkDetail] = Field(default_factory=list)

    model_config = {"from_attributes": True}


# ──────────────────────────────────────────────────────────────────────────────
# CROSS-REFERENCE QUERY RESULTS
# ──────────────────────────────────────────────────────────────────────────────

class DroneCapabilityProfile(BaseModel):
    """
    Answer: What drones can carry payload X?
    Used for mission planning: "I need to deploy sensor Y — which drones can carry it?"
    """
    payload_id: int
    payload_name: str
    capable_drones: list[DronePayloadLinkDetail] = Field(default_factory=list)
    total_capable: int = 0
    primary_carrier_drones: list[DronePayloadLinkDetail] = Field(default_factory=list)

    model_config = {"from_attributes": True}


class ThreatMitigationProfile(BaseModel):
    """
    Answer: How do we defeat threat T?
    Used for threat analysis: "Given SAM system X, which payloads can counter it?
    Which drones can deliver those payloads?"
    """
    threat_id: int
    threat_name: str
    threat_category: str
    
    # Mitigation chain: Threat → Effective Payloads → Capable Drones
    effective_payloads: list[PayloadThreatLinkDetail] = Field(default_factory=list)
    payload_count: int = 0
    
    capable_drones_for_payloads: dict[int, list[DronePayloadLinkDetail]] = Field(
        default_factory=dict
    )
    total_capable_drones: int = 0
    coverage_analysis: Optional[dict] = None  # payloads_with_no_capable_drone, payloads_with_redundant_drones, fully_covered

    model_config = {"from_attributes": True}


class DroneVulnerabilityProfile(BaseModel):
    """
    Answer: What threats threaten drone D?
    Used for planning: "Deploy drone X in environment with SAMs — what's the threat?"
    """
    drone_id: int
    drone_name: str
    drone_size_class: str
    
    # Direct threats
    exposed_threats: list[DroneThreatLinkDetail] = Field(default_factory=list)
    threat_count: int = 0
    
    # Mitigation: available payloads + their effectiveness against threats
    available_payloads: list[DronePayloadLinkDetail] = Field(default_factory=list)
    payload_threat_mitigation: dict[int, list[PayloadThreatLinkDetail]] = Field(
        default_factory=dict
    )
    coverage_analysis: Optional[dict] = None  # threats_with_no_mitigating_payload, threats_with_redundant_mitigation, fully_mitigated

    model_config = {"from_attributes": True}


class MissionInventoryProfile(BaseModel):
    """
    Answer: Given mission requirements M, what drone + payload combinations work?
    Multi-dimensional query: size_class, endurance, payload weight, threat environment.
    """
    mission_type: str
    constraints: dict  # size_class, max_weight, required_endurance, etc.
    
    # Results: viable drone-payload pairs ranked by suitability
    viable_combinations: list[dict] = Field(default_factory=list)  # {drone, payloads[], threats[]}
    total_options: int = 0
    
    # Analysis
    primary_recommendation: Optional[dict] = None  # top-ranked combo
    analysis_notes: str = ""

    model_config = {"from_attributes": True}


# ──────────────────────────────────────────────────────────────────────────────
# KNOWLEDGE-BASE QUERY SCHEMAS (for search/filter)
# ──────────────────────────────────────────────────────────────────────────────

class InventorySearchQuery(BaseModel):
    """Multi-faceted search across all inventory entities."""
    q: Optional[str] = Field(None, description="Free-text search (name, manufacturer, model)")
    
    # Drone filters
    drone_size_class: Optional[list[str]] = None
    drone_mission_type: Optional[list[str]] = None
    drone_min_endurance_h: Optional[float] = None
    drone_max_weight_kg: Optional[float] = None
    
    # Payload filters
    payload_category: Optional[list[str]] = None
    payload_max_weight_kg: Optional[float] = None
    
    # Threat filters
    threat_category: Optional[list[str]] = None
    threat_country: Optional[list[str]] = None
    
    # Link filters
    exposure_level: Optional[list[str]] = None
    effectiveness: Optional[list[str]] = None
    
    limit: int = Field(20, ge=1, le=100)
    offset: int = Field(0, ge=0)


class InventorySearchResult(BaseModel):
    """Results from inventory search."""
    drones: list[DroneTypeWithInventory] = Field(default_factory=list)
    payloads: list[PayloadTypeWithInventory] = Field(default_factory=list)
    threats: list[ThreatSystemWithInventory] = Field(default_factory=list)
    
    total_drones: int = 0
    total_payloads: int = 0
    total_threats: int = 0
    
    query: str = ""
    executed_at: datetime = Field(default_factory=datetime.utcnow)


# ──────────────────────────────────────────────────────────────────────────────
# ANALYTICS & REPORTING SCHEMAS
# ──────────────────────────────────────────────────────────────────────────────

class InventoryHealthReport(BaseModel):
    """Inventory knowledge-base health and completeness metrics."""
    total_drone_types: int = 0
    total_drone_instances: int = 0
    total_payload_types: int = 0
    total_threat_systems: int = 0
    
    # Link completeness
    drone_payload_links: int = 0
    drone_threat_links: int = 0
    payload_threat_links: int = 0
    
    # Coverage analysis
    drones_with_payloads: int = 0
    drones_with_threats: int = 0
    payloads_with_threats: int = 0
    
    # Gap analysis
    unmapped_drones: list[int] = Field(default_factory=list)  # drone IDs with no links
    unmapped_threats: list[int] = Field(default_factory=list)
    
    generated_at: datetime = Field(default_factory=datetime.utcnow)


class EntityRelationshipStats(BaseModel):
    """Statistics about a specific entity's relationships."""
    entity_type: Literal["drone", "payload", "threat"]
    entity_id: int
    entity_name: str
    
    outgoing_links: int = 0  # direct connections
    incoming_links: int = 0  # reverse connections
    transitive_relations: int = 0  # two-hop paths
    
    connected_entity_counts: dict[str, int] = Field(default_factory=dict)


# ──────────────────────────────────────────────────────────────────────────────
# BULK OPERATIONS
# ──────────────────────────────────────────────────────────────────────────────

class LinkBulkCreate(BaseModel):
    """Create multiple links at once (CSV import pattern)."""
    link_type: Literal["drone_payload", "drone_threat", "payload_threat"]
    links: list[dict]  # List of {entity1_id, entity2_id, level/effectiveness, notes}
    validate_before_create: bool = True


class LinkBulkCreateResult(BaseModel):
    """Result of bulk link creation."""
    link_type: str
    created: int = 0
    failed: int = 0
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


# ──────────────────────────────────────────────────────────────────────────────
# VERSION INFORMATION
# ──────────────────────────────────────────────────────────────────────────────

class InventoryKBVersion(BaseModel):
    """Knowledge-base schema version and capabilities."""
    version: str = "1.0"
    deployment_date: str = "2026-08-12"
    capabilities: list[str] = Field(
        default_factory=lambda: [
            "cross_reference_queries",
            "threat_mitigation_analysis",
            "drone_vulnerability_analysis",
            "mission_planning_support",
            "bulk_import_export",
            "inventory_health_reporting",
        ]
    )
    v2_planned_features: list[str] = Field(
        default_factory=lambda: [
            "elasticsearch_full_text_search",
            "cms_workflow",
            "rich_html_pages",
            "comparative_analysis",
            "advanced_threat_modeling",
            "ai_powered_recommendations",
        ]
    )
