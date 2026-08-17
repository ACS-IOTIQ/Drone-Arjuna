"""
Inventory Knowledge-Base API Tests
===================================

Comprehensive test suite for cross-reference queries and inventory KB endpoints.

Coverage:
  - Capability profiles (drones for payload, payloads for drone)
  - Threat analysis (mitigation profiles, vulnerability profiles)
  - Multi-faceted search with dimensional filters
  - Enriched entity views with full relationships
  - Analytics and health reporting
  - Entity relationship statistics
  - Authorization (VIEWER+ for reads, ADMIN for link writes)
  - Error handling (404s, validation errors)
"""

import pytest
import pytest_asyncio
from httpx import AsyncClient
from datetime import datetime, timezone


# ──────────────────────────────────────────────────────────────────────────────
# TEST DATA FIXTURES
# ──────────────────────────────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def kb_drone_type(client: AsyncClient, admin_user, make_token):
    """Create a drone type for KB tests."""
    token = make_token(admin_user.id, admin_user.role)
    hdrs = {"Authorization": f"Bearer {token}"}
    body = {
        "name": "KB-Heron-TP",
        "manufacturer": "Elbit Systems",
        "model": "Heron TP",
        "size_class": "medium",
        "mission_type": "ISR",
        "is_vtol": False,
        "max_speed_ms": 35.0,
        "cruise_speed_ms": 25.0,
        "max_altitude_m": 5400.0,
        "endurance_h": 10.0,
        "range_km": 300.0,
        "max_takeoff_weight_kg": 620.0,
        "max_payload_weight_kg": 45.0,
        "autopilot_type": "ArduPilot",
        "notes": "Long-endurance ISR platform"
    }
    resp = await client.post("/api/master/drone-types", json=body, headers=hdrs)
    assert resp.status_code == 201, resp.text
    data = resp.json()
    yield data
    await client.delete(f"/api/master/drone-types/{data['id']}", headers=hdrs)


@pytest_asyncio.fixture
async def kb_drone_type2(client: AsyncClient, admin_user, make_token):
    """Create a second drone type for comparison tests."""
    token = make_token(admin_user.id, admin_user.role)
    hdrs = {"Authorization": f"Bearer {token}"}
    body = {
        "name": "KB-Raven-Plus",
        "manufacturer": "AeroVironment",
        "model": "RQ-14A+",
        "size_class": "small",
        "mission_type": "ISR",
        "is_vtol": True,
        "max_speed_ms": 12.0,
        "cruise_speed_ms": 8.0,
        "max_altitude_m": 1500.0,
        "endurance_h": 6.0,
        "range_km": 50.0,
        "max_takeoff_weight_kg": 4.5,
        "max_payload_weight_kg": 0.6,
        "autopilot_type": "Custom",
        "notes": "Small tactical ISR"
    }
    resp = await client.post("/api/master/drone-types", json=body, headers=hdrs)
    assert resp.status_code == 201, resp.text
    data = resp.json()
    yield data
    await client.delete(f"/api/master/drone-types/{data['id']}", headers=hdrs)


@pytest_asyncio.fixture
async def kb_payload_type(client: AsyncClient, admin_user, make_token):
    """Create a payload type for KB tests."""
    token = make_token(admin_user.id, admin_user.role)
    hdrs = {"Authorization": f"Bearer {token}"}
    body = {
        "name": "EO-IR-Gimbal",
        "manufacturer": "Elecro-Optical Systems",
        "model": "EOS 600L",
        "category": "sensor",
        "weight_kg": 15.0,
        "voltage_v": 28.0,
        "max_current_a": 8.0,
        "has_gimbal": True,
        "sensor_type": "Electro-Optical/Infrared",
        "resolution": "640x512",
        "frame_rate_fps": 30.0,
        "notes": "Stabilized EO/IR pod"
    }
    resp = await client.post("/api/master/payload-types", json=body, headers=hdrs)
    assert resp.status_code == 201, resp.text
    data = resp.json()
    yield data
    # Cleanup
    try:
        await client.delete(f"/api/master/payload-types/{data['id']}", headers=hdrs)
    except:
        pass


@pytest_asyncio.fixture
async def kb_payload_type2(client: AsyncClient, admin_user, make_token):
    """Create a second payload type for tests."""
    token = make_token(admin_user.id, admin_user.role)
    hdrs = {"Authorization": f"Bearer {token}"}
    body = {
        "name": "SIGINT-Pod",
        "manufacturer": "EDO Corporation",
        "model": "SYSTIR-EP",
        "category": "sensor",
        "weight_kg": 8.0,
        "voltage_v": 28.0,
        "max_current_a": 4.0,
        "has_gimbal": False,
        "sensor_type": "SIGINT",
        "notes": "Signals Intelligence collection pod"
    }
    resp = await client.post("/api/master/payload-types", json=body, headers=hdrs)
    assert resp.status_code == 201, resp.text
    data = resp.json()
    yield data
    try:
        await client.delete(f"/api/master/payload-types/{data['id']}", headers=hdrs)
    except:
        pass


