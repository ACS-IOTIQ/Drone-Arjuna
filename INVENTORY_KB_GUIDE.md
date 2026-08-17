# Inventory Knowledge-Base Implementation Guide

## Overview

The Inventory Knowledge-Base (KB) system provides a sophisticated cross-reference query framework for linking drones, payloads, and threats. This enables multi-dimensional analysis for mission planning, threat assessment, and capability evaluation.

**Version:** 1.0  
**Status:** Production Ready  
**Last Updated:** 2026-08-12

---

## Architecture

### Three-Tier Entity Model

```
┌─────────────────────────────────────────────────┐
│         Inventory Knowledge-Base (KB)           │
├─────────────────────────────────────────────────┤
│                                                 │
│  ┌──────────────┐  ┌──────────────┐            │
│  │ Drone Types  │  │  Payloads    │            │
│  │  (catalog)   │  │  (catalog)   │            │
│  └──────────────┘  └──────────────┘            │
│         │                  │                    │
│         └──────┬───────────┘                    │
│              (via links)                        │
│         │                  │                    │
│  ┌──────────────────────────────────┐          │
│  │ DronePayloadLink (compatibility) │          │
│  │ ├─ is_primary (bool)             │          │
│  │ ├─ max_qty (int)                 │          │
│  │ └─ notes (text)                  │          │
│  └──────────────────────────────────┘          │
│                                                 │
│  ┌──────────────────────────────────┐          │
│  │ DroneThreatLink (vulnerability)  │          │
│  │ ├─ exposure_level (LOW/HIGH/etc) │          │
│  │ └─ notes (text)                  │          │
│  └──────────────────────────────────┘          │
│         │                                       │
│         └─────────────┬───────────────┐        │
│                       │               │        │
│                  ┌────────────┐       │        │
│                  │  Threats   │       │        │
│                  │ (catalog)  │       │        │
│                  └────────────┘       │        │
│                       ▲               │        │
│                       │               │        │
│  ┌──────────────────────────────────┐│        │
│  │PayloadThreatLink (effectiveness) ││        │
│  │ ├─ effectiveness (LOW/HIGH/etc)  ││        │
│  │ └─ notes (text)                  ││        │
│  └──────────────────────────────────┘│        │
│                                        │        │
│                                       ▼        │
└─────────────────────────────────────────────────┘
```

### Database Schema

**Linking Tables:**
- `drone_payload_links` — Which payloads can a drone carry?
- `drone_threat_links` — What threats threaten a drone?
- `payload_threat_links` — How effective is a payload against a threat?

**Relationships:** All are one-to-many with unique constraints to prevent duplicate links.

---

## Core Features

### 1. Cross-Reference Queries

#### Capability Profiles

**Query: Which drones can carry payload X?**
```python
GET /api/inventory/kb/capabilities/payload/{payload_id}
```

Response: `DroneCapabilityProfile`
- List of all drones that can carry this payload
- Constraints (max quantity, primary carrier status)
- Sorted by capability (primary vs. secondary)

**Use Case:** Mission planning — "I need to deploy sensor Y, which drones fit?"

---

**Query: What payloads can drone D carry?**
```python
GET /api/inventory/kb/capabilities/drone/{drone_id}
```

Response: Dictionary with:
- Primary payloads (intended load)
- Secondary payloads (optional augmentation)
- Max payload weight constraint

**Use Case:** Drone inventory — "What's the full capability suite of drone type X?"

---

#### Threat Analysis

**Query: How do we defeat threat T?**
```python
GET /api/inventory/kb/threats/mitigation/{threat_id}
```

Response: `ThreatMitigationProfile` — Multi-hop chain:
1. All payloads effective against this threat
2. For each payload, all drones capable of carrying it
3. Coverage analysis (redundancy, gaps)

**Use Case:** Threat mitigation — "We face SAM system X, what's our counter-capability?"

---

**Query: What threats threaten drone D?**
```python
GET /api/inventory/kb/threats/vulnerability/{drone_id}
```

