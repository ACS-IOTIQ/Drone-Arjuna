"""
Elasticsearch client + indexing helpers  —  P4-06

Indices:
  da_drone_types     ←  DroneType rows
  da_payload_types   ←  PayloadType rows
  da_threat_systems  ←  ThreatSystem rows

All index/delete calls are fire-and-forget: they log errors but never
raise, so an ES outage never breaks the primary HTTP endpoints.
"""
import asyncio
import structlog
from elasticsearch import AsyncElasticsearch, NotFoundError

from app.config import get_settings

log = structlog.get_logger()

INDEX_DRONE   = "da_drone_types"
INDEX_PAYLOAD = "da_payload_types"
INDEX_THREAT  = "da_threat_systems"

_client: AsyncElasticsearch | None = None


def get_client() -> AsyncElasticsearch:
    global _client
    if _client is None:
        cfg = get_settings()
        _client = AsyncElasticsearch(cfg.elasticsearch_url, request_timeout=5)
    return _client


async def close_client() -> None:
    global _client
    if _client:
        await _client.close()
        _client = None


# ── Index creation ────────────────────────────────────────────────

_MAPPINGS: dict[str, dict] = {
    INDEX_DRONE: {
        "mappings": {
            "properties": {
                "name":         {"type": "text"},
                "manufacturer": {"type": "text"},
                "model":        {"type": "text"},
                "mission_type": {"type": "text"},
                "size_class":   {"type": "keyword"},
                "autopilot":    {"type": "keyword"},
                "notes":        {"type": "text"},
            }
        }
    },
    INDEX_PAYLOAD: {
        "mappings": {
            "properties": {
                "name":         {"type": "text"},
                "manufacturer": {"type": "text"},
                "model":        {"type": "text"},
                "category":     {"type": "text"},
                "sensor_type":  {"type": "text"},
                "notes":        {"type": "text"},
            }
        }
    },
    INDEX_THREAT: {
        "mappings": {
            "properties": {
                "name":         {"type": "text"},
                "manufacturer": {"type": "text"},
                "country":      {"type": "text"},
                "category":     {"type": "keyword"},
                "notes":        {"type": "text"},
            }
        }
    },
}


async def ensure_indices() -> None:
    """Create indices if they don't exist yet. Called at startup."""
    es = get_client()
    for index, body in _MAPPINGS.items():
        try:
            exists = await es.indices.exists(index=index)
            if not exists:
                await es.indices.create(index=index, body=body)
                log.info("es_index_created", index=index)
        except Exception as exc:
            log.error("es_ensure_index_failed", index=index, error=str(exc))


# ── Single-document helpers ───────────────────────────────────────

async def index_drone_type(drone: dict) -> None:
    try:
        await get_client().index(
            index=INDEX_DRONE,
            id=str(drone["id"]),
            document={
                "name":         drone.get("name", ""),
                "manufacturer": drone.get("manufacturer", ""),
                "model":        drone.get("model", ""),
                "mission_type": drone.get("mission_type", ""),
                "size_class":   drone.get("size_class", ""),
                "autopilot":    drone.get("autopilot_type", drone.get("autopilot", "")),
                "notes":        drone.get("notes") or "",
            },
        )
    except Exception as exc:
        log.error("es_index_drone_failed", id=drone.get("id"), error=str(exc))


async def index_payload_type(payload: dict) -> None:
    try:
        await get_client().index(
            index=INDEX_PAYLOAD,
            id=str(payload["id"]),
            document={
                "name":         payload.get("name", ""),
                "manufacturer": payload.get("manufacturer", ""),
                "model":        payload.get("model", ""),
                "category":     payload.get("category", ""),
                "sensor_type":  payload.get("sensor_type") or "",
                "notes":        payload.get("notes") or "",
            },
        )
    except Exception as exc:
        log.error("es_index_payload_failed", id=payload.get("id"), error=str(exc))