@pytest_asyncio.fixture
async def kb_threat_system(client: AsyncClient, admin_user, make_token):
    """Create a threat system for KB tests."""
    token = make_token(admin_user.id, admin_user.role)
    hdrs = {"Authorization": f"Bearer {token}"}
    body = {
        "name": "Buk M2",
        "category": "SAM",
        "manufacturer": "Almaz-Antey",
        "country": "Russia",
        "max_range_km": 70.0,
        "max_altitude_m": 35000.0,
        "max_speed_kmh": 3000.0,
        "radar_cross_section_m2": 0.5,
        "countermeasures": ["chaff", "flares", "maneuvers"],
        "notes": "Mobile air defense system",
        "classification": "UNCLASSIFIED"
    }
    resp = await client.post("/api/inventory/threat-systems", json=body, headers=hdrs)
    assert resp.status_code == 201, resp.text
    data = resp.json()
    yield data
    await client.delete(f"/api/inventory/threat-systems/{data['id']}", headers=hdrs)


@pytest_asyncio.fixture
async def kb_threat_system2(client: AsyncClient, admin_user, make_token):
    """Create a second threat system for tests."""
    token = make_token(admin_user.id, admin_user.role)
    hdrs = {"Authorization": f"Bearer {token}"}
    body = {
        "name": "S-300",
        "category": "SAM",
        "manufacturer": "Almaz-Antey",
        "country": "Russia",
        "max_range_km": 150.0,
        "max_altitude_m": 30000.0,
        "radar_cross_section_m2": 1.0,
        "countermeasures": ["ECM", "maneuvers"],
        "notes": "Long-range air defense system",
        "classification": "UNCLASSIFIED"
    }
    resp = await client.post("/api/inventory/threat-systems", json=body, headers=hdrs)
    assert resp.status_code == 201, resp.text
    data = resp.json()
    yield data
    await client.delete(f"/api/inventory/threat-systems/{data['id']}", headers=hdrs)