Response: `DroneVulnerabilityProfile`
- Identified threats (with exposure levels)
- Available payloads to counter each threat
- Mitigation effectiveness matrix

**Use Case:** Mission risk assessment — "Deploy drone X in hostile area with SAMs — what are the risks and options?"

---

### 2. Multi-Faceted Search

**Query: Search across all inventory entities with filters**
```python
POST /api/inventory/kb/search
```

Request: `InventorySearchQuery`
```json
{
  "q": "optical sensor",
  "drone_size_class": ["medium", "large"],
  "drone_mission_type": ["ISR"],
  "drone_min_endurance_h": 6.0,
  "payload_category": ["sensor"],
  "threat_country": ["Russia", "China"],
  "limit": 20
}
```

Response: `InventorySearchResult`
- Matching drones (filtered)
- Matching payloads (filtered)
- Matching threats (filtered)
- Total counts

**Features:**
- Free-text search (name, manufacturer, model)
- Multi-dimensional filtering
- Pagination (limit, offset)
- Combines results from all three entity types

---

### 3. Enriched Entity Views

**Drones with full inventory context:**
```python
GET /api/inventory/kb/drones/{drone_id}/full
```

Returns: `DroneTypeWithInventory`
```json
{
  "id": 1,
  "name": "Heron TP",
  "size_class": "medium",
  "max_payload_weight_kg": 45,
  "compatible_payloads": [
    {
      "id": 10,
      "is_primary": true,
      "max_qty": 1,
      "payload": {...},
      "notes": "Gimbal-stabilized EO/IR"
    }
  ],
  "exposed_threats": [
    {
      "exposure_level": "MEDIUM",
      "threat": {...},
      "notes": "RCS ~0.5 m², vulnerable to mono-pulse"
    }
  ],
  "registered_instances": [
    {
      "call_sign": "HERON-01",
      "status": "online",
      "flight_hours": 234.5
    }
  ]
}
```

Similar views available for:
- `GET /api/inventory/kb/payloads/{payload_id}/full` → `PayloadTypeWithInventory`
- `GET /api/inventory/kb/threats/{threat_id}/full` → `ThreatSystemWithInventory`

---

### 4. Analytics & Health Reporting

**Inventory completeness metrics:**
```python
GET /api/inventory/kb/analytics/health
```

Response: `InventoryHealthReport`
```json
{
  "total_drone_types": 12,
  "total_drone_instances": 47,
  "total_payload_types": 18,
  "total_threat_systems": 9,
  "drone_payload_links": 24,
  "drone_threat_links": 15,
  "payload_threat_links": 11,
  "drones_with_payloads": 10,
  "drones_with_threats": 8,
  "unmapped_drones": [5, 12],
  "unmapped_threats": [3],
  "generated_at": "2026-08-12T15:30:00Z"
}
```

**Interpretation:**
- **Link Coverage:** 10/12 drones (83%) have payload mappings
- **Gaps:** Drones #5, #12 not yet categorized
- **Vulnerability Assessment:** 8/12 drones have threat exposure mappings

---

**Entity relationship statistics:**
```python
GET /api/inventory/kb/analytics/entity/{entity_type}/{entity_id}
```

Returns: `EntityRelationshipStats`
- Connection counts (outgoing/incoming links)
- Breakdown by entity type
- Transitive relationship counts (V2 feature)

---

## API Endpoints Summary