async def index_threat_system(threat: dict) -> None:
    try:
        await get_client().index(
            index=INDEX_THREAT,
            id=str(threat["id"]),
            document={
                "name":         threat.get("name", ""),
                "manufacturer": threat.get("manufacturer", ""),
                "country":      threat.get("country", ""),
                "category":     threat.get("category", ""),
                "notes":        threat.get("notes") or "",
            },
        )
    except Exception as exc:
        log.error("es_index_threat_failed", id=threat.get("id"), error=str(exc))


async def delete_document(index: str, doc_id: int) -> None:
    try:
        await get_client().delete(index=index, id=str(doc_id))
    except NotFoundError:
        pass
    except Exception as exc:
        log.error("es_delete_failed", index=index, id=doc_id, error=str(exc))


# ── Multi-index search ────────────────────────────────────────────

async def search_inventory(query: str, limit: int = 20) -> list[dict]:
    """
    multi_match with fuzziness AUTO across name^3, manufacturer^2,
    model, mission_type, category, country, notes.
    Returns list of result dicts with type + _score.
    Falls back to empty list on any ES error.
    """
    if not query.strip():
        return []

    es = get_client()
    body = {
        "size": limit,
        "query": {
            "multi_match": {
                "query":     query,
                "fields":    [
                    "name^3",
                    "manufacturer^2",
                    "model",
                    "mission_type",
                    "category",
                    "sensor_type",
                    "country",
                    "notes",
                ],
                "fuzziness": "AUTO",
                "type":      "best_fields",
            }
        },
    }

    try:
        response = await es.search(
            index=f"{INDEX_DRONE},{INDEX_PAYLOAD},{INDEX_THREAT}",
            body=body,
        )
        results = []
        for hit in response["hits"]["hits"]:
            idx = hit["_index"]
            doc_type = (
                "drone"   if idx == INDEX_DRONE   else
                "payload" if idx == INDEX_PAYLOAD else
                "threat"
            )
            results.append({
                "type":   doc_type,
                "id":     int(hit["_id"]),
                "_score": round(hit["_score"], 3),
                **hit["_source"],
            })
        return results
    except Exception as exc:
        log.error("es_search_failed", query=query, error=str(exc))
        return []


# ── Bulk startup index ────────────────────────────────────────────

async def bulk_index_all(db) -> None:
    """
    Index all existing DroneType, PayloadType, ThreatSystem rows.
    Called once at backend startup inside the lifespan handler.
    Errors are caught and logged — ES unavailability never aborts startup.
    """
    from sqlalchemy import select
    from app.models.drone import DroneType
    from app.models.payload import PayloadType
    from app.models.threat import ThreatSystem

    try:
        await ensure_indices()

        result = await db.execute(select(DroneType).where(DroneType.is_active == True))
        drones = result.scalars().all()
        for dt in drones:
            await index_drone_type({
                "id": dt.id, "name": dt.name, "manufacturer": dt.manufacturer,
                "model": dt.model, "mission_type": dt.mission_type,
                "size_class": dt.size_class, "autopilot_type": dt.autopilot_type,
                "notes": dt.notes,
            })

        result = await db.execute(select(PayloadType).where(PayloadType.is_active == True))
        payloads = result.scalars().all()
        for pt in payloads:
            await index_payload_type({
                "id": pt.id, "name": pt.name, "manufacturer": pt.manufacturer,
                "model": pt.model, "category": pt.category,
                "sensor_type": pt.sensor_type, "notes": pt.notes,
            })

        result = await db.execute(select(ThreatSystem))
        threats = result.scalars().all()
        for ts in threats:
            await index_threat_system({
                "id": ts.id, "name": ts.name, "manufacturer": ts.manufacturer,
                "country": ts.country, "category": ts.category, "notes": ts.notes,
            })

        log.info("es_bulk_index_complete",
                 drones=len(drones), payloads=len(payloads), threats=len(threats))
    except Exception as exc:
        log.error("es_bulk_index_failed", error=str(exc))