@pytest_asyncio.fixture
async def kb_links_setup(
    client: AsyncClient, 
    admin_user, 
    make_token, 
    kb_drone_type,
    kb_drone_type2,
    kb_payload_type,
    kb_payload_type2,
    kb_threat_system,
    kb_threat_system2
):
    """
    Create a complete set of linking relationships for KB tests.
    
    Topology:
    - Drone1 (Heron) can carry Payload1 (EO/IR) and Payload2 (SIGINT)
    - Drone2 (Raven) can carry Payload2 (SIGINT)
    - Drone1 exposed to Threat1 (Buk) and Threat2 (S-300)
    - Payload1 effective against both threats
    - Payload2 effective against Threat2
    """
    token = make_token(admin_user.id, admin_user.role)
    hdrs = {"Authorization": f"Bearer {token}"}
    
    # Create drone-payload links
    link1_body = {
        "drone_type_id": kb_drone_type["id"],
        "payload_type_id": kb_payload_type["id"],
        "is_primary": True,
        "max_qty": 1,
        "notes": "Primary EO/IR imaging sensor"
    }
    resp = await client.post("/api/inventory/links/drone-payload", json=link1_body, headers=hdrs)
    assert resp.status_code == 201
    link1 = resp.json()
    
    link2_body = {
        "drone_type_id": kb_drone_type["id"],
        "payload_type_id": kb_payload_type2["id"],
        "is_primary": False,
        "max_qty": 1,
        "notes": "Secondary SIGINT pod"
    }
    resp = await client.post("/api/inventory/links/drone-payload", json=link2_body, headers=hdrs)
    assert resp.status_code == 201
    link2 = resp.json()
    
    link3_body = {
        "drone_type_id": kb_drone_type2["id"],
        "payload_type_id": kb_payload_type2["id"],
        "is_primary": True,
        "max_qty": 1,
        "notes": "Only compatible payload for Raven"
    }
    resp = await client.post("/api/inventory/links/drone-payload", json=link3_body, headers=hdrs)
    assert resp.status_code == 201
    link3 = resp.json()
    
    # Create drone-threat links
    threat_link1_body = {
        "drone_type_id": kb_drone_type["id"],
        "threat_system_id": kb_threat_system["id"],
        "exposure_level": "MEDIUM",
        "notes": "Vulnerable to Buk radar"
    }
    resp = await client.post("/api/inventory/links/drone-threat", json=threat_link1_body, headers=hdrs)
    assert resp.status_code == 201
    threat_link1 = resp.json()
    
    threat_link2_body = {
        "drone_type_id": kb_drone_type["id"],
        "threat_system_id": kb_threat_system2["id"],
        "exposure_level": "HIGH",
        "notes": "Highly vulnerable to S-300"
    }
    resp = await client.post("/api/inventory/links/drone-threat", json=threat_link2_body, headers=hdrs)
    assert resp.status_code == 201
    threat_link2 = resp.json()
    
    # Create payload-threat links
    payload_threat1_body = {
        "payload_type_id": kb_payload_type["id"],
        "threat_system_id": kb_threat_system["id"],
        "effectiveness": "HIGH",
        "notes": "EO can detect SAM emitters"
    }
    resp = await client.post("/api/inventory/links/payload-threat", json=payload_threat1_body, headers=hdrs)
    assert resp.status_code == 201
    payload_threat1 = resp.json()
    
    payload_threat2_body = {
        "payload_type_id": kb_payload_type["id"],
        "threat_system_id": kb_threat_system2["id"],
        "effectiveness": "MEDIUM",
        "notes": "EO/IR can detect S-300 launch signatures"
    }
    resp = await client.post("/api/inventory/links/payload-threat", json=payload_threat2_body, headers=hdrs)
    assert resp.status_code == 201
    payload_threat2 = resp.json()
    
    payload_threat3_body = {
        "payload_type_id": kb_payload_type2["id"],
        "threat_system_id": kb_threat_system2["id"],
        "effectiveness": "HIGH",
        "notes": "SIGINT can locate SAM emitters"
    }
    resp = await client.post("/api/inventory/links/payload-threat", json=payload_threat3_body, headers=hdrs)
    assert resp.status_code == 201
    payload_threat3 = resp.json()
    
    yield {
        "drones": (kb_drone_type, kb_drone_type2),
        "payloads": (kb_payload_type, kb_payload_type2),
        "threats": (kb_threat_system, kb_threat_system2),
        "drone_payload_links": (link1, link2, link3),
        "drone_threat_links": (threat_link1, threat_link2),
        "payload_threat_links": (payload_threat1, payload_threat2, payload_threat3),
    }


# ──────────────────────────────────────────────────────────────────────────────
# CAPABILITY PROFILE TESTS
# ──────────────────────────────────────────────────────────────────────────────

