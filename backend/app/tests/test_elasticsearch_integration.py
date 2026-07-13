"""
P4-06 — Elasticsearch integration test (live ES required).

Runs against the real Elasticsearch container — no mocks.
Execute inside the backend container:

    docker compose exec backend pytest app/tests/test_elasticsearch_integration.py -v

Test sequence (all in one test to guarantee ordering):
  1. Index a test drone type directly via the ES client
  2. Refresh the index so the doc is visible immediately
  3. Search by exact name  → assert it appears
  4. Search with a deliberate typo → assert it still appears (fuzziness AUTO)
  5. Delete the document
  6. Confirm it no longer appears in search results
"""
import asyncio
import pytest
import pytest_asyncio
from elasticsearch import AsyncElasticsearch, NotFoundError

pytestmark = pytest.mark.asyncio

# ─────────────────────────────────────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────────────────────────────────────

ES_URL        = "http://elasticsearch:9200"
INDEX_DRONE   = "da_drone_types"
TEST_DOC_ID   = 99999          # sentinel ID unlikely to collide with real data
TEST_DOC_NAME = "ArjunaTestDrone-X1"
TEST_DOCUMENT = {
    "name":         TEST_DOC_NAME,
    "manufacturer": "ACS Technologies",
    "model":        "X1-Alpha",
    "mission_type": "ISR",
    "size_class":   "medium",
    "autopilot":    "ArduPilot",
    "notes":        "Integration test document — safe to delete",
}


# ─────────────────────────────────────────────────────────────────────────────
# Fixture — raw ES client with generous timeout; cleans up on teardown
# ─────────────────────────────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def es():
    """
    Yields a live AsyncElasticsearch client with a 30-second request timeout.
    Creates the da_drone_types index if missing.
    Deletes the test document on teardown (regardless of test outcome).
    """
    client = AsyncElasticsearch(ES_URL, request_timeout=30)

    # Ensure index exists
    if not await client.indices.exists(index=INDEX_DRONE):
        await client.indices.create(
            index=INDEX_DRONE,
            body={
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
        )

    yield client

    # Teardown — delete test doc if it still exists so reruns start clean
    try:
        await client.delete(index=INDEX_DRONE, id=str(TEST_DOC_ID))
        await client.indices.refresh(index=INDEX_DRONE)
    except NotFoundError:
        pass

    await client.close()


# ─────────────────────────────────────────────────────────────────────────────
# Helper
# ─────────────────────────────────────────────────────────────────────────────

async def _search(client: AsyncElasticsearch, query: str) -> list[dict]:
    """Run a multi_match with fuzziness AUTO and return hits for TEST_DOC_ID."""
    response = await client.search(
        index=INDEX_DRONE,
        body={
            "size": 50,
            "query": {
                "multi_match": {
                    "query":     query,
                    "fields":    ["name^3", "manufacturer^2", "model", "mission_type", "notes"],
                    "fuzziness": "AUTO",
                    "type":      "best_fields",
                }
            },
        },
    )
    return [
        hit for hit in response["hits"]["hits"]
        if hit["_id"] == str(TEST_DOC_ID)
    ]


# ─────────────────────────────────────────────────────────────────────────────
# Test
# ─────────────────────────────────────────────────────────────────────────────

async def test_elasticsearch_index_search_delete(es: AsyncElasticsearch):
    """
    Full lifecycle:
      index → exact search → typo search → delete → confirm gone.
    """
    # ── 1. Index ─────────────────────────────────────────────────────────────
    await es.index(
        index=INDEX_DRONE,
        id=str(TEST_DOC_ID),
        document=TEST_DOCUMENT,
    )
    # Force refresh so the doc is immediately searchable
    await es.indices.refresh(index=INDEX_DRONE)

    # ── 2. Search by exact name ──────────────────────────────────────────────
    exact_hits = await _search(es, TEST_DOC_NAME)
    assert len(exact_hits) >= 1, (
        f"Exact name search for '{TEST_DOC_NAME}' returned no results"
    )
    source = exact_hits[0]["_source"]
    assert source["name"] == TEST_DOC_NAME
    assert source["manufacturer"] == "ACS Technologies"

    # ── 3. Search with a deliberate typo ─────────────────────────────────────
    # Drop the 'o' from 'Drone' → 'Drne'
    typo_query = "ArjunaTestDrne-X1"
    typo_hits = await _search(es, typo_query)
    assert len(typo_hits) >= 1, (
        f"Fuzzy search for typo '{typo_query}' returned no results. "
        "Verify fuzziness=AUTO is set in the query."
    )

    # ── 4. Delete the document ───────────────────────────────────────────────
    await es.delete(index=INDEX_DRONE, id=str(TEST_DOC_ID))
    await es.indices.refresh(index=INDEX_DRONE)

    # ── 5. Confirm it no longer appears ─────────────────────────────────────
    post_delete_hits = await _search(es, TEST_DOC_NAME)
    assert len(post_delete_hits) == 0, (
        f"Expected 0 hits after deletion, found: {post_delete_hits}"
    )
