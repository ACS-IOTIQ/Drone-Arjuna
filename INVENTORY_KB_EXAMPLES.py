"""
Inventory Knowledge-Base API Usage Examples
============================================
Practical curl/Python examples for using the KB endpoints.
"""

# ──────────────────────────────────────────────────────────────────────────────
# 1. CAPABILITY QUERIES
# ──────────────────────────────────────────────────────────────────────────────

# === CURL ===

# Q: Which drones can carry payload ID 5 (EO/IR camera)?
curl -H "Authorization: Bearer $TOKEN" \
  "http://localhost:8000/api/inventory/kb/capabilities/payload/5"

# Q: What payloads can drone ID 1 (Heron TP) carry?
curl -H "Authorization: Bearer $TOKEN" \
  "http://localhost:8000/api/inventory/kb/capabilities/drone/1"


# === PYTHON (with httpx) ===

import httpx

async with httpx.AsyncClient() as client:
    # Payload capabilities
    response = await client.get(
        "http://localhost:8000/api/inventory/kb/capabilities/payload/5",
        headers={"Authorization": f"Bearer {token}"}
    )
    data = response.json()
    print(f"Payload '{data['payload_name']}' can be carried by:")
    for link in data['capable_drones']:
        print(f"  - {link['drone']['name']} (qty: {link['max_qty']})")


# ──────────────────────────────────────────────────────────────────────────────
# 2. THREAT ANALYSIS QUERIES
# ──────────────────────────────────────────────────────────────────────────────

# === CURL ===

# Q: How do we defeat Russian Buk SAM (threat ID 3)?
curl -H "Authorization: Bearer $TOKEN" \
  "http://localhost:8000/api/inventory/kb/threats/mitigation/3"

# Response structure:
# {
#   "threat_id": 3,
#   "threat_name": "Buk M2",
#   "threat_category": "SAM",
#   "effective_payloads": [
#     {
#       "id": 8,
#       "effectiveness": "HIGH",
#       "payload": {"name": "Krasukha EW Pod", ...}
#     }
#   ],
#   "capable_drones_for_payloads": {
#     "8": [
#       {"drone": {"name": "Heron TP", ...}, "max_qty": 1}
#     ]
#   }
# }


# Q: What threats endanger Heron TP (drone ID 1)?
curl -H "Authorization: Bearer $TOKEN" \
  "http://localhost:8000/api/inventory/kb/threats/vulnerability/1"

# Response includes:
# - Identified threats (with exposure levels)
# - Available payloads to counter each threat
# - Mitigation effectiveness matrix


# === PYTHON (with httpx) ===

import httpx
import json

async def analyze_threat_environment(threat_id: int, token: str):
    """Analyze complete threat mitigation chain."""
    async with httpx.AsyncClient() as client:
        # Get threat mitigation profile
        response = await client.get(
            f"http://localhost:8000/api/inventory/kb/threats/mitigation/{threat_id}",
            headers={"Authorization": f"Bearer {token}"}
        )
        mitigation = response.json()
        
        print(f"\n=== Threat: {mitigation['threat_name']} ===")
        print(f"Category: {mitigation['threat_category']}")
        print(f"\nEffective Payloads ({mitigation['payload_count']}):")
        
        for payload_link in mitigation['effective_payloads']:
            payload = payload_link['payload']
            print(f"  - {payload['name']} (Effectiveness: {payload_link['effectiveness']})")
            
            # Show capable drones
            capable_drones = mitigation['capable_drones_for_payloads'].get(payload['id'], [])
            for drone_link in capable_drones:
                drone = drone_link['drone']
                print(f"    └─ {drone['name']} (qty: {drone_link['max_qty']})")


# ──────────────────────────────────────────────────────────────────────────────
# 3. MULTI-FACETED SEARCH
# ──────────────────────────────────────────────────────────────────────────────

# === CURL ===

# Q: Search for medium/large ISR drones with 6+ hour endurance
curl -X POST -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "q": "ISR",
    "drone_size_class": ["medium", "large"],
    "drone_mission_type": ["ISR"],
    "drone_min_endurance_h": 6.0,
    "limit": 10
  }' \
  "http://localhost:8000/api/inventory/kb/search"

# Q: Search for all RF sensors (antenna systems)
curl -X POST -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "q": "RF",
    "payload_category": ["sensor"],
    "limit": 20
  }' \
  "http://localhost:8000/api/inventory/kb/search"


# === PYTHON (with httpx) ===

import httpx

async def search_mission_capable_drones(
    endurance_hours: float,
    size_classes: list[str],
    token: str
):
    """Find drones suitable for long-endurance ISR mission."""
    async with httpx.AsyncClient() as client:
        response = await client.post(
            "http://localhost:8000/api/inventory/kb/search",
            json={
                "drone_size_class": size_classes,
                "drone_mission_type": ["ISR"],
                "drone_min_endurance_h": endurance_hours,
                "limit": 20
            },
            headers={"Authorization": f"Bearer {token}"}
        )
        results = response.json()
        
        print(f"Found {results['total_drones']} compatible drones:")
        for drone in results['drones']:
            print(f"\n{drone['name']} ({drone['manufacturer']})")
            print(f"  Size: {drone['size_class']}")
            print(f"  Endurance: {drone['endurance_h']}h")
            print(f"  Payloads: {len(drone['compatible_payloads'])} options")