class TestCapabilityProfiles:
    """Tests for capability profile queries."""

    async def test_payload_capability_profile_200(
        self, client: AsyncClient, viewer_user, make_token, kb_links_setup
    ):
        """Query: Which drones can carry payload X?"""
        token = make_token(viewer_user.id, viewer_user.role)
        hdrs = {"Authorization": f"Bearer {token}"}
        payload_id = kb_links_setup["payloads"][0]["id"]  # EO-IR
        
        resp = await client.get(
            f"/api/inventory/kb/capabilities/payload/{payload_id}",
            headers=hdrs
        )
        assert resp.status_code == 200
        data = resp.json()
        
        # Should return payload info and capable drones
        assert data["payload_id"] == payload_id
        assert data["payload_name"] == "EO-IR-Gimbal"
        assert data["total_capable"] >= 1
        assert len(data["capable_drones"]) >= 1
        
        # Check drone details are embedded
        for drone_link in data["capable_drones"]:
            assert "drone" in drone_link
            assert "payload" in drone_link
            assert drone_link["max_qty"] >= 1

    async def test_payload_capability_profile_empty_200(
        self, client: AsyncClient, viewer_user, make_token, kb_payload_type
    ):
        """Query with no links returns empty capable_drones."""
        token = make_token(viewer_user.id, viewer_user.role)
        hdrs = {"Authorization": f"Bearer {token}"}
        
        resp = await client.get(
            f"/api/inventory/kb/capabilities/payload/{kb_payload_type['id']}",
            headers=hdrs
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_capable"] == 0
        assert len(data["capable_drones"]) == 0

    async def test_payload_capability_profile_404(
        self, client: AsyncClient, viewer_user, make_token
    ):
        """Query non-existent payload returns 404."""
        token = make_token(viewer_user.id, viewer_user.role)
        hdrs = {"Authorization": f"Bearer {token}"}
        
        resp = await client.get(
            "/api/inventory/kb/capabilities/payload/999999",
            headers=hdrs
        )
        assert resp.status_code == 404

    async def test_drone_capability_profile_200(
        self, client: AsyncClient, viewer_user, make_token, kb_links_setup
    ):
        """Query: What payloads can drone D carry?"""
        token = make_token(viewer_user.id, viewer_user.role)
        hdrs = {"Authorization": f"Bearer {token}"}
        drone_id = kb_links_setup["drones"][0]["id"]  # Heron
        
        resp = await client.get(
            f"/api/inventory/kb/capabilities/drone/{drone_id}",
            headers=hdrs
        )
        assert resp.status_code == 200
        data = resp.json()
        
        assert data["drone_id"] == drone_id
        assert data["drone_name"] == "KB-Heron-TP"
        assert "primary_payloads" in data
        assert "secondary_payloads" in data
        assert len(data["primary_payloads"]) >= 1
        assert len(data["secondary_payloads"]) >= 1

    async def test_drone_capability_profile_404(
        self, client: AsyncClient, viewer_user, make_token
    ):
        """Query non-existent drone returns 404."""
        token = make_token(viewer_user.id, viewer_user.role)
        hdrs = {"Authorization": f"Bearer {token}"}
        
        resp = await client.get(
            "/api/inventory/kb/capabilities/drone/999999",
            headers=hdrs
        )
        assert resp.status_code == 404

    async def test_capability_profile_requires_auth_401(self, client: AsyncClient):
        """KB queries require authentication."""
        resp = await client.get("/api/inventory/kb/capabilities/payload/1")
        assert resp.status_code == 401


# ──────────────────────────────────────────────────────────────────────────────
# THREAT ANALYSIS TESTS
# ──────────────────────────────────────────────────────────────────────────────

class TestThreatAnalysis:
    """Tests for threat mitigation and vulnerability profiles."""

    async def test_threat_mitigation_profile_200(
        self, client: AsyncClient, viewer_user, make_token, kb_links_setup
    ):
        """Query: How do we defeat threat T? (Multi-hop chain)"""
        token = make_token(viewer_user.id, viewer_user.role)
        hdrs = {"Authorization": f"Bearer {token}"}
        threat_id = kb_links_setup["threats"][0]["id"]  # Buk
        
        resp = await client.get(
            f"/api/inventory/kb/threats/mitigation/{threat_id}",
            headers=hdrs
        )
        assert resp.status_code == 200
        data = resp.json()
        
        assert data["threat_id"] == threat_id
        assert data["threat_name"] == "Buk M2"
        assert data["threat_category"] == "SAM"
        
        # Should have effective payloads
        assert data["payload_count"] >= 1
        assert len(data["effective_payloads"]) >= 1
        
        # Should show capable drones for each payload
        assert "capable_drones_for_payloads" in data
        for payload_id, drone_links in data["capable_drones_for_payloads"].items():
            assert len(drone_links) >= 1
            for link in drone_links:
                assert "drone" in link
                assert "payload" in link

    async def test_threat_mitigation_profile_empty_200(
        self, client: AsyncClient, viewer_user, make_token, kb_threat_system
    ):
        """Query threat with no mitigation links returns empty results."""
        token = make_token(viewer_user.id, viewer_user.role)
        hdrs = {"Authorization": f"Bearer {token}"}
        
        resp = await client.get(
            f"/api/inventory/kb/threats/mitigation/{kb_threat_system['id']}",
            headers=hdrs
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["payload_count"] == 0
        assert len(data["effective_payloads"]) == 0

    async def test_threat_mitigation_profile_404(
        self, client: AsyncClient, viewer_user, make_token
    ):
        """Query non-existent threat returns 404."""
        token = make_token(viewer_user.id, viewer_user.role)
        hdrs = {"Authorization": f"Bearer {token}"}
        
        resp = await client.get(
            "/api/inventory/kb/threats/mitigation/999999",
            headers=hdrs
        )
        assert resp.status_code == 404

    async def test_drone_vulnerability_profile_200(
        self, client: AsyncClient, viewer_user, make_token, kb_links_setup
    ):
        """Query: What threats threaten drone D?"""
        token = make_token(viewer_user.id, viewer_user.role)
        hdrs = {"Authorization": f"Bearer {token}"}
        drone_id = kb_links_setup["drones"][0]["id"]  # Heron (exposed to threats)
        
        resp = await client.get(
            f"/api/inventory/kb/threats/vulnerability/{drone_id}",
            headers=hdrs
        )
        assert resp.status_code == 200
        data = resp.json()
        
        assert data["drone_id"] == drone_id
        assert data["drone_name"] == "KB-Heron-TP"
        assert data["threat_count"] >= 2  # Should have 2 threats
        
        # Should list exposed threats
        assert len(data["exposed_threats"]) >= 2
        for threat_link in data["exposed_threats"]:
            assert threat_link["exposure_level"] in ["LOW", "MEDIUM", "HIGH", "CRITICAL"]
            assert "threat" in threat_link
        
        # Should show available payloads
        assert len(data["available_payloads"]) >= 1
        
        # Should show payload-threat mitigation matrix
        assert "payload_threat_mitigation" in data

    async def test_drone_vulnerability_profile_no_threats_200(
        self, client: AsyncClient, viewer_user, make_token, kb_drone_type2
    ):
        """Query drone with no threat exposure returns empty threats."""
        token = make_token(viewer_user.id, viewer_user.role)
        hdrs = {"Authorization": f"Bearer {token}"}
        
        resp = await client.get(
            f"/api/inventory/kb/threats/vulnerability/{kb_drone_type2['id']}",
            headers=hdrs
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["threat_count"] == 0

    async def test_drone_vulnerability_profile_404(
        self, client: AsyncClient, viewer_user, make_token
    ):
        """Query non-existent drone returns 404."""
        token = make_token(viewer_user.id, viewer_user.role)
        hdrs = {"Authorization": f"Bearer {token}"}
        
        resp = await client.get(
            "/api/inventory/kb/threats/vulnerability/999999",
            headers=hdrs
        )
        assert resp.status_code == 404


# ──────────────────────────────────────────────────────────────────────────────
# SEARCH TESTS
# ──────────────────────────────────────────────────────────────────────────────

class TestInventorySearch:
    """Tests for multi-faceted inventory search."""

    async def test_search_inventory_free_text_200(
        self, client: AsyncClient, viewer_user, make_token, kb_links_setup
    ):
        """Search with free-text query."""
        token = make_token(viewer_user.id, viewer_user.role)
        hdrs = {"Authorization": f"Bearer {token}"}
        
        resp = await client.post(
            "/api/inventory/kb/search",
            json={"q": "Heron"},
            headers=hdrs
        )
        assert resp.status_code == 200
        data = resp.json()
        
        assert "drones" in data
        assert "payloads" in data
        assert "threats" in data
        assert len(data["drones"]) >= 1
        assert any(d["name"] == "KB-Heron-TP" for d in data["drones"])

    async def test_search_inventory_drone_filters_200(
        self, client: AsyncClient, viewer_user, make_token, kb_links_setup
    ):
        """Search with drone-specific filters."""
        token = make_token(viewer_user.id, viewer_user.role)
        hdrs = {"Authorization": f"Bearer {token}"}
        
        resp = await client.post(
            "/api/inventory/kb/search",
            json={
                "drone_size_class": ["medium"],
                "drone_mission_type": ["ISR"],
                "drone_min_endurance_h": 5.0,
            },
            headers=hdrs
        )
        assert resp.status_code == 200
        data = resp.json()
        
        # Should find Heron (medium, ISR, 10h endurance)
        assert len(data["drones"]) >= 1
        for drone in data["drones"]:
            assert drone["size_class"] == "medium"
            assert drone["mission_type"] == "ISR"
            assert drone["endurance_h"] >= 5.0

    async def test_search_inventory_payload_filters_200(
        self, client: AsyncClient, viewer_user, make_token, kb_links_setup
    ):
        """Search with payload-specific filters."""
        token = make_token(viewer_user.id, viewer_user.role)
        hdrs = {"Authorization": f"Bearer {token}"}
        
        resp = await client.post(
            "/api/inventory/kb/search",
            json={
                "payload_category": ["sensor"],
                "payload_max_weight_kg": 20.0,
            },
            headers=hdrs
        )
        assert resp.status_code == 200
        data = resp.json()
        
        assert len(data["payloads"]) >= 1
        for payload in data["payloads"]:
            assert payload["category"] == "sensor"
            assert payload["weight_kg"] <= 20.0

    async def test_search_inventory_threat_filters_200(
        self, client: AsyncClient, viewer_user, make_token, kb_links_setup
    ):
        """Search with threat-specific filters."""
        token = make_token(viewer_user.id, viewer_user.role)
        hdrs = {"Authorization": f"Bearer {token}"}
        
        resp = await client.post(
            "/api/inventory/kb/search",
            json={
                "threat_category": ["SAM"],
                "threat_country": ["Russia"],
            },
            headers=hdrs
        )
        assert resp.status_code == 200
        data = resp.json()
        
        assert len(data["threats"]) >= 1
        for threat in data["threats"]:
            assert threat["category"] == "SAM"
            assert threat["country"] == "Russia"

    async def test_search_inventory_empty_query_200(
        self, client: AsyncClient, viewer_user, make_token, kb_links_setup
    ):
        """Empty search returns all entities."""
        token = make_token(viewer_user.id, viewer_user.role)
        hdrs = {"Authorization": f"Bearer {token}"}
        
        resp = await client.post(
            "/api/inventory/kb/search",
            json={},
            headers=hdrs
        )
        assert resp.status_code == 200
        data = resp.json()
        
        # Should return all entities (within limit)
        assert "drones" in data
        assert "payloads" in data
        assert "threats" in data

    async def test_search_inventory_pagination_200(
        self, client: AsyncClient, viewer_user, make_token, kb_links_setup
    ):
        """Search respects limit and offset."""
        token = make_token(viewer_user.id, viewer_user.role)
        hdrs = {"Authorization": f"Bearer {token}"}
        
        resp = await client.post(
            "/api/inventory/kb/search",
            json={"limit": 10, "offset": 0},
            headers=hdrs
        )
        assert resp.status_code == 200
        data = resp.json()
        
        # Should have limit applied
        assert len(data["drones"]) <= 10


# ──────────────────────────────────────────────────────────────────────────────
# ENRICHED ENTITY VIEWS TESTS
# ──────────────────────────────────────────────────────────────────────────────

class TestEnrichedEntityViews:
    """Tests for full entity views with embedded relationships."""

    async def test_drone_enriched_view_200(
        self, client: AsyncClient, viewer_user, make_token, kb_links_setup
    ):
        """Get drone with full inventory relationships."""
        token = make_token(viewer_user.id, viewer_user.role)
        hdrs = {"Authorization": f"Bearer {token}"}
        drone_id = kb_links_setup["drones"][0]["id"]
        
        resp = await client.get(
            f"/api/inventory/kb/drones/{drone_id}/full",
            headers=hdrs
        )
        assert resp.status_code == 200
        data = resp.json()
        
        # Full drone spec
        assert data["id"] == drone_id
        assert data["name"] == "KB-Heron-TP"
        assert data["max_payload_weight_kg"] == 45.0
        assert data["endurance_h"] == 10.0
        
        # Embedded relationships
        assert "compatible_payloads" in data
        assert len(data["compatible_payloads"]) >= 1
        assert "exposed_threats" in data
        assert len(data["exposed_threats"]) >= 1
        
        # Check payload embedding
        for payload_link in data["compatible_payloads"]:
            assert "payload" in payload_link
            assert payload_link["payload"]["name"] in ["EO-IR-Gimbal", "SIGINT-Pod"]
        
        # Check threat embedding
        for threat_link in data["exposed_threats"]:
            assert "threat" in threat_link
            assert threat_link["threat"]["category"] == "SAM"

    async def test_payload_enriched_view_200(
        self, client: AsyncClient, viewer_user, make_token, kb_links_setup
    ):
        """Get payload with full inventory relationships."""
        token = make_token(viewer_user.id, viewer_user.role)
        hdrs = {"Authorization": f"Bearer {token}"}
        payload_id = kb_links_setup["payloads"][0]["id"]
        
        resp = await client.get(
            f"/api/inventory/kb/payloads/{payload_id}/full",
            headers=hdrs
        )
        assert resp.status_code == 200
        data = resp.json()
        
        assert data["id"] == payload_id
        assert data["name"] == "EO-IR-Gimbal"
        assert data["category"] == "sensor"
        
        # Embedded relationships
        assert "compatible_drones" in data
        assert len(data["compatible_drones"]) >= 1
        assert "effective_against_threats" in data

    async def test_threat_enriched_view_200(
        self, client: AsyncClient, viewer_user, make_token, kb_links_setup
    ):
        """Get threat with full inventory relationships."""
        token = make_token(viewer_user.id, viewer_user.role)
        hdrs = {"Authorization": f"Bearer {token}"}
        threat_id = kb_links_setup["threats"][0]["id"]
        
        resp = await client.get(
            f"/api/inventory/kb/threats/{threat_id}/full",
            headers=hdrs
        )
        assert resp.status_code == 200
        data = resp.json()
        
        assert data["id"] == threat_id
        assert data["name"] == "Buk M2"
        assert data["category"] == "SAM"
        
        # Embedded relationships
        assert "vulnerable_drones" in data
        assert len(data["vulnerable_drones"]) >= 1
        assert "mitigating_payloads" in data

    async def test_enriched_view_404(
        self, client: AsyncClient, viewer_user, make_token
    ):
        """Enriched view of non-existent entity returns 404."""
        token = make_token(viewer_user.id, viewer_user.role)
        hdrs = {"Authorization": f"Bearer {token}"}
        
        resp = await client.get(
            "/api/inventory/kb/drones/999999/full",
            headers=hdrs
        )
        assert resp.status_code == 404


# ──────────────────────────────────────────────────────────────────────────────
# ANALYTICS TESTS
# ──────────────────────────────────────────────────────────────────────────────

class TestAnalytics:
    """Tests for analytics and health reporting."""

    async def test_inventory_health_report_200(
        self, client: AsyncClient, viewer_user, make_token, kb_links_setup
    ):
        """Get inventory health metrics."""
        token = make_token(viewer_user.id, viewer_user.role)
        hdrs = {"Authorization": f"Bearer {token}"}
        
        resp = await client.get(
            "/api/inventory/kb/analytics/health",
            headers=hdrs
        )
        assert resp.status_code == 200
        data = resp.json()
        
        # Should have entity counts
        assert data["total_drone_types"] >= 2
        assert data["total_payload_types"] >= 2
        assert data["total_threat_systems"] >= 2
        
        # Should have link counts
        assert data["drone_payload_links"] >= 3
        assert data["drone_threat_links"] >= 2
        assert data["payload_threat_links"] >= 3
        
        # Should have coverage metrics
        assert "drones_with_payloads" in data
        assert "drones_with_threats" in data
        assert "unmapped_drones" in data or isinstance(data.get("unmapped_drones"), list)

    async def test_entity_relationship_stats_drone_200(
        self, client: AsyncClient, viewer_user, make_token, kb_links_setup
    ):
        """Get relationship statistics for a drone."""
        token = make_token(viewer_user.id, viewer_user.role)
        hdrs = {"Authorization": f"Bearer {token}"}
        drone_id = kb_links_setup["drones"][0]["id"]
        
        resp = await client.get(
            f"/api/inventory/kb/analytics/entity/drone/{drone_id}",
            headers=hdrs
        )
        assert resp.status_code == 200
        data = resp.json()
        
        assert data["entity_type"] == "drone"
        assert data["entity_id"] == drone_id
        assert data["outgoing_links"] >= 3  # 2 threats + 2 payloads
        assert "connected_entity_counts" in data

    async def test_entity_relationship_stats_payload_200(
        self, client: AsyncClient, viewer_user, make_token, kb_links_setup
    ):
        """Get relationship statistics for a payload."""
        token = make_token(viewer_user.id, viewer_user.role)
        hdrs = {"Authorization": f"Bearer {token}"}
        payload_id = kb_links_setup["payloads"][0]["id"]
        
        resp = await client.get(
            f"/api/inventory/kb/analytics/entity/payload/{payload_id}",
            headers=hdrs
        )
        assert resp.status_code == 200
        data = resp.json()
        
        assert data["entity_type"] == "payload"
        assert data["entity_id"] == payload_id
        assert data["outgoing_links"] >= 3  # At least 1 drone + 2 threats

    async def test_entity_relationship_stats_threat_200(
        self, client: AsyncClient, viewer_user, make_token, kb_links_setup
    ):
        """Get relationship statistics for a threat."""
        token = make_token(viewer_user.id, viewer_user.role)
        hdrs = {"Authorization": f"Bearer {token}"}
        threat_id = kb_links_setup["threats"][0]["id"]
        
        resp = await client.get(
            f"/api/inventory/kb/analytics/entity/threat/{threat_id}",
            headers=hdrs
        )
        assert resp.status_code == 200
        data = resp.json()
        
        assert data["entity_type"] == "threat"
        assert data["entity_id"] == threat_id
        assert data["incoming_links"] >= 1  # At least 1 drone or payload


# ──────────────────────────────────────────────────────────────────────────────
# AUTHORIZATION TESTS
# ──────────────────────────────────────────────────────────────────────────────

class TestKBAuthorization:
    """Tests for role-based access control."""

    async def test_kb_queries_require_viewer_role_401(self, client: AsyncClient):
        """All KB read endpoints require VIEWER+ role."""
        # No auth header
        resp = await client.get("/api/inventory/kb/capabilities/payload/1")
        assert resp.status_code == 401
        
        resp = await client.get("/api/inventory/kb/capabilities/drone/1")
        assert resp.status_code == 401
        
        resp = await client.get("/api/inventory/kb/threats/mitigation/1")
        assert resp.status_code == 401

    async def test_kb_queries_accessible_to_viewer_200(
        self, client: AsyncClient, viewer_user, make_token, kb_payload_type
    ):
        """KB read endpoints accessible to VIEWER role."""
        token = make_token(viewer_user.id, viewer_user.role)
        hdrs = {"Authorization": f"Bearer {token}"}
        
        resp = await client.get(
            f"/api/inventory/kb/capabilities/payload/{kb_payload_type['id']}",
            headers=hdrs
        )
        assert resp.status_code == 200

    async def test_link_creation_requires_admin_role_401(
        self, client: AsyncClient, viewer_user, make_token,
        kb_drone_type, kb_payload_type
    ):
        """Link creation requires ADMIN role."""
        token = make_token(viewer_user.id, viewer_user.role)
        hdrs = {"Authorization": f"Bearer {token}"}
        
        body = {
            "drone_type_id": kb_drone_type["id"],
            "payload_type_id": kb_payload_type["id"],
            "is_primary": True,
            "max_qty": 1
        }
        resp = await client.post(
            "/api/inventory/links/drone-payload",
            json=body,
            headers=hdrs
        )
        # VIEWER role should not be able to create links
        assert resp.status_code == 403

    async def test_link_creation_allowed_for_admin_201(
        self, client: AsyncClient, admin_user, make_token,
        kb_drone_type, kb_payload_type
    ):
        """Link creation allowed for ADMIN role."""
        token = make_token(admin_user.id, admin_user.role)
        hdrs = {"Authorization": f"Bearer {token}"}
        
        body = {
            "drone_type_id": kb_drone_type["id"],
            "payload_type_id": kb_payload_type["id"],
            "is_primary": True,
            "max_qty": 1
        }
        resp = await client.post(
            "/api/inventory/links/drone-payload",
            json=body,
            headers=hdrs
        )
        assert resp.status_code == 201
        
        # Cleanup
        link_id = resp.json()["id"]
        await client.delete(
            f"/api/inventory/links/drone-payload/{link_id}",
            headers=hdrs
        )


# ──────────────────────────────────────────────────────────────────────────────
# INTEGRATION TESTS
# ──────────────────────────────────────────────────────────────────────────────

class TestKBIntegration:
    """End-to-end integration tests."""

    async def test_complete_mission_planning_workflow(
        self, client: AsyncClient, viewer_user, make_token, kb_links_setup
    ):
        """Complete workflow: search → capability → vulnerability → recommend."""
        token = make_token(viewer_user.id, viewer_user.role)
        hdrs = {"Authorization": f"Bearer {token}"}
        
        # Step 1: Search for ISR drones
        resp = await client.post(
            "/api/inventory/kb/search",
            json={
                "drone_mission_type": ["ISR"],
                "drone_min_endurance_h": 6.0
            },
            headers=hdrs
        )
        assert resp.status_code == 200
        drones = resp.json()["drones"]
        assert len(drones) >= 1
        drone_id = drones[0]["id"]
        
        # Step 2: Check drone vulnerability in threat environment
        resp = await client.get(
            f"/api/inventory/kb/threats/vulnerability/{drone_id}",
            headers=hdrs
        )
        assert resp.status_code == 200
        vuln_profile = resp.json()
        threat_count = vuln_profile["threat_count"]
        
        # Step 3: For each threat, check mitigation
        for threat_link in vuln_profile["exposed_threats"][:1]:  # Check first threat
            threat_id = threat_link["threat"]["id"]
            resp = await client.get(
                f"/api/inventory/kb/threats/mitigation/{threat_id}",
                headers=hdrs
            )
            assert resp.status_code == 200
            mitigation = resp.json()
            # Should have some counter-measures
            assert "effective_payloads" in mitigation
        
        # Step 4: Get full drone spec for recommendation
        resp = await client.get(
            f"/api/inventory/kb/drones/{drone_id}/full",
            headers=hdrs
        )
        assert resp.status_code == 200
        full_spec = resp.json()
        
        # Verify complete recommendation chain is available
        assert full_spec["compatible_payloads"] is not None
        assert full_spec["exposed_threats"] is not None

    async def test_threat_assessment_workflow(
        self, client: AsyncClient, viewer_user, make_token, kb_links_setup
    ):
        """Threat assessment: analyze fleet exposure and response capability."""
        token = make_token(viewer_user.id, viewer_user.role)
        hdrs = {"Authorization": f"Bearer {token}"}
        
        # Get health report
        resp = await client.get(
            "/api/inventory/kb/analytics/health",
            headers=hdrs
        )
        assert resp.status_code == 200
        health = resp.json()
        total_drones = health["total_drone_types"]
        
        # Check each drone's vulnerability
        vulnerable_count = 0
        for i in range(1, min(3, total_drones + 1)):  # Check first 2 drones
            resp = await client.get(
                f"/api/inventory/kb/analytics/entity/drone/{i}",
                headers=hdrs
            )
            if resp.status_code == 200:
                stats = resp.json()
                if stats["outgoing_links"] > 0:
                    vulnerable_count += 1
        
        # Verify threat assessment data is available
        assert health["total_threat_systems"] >= 0
        assert health["payload_threat_links"] >= 0