### Knowledge-Base Queries (Read-Only)

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/kb/capabilities/payload/{id}` | GET | Which drones can carry payload X? |
| `/kb/capabilities/drone/{id}` | GET | What payloads can drone D carry? |
| `/kb/threats/mitigation/{id}` | GET | How to defeat threat T? |
| `/kb/threats/vulnerability/{id}` | GET | What threatens drone D? |
| `/kb/search` | POST | Multi-faceted inventory search |
| `/kb/drones/{id}/full` | GET | Drone with full relationships |
| `/kb/payloads/{id}/full` | GET | Payload with full relationships |
| `/kb/threats/{id}/full` | GET | Threat with full relationships |
| `/kb/analytics/health` | GET | Inventory health metrics |
| `/kb/analytics/entity/{type}/{id}` | GET | Entity relationship statistics |

### Link Management (CRUD)

Existing endpoints for creating/updating links:
- `POST /links/drone-payload` — Create compatibility link
- `PUT /links/drone-payload/{id}` — Update constraints
- `DELETE /links/drone-payload/{id}` — Remove link
- Similar for `drone-threat` and `payload-threat`

---

## Usage Examples

### Example 1: Mission Planning

**Scenario:** Plan a long-endurance ISR mission to detect SAM sites in contested airspace.

**Steps:**
```python
# 1. What threats are we likely to face?
GET /api/inventory/kb/threats/mitigation/3  # SAM system ID
# Response: 15 payloads can counter this threat
#          12 drones can carry effective payloads

# 2. Which drones have 8+ hour endurance?
POST /api/inventory/kb/search
{
  "drone_min_endurance_h": 8.0,
  "drone_mission_type": ["ISR"]
}
# Response: 3 compatible drones found

# 3. Full capability review
GET /api/inventory/kb/drones/1/full
# Response: Heron TP can carry EO/IR, has 10h endurance,
#          exposed to SAM but can carry EW jammer

# 4. Recommendation
# → Deploy Heron TP with jammer (primary) + EO/IR (secondary)
```

---

### Example 2: Threat Assessment

**Scenario:** Enemy acquired Buk SAM system, assess our drone fleet exposure.

**Steps:**
```python
# 1. What drones are vulnerable?
GET /api/inventory/kb/threats/vulnerability/5  # Buk system ID
# Response: 8 of our drones exposed at MEDIUM/HIGH level

# 2. What's our counter-capability?
GET /api/inventory/kb/threats/mitigation/5
# Response: 3 payloads can counter Buk
#          2 drones can carry them

# 3. Coverage analysis
GET /api/inventory/kb/analytics/health
# Response: 2/12 drones have Buk counter-measures
#          Gap analysis: Need more EW payload capacity

# 4. Action items
# → Prioritize EW payload integration with large drones
# → Allocate drone units with counter-measures to contested zones
```

---

### Example 3: Payload Integration

**Scenario:** New drone type acquired, need to assess payload options.

**Steps:**
```python
# 1. Payload weight budget
# New drone: max 35 kg payload

# 2. What payloads fit?
POST /api/inventory/kb/search
{
  "payload_max_weight_kg": 35,
  "payload_category": ["sensor", "comms"]
}
# Response: 12 compatible payloads

# 3. Threat environment?
# Check which payloads can address primary threats:
GET /api/inventory/kb/threats/mitigation/1
GET /api/inventory/kb/threats/mitigation/2

