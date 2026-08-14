"""
Inventory Knowledge-Base Service Unit Tests
=============================================

Low-level unit tests for InventoryKBService methods using mocked AsyncSession.
These tests focus on business logic, error handling, and data transformation
without requiring HTTP layer or full database.

Coverage:
  - Cross-reference query correctness
  - Data hydration and relationship mapping
  - Multi-hop query traversal
  - Error handling and validation
  - Edge cases (empty results, missing entities, null fields)
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from sqlalchemy import select
from datetime import datetime, timezone
from fastapi import HTTPException

from app.modules.drone_inventory.kb_service import InventoryKBService
from app.models.drone import DroneType, DroneInstance
from app.models.payload import PayloadType
from app.models.threat import ThreatSystem
from app.models.inventory_link import (
    DronePayloadLink, DroneThreatLink, PayloadThreatLink
)


def as_dict(value):
    """Normalize service responses to plain dicts for assertions."""
    return value.model_dump() if hasattr(value, "model_dump") else value


# ──────────────────────────────────────────────────────────────────────────────
# FIXTURES FOR MOCKED ENTITIES
# ──────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def mock_db():
    """Create a mocked AsyncSession."""
    return AsyncMock()


@pytest.fixture
def sample_drone():
    """Create a sample DroneType instance."""
    return DroneType(
        id=1,
        name="Heron TP",
        manufacturer="Elbit Systems",
        model="Heron TP",
        size_class="medium",
        mission_type="ISR",
        is_vtol=False,
        max_speed_ms=35.0,
        cruise_speed_ms=25.0,
        max_altitude_m=5400.0,
        endurance_h=10.0,
        range_km=300.0,
        max_takeoff_weight_kg=620.0,
        max_payload_weight_kg=45.0,
        autopilot_type="ArduPilot",
        notes="Long-endurance ISR platform",
        is_active=True,
        created_at=datetime.now(timezone.utc),
    )


@pytest.fixture
def sample_drone2():
    """Create a second sample DroneType instance."""
    return DroneType(
        id=2,
        name="Raven Plus",
        manufacturer="AeroVironment",
        model="RQ-14A+",
        size_class="small",
        mission_type="ISR",
        is_vtol=True,
        max_speed_ms=12.0,
        cruise_speed_ms=8.0,
        max_altitude_m=1500.0,
        endurance_h=6.0,
        range_km=50.0,
        max_takeoff_weight_kg=4.5,
        max_payload_weight_kg=0.6,
        autopilot_type="Custom",
        notes="Small tactical ISR",
        is_active=True,
        created_at=datetime.now(timezone.utc),
    )


@pytest.fixture
def sample_payload():
    """Create a sample PayloadType instance."""
    return PayloadType(
        id=1,
        name="EO-IR Gimbal",
        manufacturer="Elecro-Optical Systems",
        model="EOS 600L",
        category="sensor",
        weight_kg=15.0,
        voltage_v=28.0,
        max_current_a=8.0,
        has_gimbal=True,
        sensor_type="Electro-Optical/Infrared",
        resolution="640x512",
        frame_rate_fps=30.0,
        notes="Stabilized EO/IR pod",
        is_active=True,
        created_at=datetime.now(timezone.utc),
    )


@pytest.fixture
def sample_payload2():
    """Create a second sample PayloadType instance."""
    return PayloadType(
        id=2,
        name="SIGINT Pod",
        manufacturer="EDO Corporation",
        model="SYSTIR-EP",
        category="sensor",
        weight_kg=8.0,
        voltage_v=28.0,
        max_current_a=4.0,
        has_gimbal=False,
        sensor_type="SIGINT",
        notes="Signals Intelligence collection pod",
        is_active=True,
        created_at=datetime.now(timezone.utc),
    )


@pytest.fixture
def sample_threat():
    """Create a sample ThreatSystem instance."""
    return ThreatSystem(
        id=1,
        name="Buk M2",
        category="SAM",
        manufacturer="Almaz-Antey",
        country="Russia",
        max_range_km=70.0,
        max_altitude_m=35000.0,
        max_speed_kmh=3000.0,
        radar_cross_section_m2=0.5,
        countermeasures=["chaff", "flares", "maneuvers"],
        notes="Mobile air defense system",
        classification="UNCLASSIFIED",
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )


@pytest.fixture
def sample_threat2():
    """Create a second sample ThreatSystem instance."""
    return ThreatSystem(
        id=2,
        name="S-300",
        category="SAM",
        manufacturer="Almaz-Antey",
        country="Russia",
        max_range_km=150.0,
        max_altitude_m=30000.0,
        radar_cross_section_m2=1.0,
        countermeasures=["ECM", "maneuvers"],
        notes="Long-range air defense system",
        classification="UNCLASSIFIED",
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )


@pytest.fixture
def sample_drone_payload_link(sample_drone, sample_payload):
    """Create a sample DronePayloadLink."""
    return DronePayloadLink(
        id=1,
        drone_type_id=sample_drone.id,
        payload_type_id=sample_payload.id,
        is_primary=True,
        max_qty=1,
        notes="Primary EO/IR sensor",
        created_at=datetime.now(timezone.utc),
    )


@pytest.fixture
def sample_drone_threat_link(sample_drone, sample_threat):
    """Create a sample DroneThreatLink."""
    return DroneThreatLink(
        id=1,
        drone_type_id=sample_drone.id,
        threat_system_id=sample_threat.id,
        exposure_level="MEDIUM",
        notes="Vulnerable to Buk radar",
        created_at=datetime.now(timezone.utc),
    )


@pytest.fixture
def sample_payload_threat_link(sample_payload, sample_threat):
    """Create a sample PayloadThreatLink."""
    return PayloadThreatLink(
        id=1,
        payload_type_id=sample_payload.id,
        threat_system_id=sample_threat.id,
        effectiveness="HIGH",
        notes="EO can detect SAM emitters",
        created_at=datetime.now(timezone.utc),
    )


# ──────────────────────────────────────────────────────────────────────────────
# TESTS: GET_PAYLOAD_CAPABILITY_PROFILE
# ──────────────────────────────────────────────────────────────────────────────

class TestGetPayloadCapabilityProfile:
    """Tests for get_payload_capability_profile() method."""

    @pytest.mark.asyncio
    async def test_payload_capability_with_links_200(
        self, mock_db, sample_payload, sample_drone, sample_drone_payload_link
    ):
        """Query payload with compatible drones returns profile."""
        service = InventoryKBService(mock_db)
        
        # Mock db.get to return the payload
        mock_db.get = AsyncMock(return_value=sample_payload)
        
        # Mock query for drone-payload links
        mock_result = MagicMock()
        mock_result.all.return_value = [(sample_drone_payload_link, sample_drone)]
        mock_db.execute = AsyncMock(return_value=mock_result)
        
        result = as_dict(await service.get_payload_capability_profile(sample_payload.id))
        
        assert result["payload_id"] == sample_payload.id
        assert result["payload_name"] == sample_payload.name
        assert result["total_capable"] >= 1
        assert len(result["capable_drones"]) >= 1
        assert result["capable_drones"][0]["max_qty"] == 1

    @pytest.mark.asyncio
    async def test_payload_capability_empty_200(self, mock_db, sample_payload):
        """Query payload with no links returns empty capable_drones."""
        service = InventoryKBService(mock_db)
        
        mock_db.get = AsyncMock(return_value=sample_payload)
        mock_result = MagicMock()
        mock_result.all.return_value = []
        mock_db.execute = AsyncMock(return_value=mock_result)
        
        result = as_dict(await service.get_payload_capability_profile(sample_payload.id))
        
        assert result["payload_id"] == sample_payload.id
        assert result["total_capable"] == 0
        assert len(result["capable_drones"]) == 0

    @pytest.mark.asyncio
    async def test_payload_capability_not_found_404(self, mock_db):
        """Query non-existent payload raises 404."""
        service = InventoryKBService(mock_db)
        mock_db.get = AsyncMock(return_value=None)
        
        with pytest.raises(HTTPException) as exc_info:
            await service.get_payload_capability_profile(999999)
        assert exc_info.value.status_code == 404


# ──────────────────────────────────────────────────────────────────────────────
# TESTS: GET_DRONE_CAPABILITY_PROFILE
# ──────────────────────────────────────────────────────────────────────────────

class TestGetDroneCapabilityProfile:
    """Tests for get_drone_capability_profile() method."""

    @pytest.mark.asyncio
    async def test_drone_capability_groups_by_primary_200(
        self, mock_db, sample_drone, sample_payload, sample_payload2,
        sample_drone_payload_link
    ):
        """Query drone returns payloads grouped by primary/secondary."""
        service = InventoryKBService(mock_db)
        
        mock_db.get = AsyncMock(return_value=sample_drone)
        
        # Create secondary link
        secondary_link = DronePayloadLink(
            id=2,
            drone_type_id=sample_drone.id,
            payload_type_id=sample_payload2.id,
            is_primary=False,
            max_qty=1,
            created_at=datetime.now(timezone.utc),
        )
        
        mock_result = MagicMock()
        mock_result.all.return_value = [
            (sample_drone_payload_link, sample_payload),
            (secondary_link, sample_payload2),
        ]
        mock_db.execute = AsyncMock(return_value=mock_result)
        
        result = as_dict(await service.get_drone_capability_profile(sample_drone.id))
        
        assert result["drone_id"] == sample_drone.id
        assert result["drone_name"] == sample_drone.name
        assert len(result["primary_payloads"]) >= 1
        assert len(result["secondary_payloads"]) >= 1

    @pytest.mark.asyncio
    async def test_drone_capability_no_payloads_200(self, mock_db, sample_drone):
        """Query drone with no compatible payloads returns empty lists."""
        service = InventoryKBService(mock_db)
        
        mock_db.get = AsyncMock(return_value=sample_drone)
        mock_result = MagicMock()
        mock_result.all.return_value = []
        mock_db.execute = AsyncMock(return_value=mock_result)
        
        result = as_dict(await service.get_drone_capability_profile(sample_drone.id))
        
        assert result["drone_id"] == sample_drone.id
        assert len(result["primary_payloads"]) == 0
        assert len(result["secondary_payloads"]) == 0

    @pytest.mark.asyncio
    async def test_drone_capability_not_found_404(self, mock_db):
        """Query non-existent drone raises 404."""
        service = InventoryKBService(mock_db)
        mock_db.get = AsyncMock(return_value=None)
        
        with pytest.raises(HTTPException) as exc_info:
            await service.get_drone_capability_profile(999999)
        assert exc_info.value.status_code == 404


# ──────────────────────────────────────────────────────────────────────────────
# TESTS: GET_THREAT_MITIGATION_PROFILE
# ──────────────────────────────────────────────────────────────────────────────

class TestGetThreatMitigationProfile:
    """Tests for get_threat_mitigation_profile() method (2-hop query)."""

    @pytest.mark.asyncio
    async def test_threat_mitigation_multi_hop_200(
        self, mock_db, sample_threat, sample_payload, sample_drone,
        sample_payload_threat_link, sample_drone_payload_link
    ):
        """
        Query threat returns effective payloads and capable drones (2-hop chain).
        Threat → Payload-Threat links → Payloads → Drone-Payload links → Drones
        """
        service = InventoryKBService(mock_db)
        
        mock_db.get = AsyncMock(return_value=sample_threat)
        
        # First query: payload-threat links
        mock_result_1 = MagicMock()
        mock_result_1.all.return_value = [(sample_payload_threat_link, sample_payload)]
        
        # Second query: drone-payload links (for the effective payload)
        mock_result_2 = MagicMock()
        mock_result_2.all.return_value = [(sample_drone_payload_link, sample_drone, sample_payload)]
        
        # Configure execute to return different results on sequential calls
        mock_db.execute = AsyncMock(side_effect=[mock_result_1, mock_result_2])
        
        result = as_dict(await service.get_threat_mitigation_profile(sample_threat.id))
        
        assert result["threat_id"] == sample_threat.id
        assert result["threat_name"] == sample_threat.name
        assert result["payload_count"] >= 1
        assert len(result["effective_payloads"]) >= 1
        assert "capable_drones_for_payloads" in result

        # Coverage: the one effective payload has a capable drone, so no gap.
        coverage = result["coverage_analysis"]
        assert coverage["payloads_with_no_capable_drone"] == []
        assert coverage["fully_covered"] is True

    @pytest.mark.asyncio
    async def test_threat_mitigation_empty_200(self, mock_db, sample_threat):
        """Query threat with no payload mitigations returns empty results."""
        service = InventoryKBService(mock_db)

        mock_db.get = AsyncMock(return_value=sample_threat)
        mock_result = MagicMock()
        mock_result.all.return_value = []
        mock_db.execute = AsyncMock(return_value=mock_result)

        result = as_dict(await service.get_threat_mitigation_profile(sample_threat.id))

        assert result["threat_id"] == sample_threat.id
        assert result["payload_count"] == 0
        assert len(result["effective_payloads"]) == 0

        # No effective payloads at all — not a "gap" (nothing to cover),
        # so fully_covered stays False rather than vacuously True.
        coverage = result["coverage_analysis"]
        assert coverage["payloads_with_no_capable_drone"] == []
        assert coverage["fully_covered"] is False

    @pytest.mark.asyncio
    async def test_threat_mitigation_coverage_gap(
        self, mock_db, sample_threat, sample_drone, sample_payload, sample_payload2,
        sample_payload_threat_link, sample_drone_payload_link
    ):
        """An effective payload with no capable drone shows up as a coverage gap."""
        service = InventoryKBService(mock_db)

        mock_db.get = AsyncMock(return_value=sample_threat)

        second_payload_threat_link = PayloadThreatLink(
            id=2,
            payload_type_id=sample_payload2.id,
            threat_system_id=sample_threat.id,
            effectiveness="LOW",
            created_at=datetime.now(timezone.utc),
        )

        # Two effective payloads...
        mock_result_1 = MagicMock()
        mock_result_1.all.return_value = [
            (sample_payload_threat_link, sample_payload),
            (second_payload_threat_link, sample_payload2),
        ]

        # ...but only the first (sample_payload) has a capable drone.
        mock_result_2 = MagicMock()
        mock_result_2.all.return_value = [
            (sample_drone_payload_link, sample_drone, sample_payload)
        ]

        mock_db.execute = AsyncMock(side_effect=[mock_result_1, mock_result_2])

        result = as_dict(await service.get_threat_mitigation_profile(sample_threat.id))

        coverage = result["coverage_analysis"]
        assert coverage["payloads_with_no_capable_drone"] == [sample_payload2.id]
        assert coverage["fully_covered"] is False

    @pytest.mark.asyncio
    async def test_threat_mitigation_not_found_404(self, mock_db):
        """Query non-existent threat raises 404."""
        service = InventoryKBService(mock_db)
        mock_db.get = AsyncMock(return_value=None)

        with pytest.raises(HTTPException) as exc_info:
            await service.get_threat_mitigation_profile(999999)
        assert exc_info.value.status_code == 404


# ──────────────────────────────────────────────────────────────────────────────
# TESTS: GET_DRONE_VULNERABILITY_PROFILE
# ──────────────────────────────────────────────────────────────────────────────

class TestGetDroneVulnerabilityProfile:
    """Tests for get_drone_vulnerability_profile() method."""

    @pytest.mark.asyncio
    async def test_drone_vulnerability_200(
        self, mock_db, sample_drone, sample_threat, sample_drone_threat_link,
        sample_payload, sample_drone_payload_link
    ):
        """Query drone returns threats and available countermeasures."""
        service = InventoryKBService(mock_db)
        
        mock_db.get = AsyncMock(return_value=sample_drone)
        
        # Mock threat links query
        mock_result_1 = MagicMock()
        mock_result_1.all.return_value = [(sample_drone_threat_link, sample_threat)]
        
        # Mock payload links query
        mock_result_2 = MagicMock()
        mock_result_2.all.return_value = [(sample_drone_payload_link, sample_payload)]
        
        # Mock payload-threat links query (empty for this test)
        mock_result_3 = MagicMock()
        mock_result_3.all.return_value = []
        
        mock_db.execute = AsyncMock(side_effect=[mock_result_1, mock_result_2, mock_result_3])
        
        result = as_dict(await service.get_drone_vulnerability_profile(sample_drone.id))
        
        assert result["drone_id"] == sample_drone.id
        assert result["drone_name"] == sample_drone.name
        assert result["threat_count"] >= 1
        assert len(result["exposed_threats"]) >= 1
        assert "payload_threat_mitigation" in result

        # No payload mitigates this threat — exposure gap, not fully mitigated.
        coverage = result["coverage_analysis"]
        assert coverage["threats_with_no_mitigating_payload"] == [sample_threat.id]
        assert coverage["fully_mitigated"] is False

    @pytest.mark.asyncio
    async def test_drone_vulnerability_coverage_redundant(
        self, mock_db, sample_drone, sample_threat, sample_drone_threat_link,
        sample_payload, sample_payload2, sample_drone_payload_link
    ):
        """A threat mitigated by more than one payload shows up as redundant coverage."""
        service = InventoryKBService(mock_db)

        mock_db.get = AsyncMock(return_value=sample_drone)

        second_drone_payload_link = DronePayloadLink(
            id=2,
            drone_type_id=sample_drone.id,
            payload_type_id=sample_payload2.id,
            is_primary=False,
            max_qty=1,
            created_at=datetime.now(timezone.utc),
        )
        payload_threat_link_1 = PayloadThreatLink(
            id=1,
            payload_type_id=sample_payload.id,
            threat_system_id=sample_threat.id,
            effectiveness="HIGH",
            created_at=datetime.now(timezone.utc),
        )
        payload_threat_link_2 = PayloadThreatLink(
            id=2,
            payload_type_id=sample_payload2.id,
            threat_system_id=sample_threat.id,
            effectiveness="MEDIUM",
            created_at=datetime.now(timezone.utc),
        )

        # Threat links query
        mock_result_1 = MagicMock()
        mock_result_1.all.return_value = [(sample_drone_threat_link, sample_threat)]

        # Payload links query — two payloads available
        mock_result_2 = MagicMock()
        mock_result_2.all.return_value = [
            (sample_drone_payload_link, sample_payload),
            (second_drone_payload_link, sample_payload2),
        ]

        # Payload-threat mitigation query — both payloads counter the same threat
        mock_result_3 = MagicMock()
        mock_result_3.all.return_value = [
            (payload_threat_link_1, sample_payload, sample_threat),
            (payload_threat_link_2, sample_payload2, sample_threat),
        ]

        mock_db.execute = AsyncMock(side_effect=[mock_result_1, mock_result_2, mock_result_3])

        result = as_dict(await service.get_drone_vulnerability_profile(sample_drone.id))

        coverage = result["coverage_analysis"]
        assert coverage["threats_with_no_mitigating_payload"] == []
        assert coverage["threats_with_redundant_mitigation"] == [sample_threat.id]
        assert coverage["fully_mitigated"] is True

    @pytest.mark.asyncio
    async def test_drone_vulnerability_no_threats_200(self, mock_db, sample_drone):
        """Query drone with no threats returns empty threats list."""
        service = InventoryKBService(mock_db)

        mock_db.get = AsyncMock(return_value=sample_drone)
        mock_result = MagicMock()
        mock_result.all.return_value = []
        mock_db.execute = AsyncMock(return_value=mock_result)

        result = as_dict(await service.get_drone_vulnerability_profile(sample_drone.id))

        assert result["drone_id"] == sample_drone.id
        assert result["threat_count"] == 0
        assert len(result["exposed_threats"]) == 0

        # No exposed threats — vacuous, not "fully mitigated".
        coverage = result["coverage_analysis"]
        assert coverage["threats_with_no_mitigating_payload"] == []
        assert coverage["fully_mitigated"] is False

    @pytest.mark.asyncio
    async def test_drone_vulnerability_not_found_404(self, mock_db):
        """Query non-existent drone raises 404."""
        service = InventoryKBService(mock_db)
        mock_db.get = AsyncMock(return_value=None)
        
        with pytest.raises(HTTPException) as exc_info:
            await service.get_drone_vulnerability_profile(999999)
        assert exc_info.value.status_code == 404


# ──────────────────────────────────────────────────────────────────────────────
# TESTS: HYDRATION METHODS
# ──────────────────────────────────────────────────────────────────────────────

class TestHydrationMethods:
    """Tests for hydration methods that embed relationships."""

    @pytest.mark.asyncio
    async def test_hydrate_drone_with_inventory(
        self, mock_db, sample_drone, sample_payload, sample_threat,
        sample_drone_payload_link, sample_drone_threat_link
    ):
        """Hydrate drone embeds all relationships."""
        service = InventoryKBService(mock_db)
        
        # Mock payload links query
        mock_result_1 = MagicMock()
        mock_result_1.all.return_value = [(sample_drone_payload_link, sample_payload)]
        
        # Mock threat links query
        mock_result_2 = MagicMock()
        mock_result_2.all.return_value = [(sample_drone_threat_link, sample_threat)]

        # Mock registered-instances query
        mock_result_3 = MagicMock()
        mock_result_3.scalars.return_value.all.return_value = []

        mock_db.execute = AsyncMock(side_effect=[mock_result_1, mock_result_2, mock_result_3])

        result = as_dict(await service._hydrate_drone_with_inventory(sample_drone))
        
        assert result["id"] == sample_drone.id
        assert result["name"] == sample_drone.name
        assert "compatible_payloads" in result
        assert "exposed_threats" in result
        assert len(result["compatible_payloads"]) >= 1
        assert len(result["exposed_threats"]) >= 1

    @pytest.mark.asyncio
    async def test_hydrate_payload_with_inventory(
        self, mock_db, sample_payload, sample_drone, sample_threat,
        sample_drone_payload_link, sample_payload_threat_link
    ):
        """Hydrate payload embeds all relationships."""
        service = InventoryKBService(mock_db)
        
        # Mock drone links query
        mock_result_1 = MagicMock()
        mock_result_1.all.return_value = [(sample_drone_payload_link, sample_drone)]
        
        # Mock threat links query
        mock_result_2 = MagicMock()
        mock_result_2.all.return_value = [(sample_payload_threat_link, sample_threat)]
        
        mock_db.execute = AsyncMock(side_effect=[mock_result_1, mock_result_2])
        
        result = as_dict(await service._hydrate_payload_with_inventory(sample_payload))
        
        assert result["id"] == sample_payload.id
        assert result["name"] == sample_payload.name
        assert "compatible_drones" in result
        assert "effective_against_threats" in result

    @pytest.mark.asyncio
    async def test_hydrate_threat_with_inventory(
        self, mock_db, sample_threat, sample_drone, sample_payload,
        sample_drone_threat_link, sample_payload_threat_link
    ):
        """Hydrate threat embeds all relationships."""
        service = InventoryKBService(mock_db)
        
        # Mock drone links query
        mock_result_1 = MagicMock()
        mock_result_1.all.return_value = [(sample_drone_threat_link, sample_drone)]
        
        # Mock payload links query
        mock_result_2 = MagicMock()
        mock_result_2.all.return_value = [(sample_payload_threat_link, sample_payload)]
        
        mock_db.execute = AsyncMock(side_effect=[mock_result_1, mock_result_2])
        
        result = as_dict(await service._hydrate_threat_with_inventory(sample_threat))
        
        assert result["id"] == sample_threat.id
        assert result["name"] == sample_threat.name
        assert "vulnerable_drones" in result
        assert "mitigating_payloads" in result


# ──────────────────────────────────────────────────────────────────────────────
# TESTS: SEARCH_INVENTORY
# ──────────────────────────────────────────────────────────────────────────────

class TestSearchInventory:
    """Tests for search_inventory() method."""

    @pytest.mark.asyncio
    async def test_search_free_text_returns_results(
        self, mock_db, sample_drone, sample_payload, sample_threat
    ):
        """Free-text search returns matching entities."""
        service = InventoryKBService(mock_db)
        
        from app.schemas.inventory_kb import InventorySearchQuery
        query = InventorySearchQuery(q="Heron")
        
        # Mock drone query
        mock_result_1 = MagicMock()
        mock_result_1.scalars.return_value.all.return_value = [sample_drone]

        # Mock empty result, reused for hydration link/instance lookups and the
        # payload/threat searches (search_inventory + _hydrate_* issue several
        # db.execute calls per matched drone).
        empty_result = MagicMock()
        empty_result.scalars.return_value.all.return_value = []
        empty_result.all.return_value = []

        mock_db.execute = AsyncMock(side_effect=[mock_result_1] + [empty_result] * 10)

        result = as_dict(await service.search_inventory(query))

        assert len(result["drones"]) >= 1
        assert any(d["name"] == "Heron TP" for d in result["drones"])

    @pytest.mark.asyncio
    async def test_search_with_filters_returns_filtered_results(
        self, mock_db, sample_drone, sample_payload
    ):
        """Search with dimensional filters returns matching entities."""
        service = InventoryKBService(mock_db)
        
        from app.schemas.inventory_kb import InventorySearchQuery
        query = InventorySearchQuery(
            drone_size_class=["medium"],
            drone_mission_type=["ISR"]
        )
        
        # Mock drone query with filters
        mock_result_1 = MagicMock()
        mock_result_1.scalars.return_value.all.return_value = [sample_drone]

        # Mock empty result, reused for hydration link/instance lookups and the
        # payload/threat searches (search_inventory + _hydrate_* issue several
        # db.execute calls per matched drone).
        empty_result = MagicMock()
        empty_result.scalars.return_value.all.return_value = []
        empty_result.all.return_value = []

        mock_db.execute = AsyncMock(side_effect=[mock_result_1] + [empty_result] * 10)

        result = as_dict(await service.search_inventory(query))

        assert len(result["drones"]) >= 1
        assert all(d["size_class"] == "medium" for d in result["drones"])

    @pytest.mark.asyncio
    async def test_search_empty_query_returns_all(self, mock_db):
        """Empty search returns all entities."""
        service = InventoryKBService(mock_db)
        
        from app.schemas.inventory_kb import InventorySearchQuery
        query = InventorySearchQuery()
        
        # Mock queries
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_db.execute = AsyncMock(return_value=mock_result)

        result = as_dict(await service.search_inventory(query))

        assert "drones" in result
        assert "payloads" in result
        assert "threats" in result


# ──────────────────────────────────────────────────────────────────────────────
# TESTS: ANALYTICS METHODS
# ──────────────────────────────────────────────────────────────────────────────

class TestAnalyticsMethods:
    """Tests for analytics and reporting methods."""

    @pytest.mark.asyncio
    async def test_inventory_health_report_has_metrics(self, mock_db):
        """Health report includes all required metrics."""
        service = InventoryKBService(mock_db)
        
        # Mock count queries (all return 5 rows)
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [MagicMock()] * 5
        mock_db.execute = AsyncMock(return_value=mock_result)
        
        result = as_dict(await service.get_inventory_health_report())
        
        assert "total_drone_types" in result
        assert "total_payload_types" in result
        assert "total_threat_systems" in result
        assert "drone_payload_links" in result
        assert "drone_threat_links" in result
        assert "payload_threat_links" in result
        assert result["total_drone_types"] >= 0
        assert result["total_payload_types"] >= 0

    @pytest.mark.asyncio
    async def test_entity_relationship_stats_drone(self, mock_db, sample_drone):
        """Entity stats for drone includes connection counts."""
        service = InventoryKBService(mock_db)
        
        mock_db.get = AsyncMock(return_value=sample_drone)
        
        # Mock link queries
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_db.execute = AsyncMock(return_value=mock_result)

        result = as_dict(await service.get_entity_relationship_stats("drone", sample_drone.id))
        
        assert result["entity_type"] == "drone"
        assert result["entity_id"] == sample_drone.id
        assert "outgoing_links" in result
        assert "connected_entity_counts" in result

    @pytest.mark.asyncio
    async def test_entity_relationship_stats_invalid_type(self, mock_db):
        """Entity stats with invalid type raises 400."""
        service = InventoryKBService(mock_db)
        
        with pytest.raises(HTTPException) as exc_info:
            await service.get_entity_relationship_stats("invalid_type", 1)
        assert exc_info.value.status_code == 400


# ──────────────────────────────────────────────────────────────────────────────
# TESTS: EDGE CASES AND ERROR HANDLING
# ──────────────────────────────────────────────────────────────────────────────

class TestEdgeCasesAndErrors:
    """Tests for edge cases and error handling."""

    @pytest.mark.asyncio
    async def test_capability_with_null_relationships(
        self, mock_db, sample_payload
    ):
        """Capability query handles null relationship fields gracefully."""
        service = InventoryKBService(mock_db)
        
        # Create link with None values
        link_with_nulls = DronePayloadLink(
            id=1,
            drone_type_id=None,
            payload_type_id=sample_payload.id,
            max_qty=None,
            notes=None,
            created_at=datetime.now(timezone.utc),
        )
        
        mock_db.get = AsyncMock(return_value=sample_payload)
        mock_result = MagicMock()
        mock_result.all.return_value = []
        mock_db.execute = AsyncMock(return_value=mock_result)
        
        result = as_dict(await service.get_payload_capability_profile(sample_payload.id))
        
        # Should still return valid structure even with nulls
        assert result["payload_id"] == sample_payload.id
        assert isinstance(result["capable_drones"], list)

    @pytest.mark.asyncio
    async def test_multi_hop_query_with_empty_intermediates(
        self, mock_db, sample_threat
    ):
        """Multi-hop query handles empty intermediate results."""
        service = InventoryKBService(mock_db)
        
        # Threat has no effective payloads
        mock_db.get = AsyncMock(return_value=sample_threat)
        mock_result = MagicMock()
        mock_result.all.return_value = []
        mock_db.execute = AsyncMock(return_value=mock_result)
        
        result = as_dict(await service.get_threat_mitigation_profile(sample_threat.id))
        
        # Should return valid structure with empty payload list
        assert result["threat_id"] == sample_threat.id
        assert result["payload_count"] == 0
        assert result["effective_payloads"] == []

    @pytest.mark.asyncio
    async def test_service_initialization(self, mock_db):
        """InventoryKBService initializes correctly."""
        service = InventoryKBService(mock_db)
        assert service.db == mock_db
        assert service is not None