# ──────────────────────────────────────────────────────────────────────────────
# 4. ENRICHED ENTITY VIEWS
# ──────────────────────────────────────────────────────────────────────────────

# === CURL ===

# Q: Get complete Heron TP specification with all relationships
curl -H "Authorization: Bearer $TOKEN" \
  "http://localhost:8000/api/inventory/kb/drones/1/full"

# Response structure:
# {
#   "id": 1,
#   "name": "Heron TP",
#   "max_payload_weight_kg": 45,
#   "compatible_payloads": [...],
#   "exposed_threats": [...],
#   "registered_instances": [...]
# }


# Q: Get complete threat profile for Russian S-300 SAM
curl -H "Authorization: Bearer $TOKEN" \
  "http://localhost:8000/api/inventory/kb/threats/2/full"

# Response shows:
# - Threat specifications
# - All vulnerable drones (with exposure levels)
# - All effective counter-payloads (with effectiveness)


# === PYTHON (with httpx) ===

import httpx

async def get_drone_full_profile(drone_id: int, token: str):
    """Get complete drone specifications with relationships."""
    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"http://localhost:8000/api/inventory/kb/drones/{drone_id}/full",
            headers={"Authorization": f"Bearer {token}"}
        )
        drone = response.json()
        
        print(f"\n=== {drone['name']} ({drone['manufacturer']}) ===")
        print(f"Class: {drone['size_class']}")
        print(f"Mission Type: {drone['mission_type']}")
        print(f"Endurance: {drone['endurance_h']}h")
        print(f"Max Payload: {drone['max_payload_weight_kg']}kg")
        
        print(f"\nCompatible Payloads ({len(drone['compatible_payloads'])}):")
        for payload_link in drone['compatible_payloads']:
            p = payload_link['payload']
            print(f"  {'[PRIMARY]' if payload_link['is_primary'] else '[SECONDARY]'} "
                  f"{p['name']} ({p['weight_kg']}kg)")
        
        print(f"\nExposed Threats ({len(drone['exposed_threats'])}):")
        for threat_link in drone['exposed_threats']:
            t = threat_link['threat']
            print(f"  {t['name']} (Exposure: {threat_link['exposure_level']})")


# ──────────────────────────────────────────────────────────────────────────────
# 5. ANALYTICS & HEALTH REPORTING
# ──────────────────────────────────────────────────────────────────────────────

# === CURL ===

# Q: What's the health of our inventory KB?
curl -H "Authorization: Bearer $TOKEN" \
  "http://localhost:8000/api/inventory/kb/analytics/health"

# Response:
# {
#   "total_drone_types": 12,
#   "total_drone_instances": 47,
#   "total_payload_types": 18,
#   "total_threat_systems": 9,
#   "drone_payload_links": 24,
#   "drone_threat_links": 15,
#   "drones_with_payloads": 10,
#   "unmapped_drones": [5, 12],
#   "unmapped_threats": [3]
# }


# Q: Get relationship stats for drone ID 1
curl -H "Authorization: Bearer $TOKEN" \
  "http://localhost:8000/api/inventory/kb/analytics/entity/drone/1"


# === PYTHON (with httpx) ===

import httpx

async def audit_inventory_completeness(token: str):
    """Check inventory KB for gaps and missing mappings."""
    async with httpx.AsyncClient() as client:
        response = await client.get(
            "http://localhost:8000/api/inventory/kb/analytics/health",
            headers={"Authorization": f"Bearer {token}"}
        )
        health = response.json()
        
        total_drones = health['total_drone_types']
        mapped_drones = health['drones_with_payloads']
        coverage = (mapped_drones / total_drones * 100) if total_drones > 0 else 0
        
        print(f"\n=== Inventory Health Report ===")
        print(f"Entities:")
        print(f"  Drone Types: {health['total_drone_types']}")
        print(f"  Payloads: {health['total_payload_types']}")
        print(f"  Threats: {health['total_threat_systems']}")
        
        print(f"\nLink Coverage:")
        print(f"  Drones with payloads: {mapped_drones}/{total_drones} ({coverage:.1f}%)")
        print(f"  Payload-Threat links: {health['payload_threat_links']}")
        
        if health['unmapped_drones']:
            print(f"\n⚠️  Action Items:")
            print(f"  Unmapped drones: {health['unmapped_drones']}")
            print(f"  Unmapped threats: {health['unmapped_threats']}")


# ──────────────────────────────────────────────────────────────────────────────
# 6. MISSION PLANNING WORKFLOW
# ──────────────────────────────────────────────────────────────────────────────

# === PYTHON WORKFLOW: Plan ISR Mission in Contested Airspace ===