# 4. Recommendation matrix
# Payload A: 28 kg, EO/IR, good against UAVs
# Payload B: 32 kg, SIGINT, good against radars
# → Acquire both, create separate loadout profiles
```

---

## Data Model Details

### DronePayloadLink

```python
{
  "drone_type_id": int,           # FK to drone_types
  "payload_type_id": int,         # FK to payload_types
  "is_primary": bool,             # Primary loadout vs. optional
  "max_qty": int,                 # Max of this payload per drone
  "notes": str,                   # Integration notes
  "created_at": datetime
}
```

**Constraint:** Unique(drone_type_id, payload_type_id)
**Use:** Capability matrix for mission planning

---

### DroneThreatLink

```python
{
  "drone_type_id": int,           # FK to drone_types
  "threat_system_id": int,        # FK to threat_systems
  "exposure_level": str,          # "LOW" | "MEDIUM" | "HIGH" | "CRITICAL"
  "notes": str,                   # Vulnerability details
  "created_at": datetime
}
```

**Constraint:** Unique(drone_type_id, threat_system_id)
**Use:** Vulnerability assessment, risk analysis

---

### PayloadThreatLink

```python
{
  "payload_type_id": int,         # FK to payload_types
  "threat_system_id": int,        # FK to threat_systems
  "effectiveness": str,           # "LOW" | "MEDIUM" | "HIGH" | "CRITICAL"
  "notes": str,                   # Mitigation strategy
  "created_at": datetime
}
```

**Constraint:** Unique(payload_type_id, threat_system_id)
**Use:** Countermeasure selection, threat mitigation

---

## Performance Considerations

### Query Optimization

- All link queries use ForeignKey indexes
- Multi-hop queries (threat → payload → drone) are O(n) with typical n≤20
- Search queries are single-pass ILIKE on indexed columns
- Hydration of entities with nested relationships is async/concurrent

### Scalability

**Current (V1):** Supports ~100 drone types, ~50 payloads, ~30 threats
- Full hydration: ~50ms for complex entities
- Cross-reference queries: ~100-200ms worst case

**V2 Optimizations:**
- Elasticsearch for full-text search
- Query result caching
- Denormalized materialized views for common queries
- GraphQL for selective field retrieval

---

## Authorization

### Role-Based Access

| Role | Capability |
|------|-----------|
| VIEWER | Read all KB queries, browse inventory |
| INTELLIGENCE_ANALYST | All above + update threat notes |
| MISSION_COMMANDER | All above + full threat access |
| ADMIN | All above + full write access (create/update/delete) |

All KB read endpoints require `VIEWER+` role.
Link modification requires `ADMIN` role.

---

## Future Enhancements (V2)

1. **Elasticsearch Integration**
   - Full-text search across all entity fields
   - Fuzzy matching for typo tolerance
   - Faceted navigation

2. **Rich Content**
   - HTML5 formatted entity pages
   - Comparative analysis visualizations
   - Threat modeling graphs

3. **CMS Workflow**
   - Draft → Review → Publish lifecycle
   - User contributions to KB
   - Change tracking/audit log

4. **Advanced Analytics**
   - AI-powered recommendations
   - Gap analysis algorithms
   - Redundancy scoring

5. **Data Import/Export**
   - CSV/JSON bulk import
   - Excel report generation
   - API data federation

---

## Testing

### Unit Tests

Location: `backend/app/modules/drone_inventory/tests/`

Test categories:
- Query correctness (cross-reference results)
- Link integrity (circular references, duplicates)
- Search filtering (facet combinations)
- Authorization enforcement

### Integration Tests

- Multi-hop query chains (threat → payload → drone)
- Concurrent hydration of large result sets
- Link deletion cascades
- Search with mixed entity types

### Load Testing

- 1000 entities across all types
- Concurrent multi-faceted searches
- Full KB health report generation

---

## Troubleshooting

### Common Issues

**Q: KB search returns no results**
- A: Check entity filters (size_class, category)—may be too restrictive
- A: Verify entities are marked `is_active = true`

**Q: Cross-reference query is slow**
- A: Check for circular link chains (rare but possible)
- A: Consider materializing frequent query results (V2 feature)

**Q: Missing threat exposure mappings**
- A: Use health report to identify unmapped drones
- A: Admin role needed to create DroneThreatLink entries

---

## Code Structure

### Files Created/Modified

```
backend/app/
├── schemas/
│   └── inventory_kb.py              ✨ NEW: Comprehensive KB schemas
├── modules/drone_inventory/
│   ├── kb_service.py                ✨ NEW: Cross-reference service
│   └── router.py                    📝 UPDATED: KB endpoints
└── models/
    └── inventory_link.py             ✅ EXISTING: Link models
```

### Service Layer

`InventoryKBService` in `kb_service.py`:
- `get_payload_capability_profile()` — Drones for payload
- `get_drone_capability_profile()` — Payloads for drone
- `get_threat_mitigation_profile()` — Counter-measures for threat
- `get_drone_vulnerability_profile()` — Threats for drone
- `search_inventory()` — Multi-faceted search
- `get_inventory_health_report()` — Completeness metrics
- `get_entity_relationship_stats()` — Connection analysis
- Helper methods for entity hydration

---

## Contact & Support

For issues, enhancements, or questions:
- Create an issue in DroneArjuna GitHub
- Tag: `inventory-kb`, `data-model`, `queries`

---

**End of Document**