import httpx
from typing import Optional

async def plan_isr_mission(
    endurance_hours: float,
    threat_ids: list[int],
    token: str
) -> Optional[dict]:
    """
    Complete workflow to plan ISR mission with threat mitigation.
    
    Returns recommended drone + payload configuration.
    """
    async with httpx.AsyncClient() as client:
        
        # Step 1: Search for capable drones
        print("Step 1: Finding endurance-capable ISR drones...")
        drone_search = await client.post(
            "http://localhost:8000/api/inventory/kb/search",
            json={
                "drone_mission_type": ["ISR"],
                "drone_min_endurance_h": endurance_hours,
                "limit": 10
            },
            headers={"Authorization": f"Bearer {token}"}
        )
        capable_drones = drone_search.json()['drones']
        print(f"  Found {len(capable_drones)} candidates")
        
        if not capable_drones:
            print("  ❌ No drones meet endurance requirement")
            return None
        
        # Step 2: For each threat, find counter-measures
        print(f"\nStep 2: Analyzing threat environment ({len(threat_ids)} threats)...")
        threat_profiles = []
        for threat_id in threat_ids:
            mitigation = await client.get(
                f"http://localhost:8000/api/inventory/kb/threats/mitigation/{threat_id}",
                headers={"Authorization": f"Bearer {token}"}
            )
            threat_profiles.append(mitigation.json())
        
        # Step 3: Rank drones by capability to carry counter-measures
        print("\nStep 3: Ranking drones by threat mitigation capability...")
        drone_scores = {}
        
        for drone in capable_drones:
            drone_id = drone['id']
            score = 0
            compatible_payloads = []
            
            # Check if this drone can carry payloads that counter the threats
            for threat_profile in threat_profiles:
                for payload_link in threat_profile['effective_payloads']:
                    payload_id = payload_link['payload']['id']
                    # Check if drone can carry this payload
                    for drone_payload in drone['compatible_payloads']:
                        if drone_payload['payload']['id'] == payload_id:
                            score += 1
                            compatible_payloads.append(payload_link['payload']['name'])
                            break
            
            if score > 0:
                drone_scores[drone_id] = {
                    "drone": drone,
                    "score": score,
                    "payloads": compatible_payloads
                }
        
        # Step 4: Recommend top option
        if not drone_scores:
            print("  ⚠️  No drones can carry threat counter-measures")
            print("  Recommendation: Accept risk or reduce threat exposure")
            return None
        
        best_drone_id = max(drone_scores, key=lambda x: drone_scores[x]['score'])
        recommendation = drone_scores[best_drone_id]
        
        print(f"\nStep 4: Mission Recommendation")
        print(f"  Drone: {recommendation['drone']['name']}")
        print(f"  Endurance: {recommendation['drone']['endurance_h']}h")
        print(f"  Threat Coverage: {recommendation['score']}/{len(threat_ids)} threats covered")
        print(f"  Recommended Payloads:")
        for payload in recommendation['payloads']:
            print(f"    - {payload}")
        
        return {
            "drone_id": best_drone_id,
            "drone_name": recommendation['drone']['name'],
            "recommended_payloads": recommendation['payloads'],
            "threat_coverage": recommendation['score'],
            "total_threats": len(threat_ids)
        }


# ──────────────────────────────────────────────────────────────────────────────
# 7. INTEGRATION PATTERN: WITH EXISTING APIs
# ──────────────────────────────────────────────────────────────────────────────

# === PYTHON: Combined Query Pattern ===

async def create_mission_with_inventory_check(
    mission_data: dict,
    token: str
) -> bool:
    """
    Create a mission with inventory KB validation.
    Verify drones can carry required payloads before mission dispatch.
    """
    async with httpx.AsyncClient() as client:
        # Extract mission requirements
        drone_type_id = mission_data['drone_type_id']
        required_payloads = mission_data.get('payload_ids', [])
        
        # Check drone capability
        drone_profile = await client.get(
            f"http://localhost:8000/api/inventory/kb/drones/{drone_type_id}/full",
            headers={"Authorization": f"Bearer {token}"}
        )
        
        if drone_profile.status_code != 200:
            print(f"❌ Drone {drone_type_id} not found in KB")
            return False
        
        drone = drone_profile.json()
        available_payload_ids = {p['payload']['id'] for p in drone['compatible_payloads']}
        
        # Validate all required payloads are compatible
        for payload_id in required_payloads:
            if payload_id not in available_payload_ids:
                print(f"❌ Drone cannot carry payload {payload_id}")
                return False
        
        print(f"✅ Drone {drone['name']} validated for all payloads")
        
        # Create mission (call existing mission endpoint)
        mission_result = await client.post(
            "http://localhost:8000/api/flight/missions",
            json=mission_data,
            headers={"Authorization": f"Bearer {token}"}
        )
        
        return mission_result.status_code == 201


# ──────────────────────────────────────────────────────────────────────────────
# End of Examples
# ──────────────────────────────────────────────────────────────────────────────
