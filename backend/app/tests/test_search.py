"""
Unit tests for app.core.search — Elasticsearch client + indexing helpers.

The real AsyncElasticsearch client is fully mocked; no live ES connection
is made. Every helper is designed to swallow ES errors and never raise, so
tests also verify that failure modes degrade gracefully.
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core import search


@pytest.fixture(autouse=True)
def _reset_client_singleton():
    original = search._client
    search._client = None
    yield
    search._client = original


class TestGetClient:
    def test_lazily_constructs_and_caches_client(self):
        with patch.object(search, "AsyncElasticsearch") as mock_cls:
            mock_cls.return_value = MagicMock()
            first = search.get_client()
            second = search.get_client()
        assert first is second
        mock_cls.assert_called_once()


class TestCloseClient:
    async def test_closes_and_clears_singleton(self):
        fake_client = AsyncMock()
        search._client = fake_client

        await search.close_client()

        fake_client.close.assert_awaited_once()
        assert search._client is None

    async def test_no_client_is_a_noop(self):
        search._client = None
        await search.close_client()  # must not raise


class TestEnsureIndices:
    async def test_creates_missing_indices(self):
        fake_client = AsyncMock()
        fake_client.indices.exists = AsyncMock(return_value=False)
        fake_client.indices.create = AsyncMock()
        search._client = fake_client

        await search.ensure_indices()

        assert fake_client.indices.create.await_count == len(search._MAPPINGS)

    async def test_skips_existing_indices(self):
        fake_client = AsyncMock()
        fake_client.indices.exists = AsyncMock(return_value=True)
        fake_client.indices.create = AsyncMock()
        search._client = fake_client

        await search.ensure_indices()

        fake_client.indices.create.assert_not_awaited()

    async def test_exception_for_one_index_does_not_abort_others(self):
        fake_client = AsyncMock()
        fake_client.indices.exists = AsyncMock(side_effect=RuntimeError("es down"))
        search._client = fake_client

        await search.ensure_indices()  # must not raise despite every index failing


class TestIndexDroneType:
    async def test_indexes_with_expected_document_shape(self):
        fake_client = AsyncMock()
        search._client = fake_client

        await search.index_drone_type({
            "id": 1, "name": "Hawk", "manufacturer": "ACS",
            "model": "H1", "mission_type": "ISR", "size_class": "small",
            "autopilot_type": "ArduPilot", "notes": "test",
        })

        fake_client.index.assert_awaited_once()
        _, kwargs = fake_client.index.call_args
        assert kwargs["index"] == search.INDEX_DRONE
        assert kwargs["id"] == "1"
        assert kwargs["document"]["autopilot"] == "ArduPilot"

    async def test_missing_optional_fields_default_to_empty_string(self):
        fake_client = AsyncMock()
        search._client = fake_client

        await search.index_drone_type({"id": 2, "name": "Bare"})

        _, kwargs = fake_client.index.call_args
        assert kwargs["document"]["notes"] == ""
        assert kwargs["document"]["manufacturer"] == ""

    async def test_exception_is_logged_and_swallowed(self):
        fake_client = AsyncMock()
        fake_client.index.side_effect = RuntimeError("es down")
        search._client = fake_client

        await search.index_drone_type({"id": 1, "name": "Hawk"})  # must not raise


class TestIndexPayloadType:
    async def test_indexes_with_expected_document_shape(self):
        fake_client = AsyncMock()
        search._client = fake_client

        await search.index_payload_type({
            "id": 5, "name": "EO/IR Gimbal", "manufacturer": "ACS",
            "model": "G1", "category": "sensor", "sensor_type": "EO/IR",
            "notes": "n",
        })

        _, kwargs = fake_client.index.call_args
        assert kwargs["index"] == search.INDEX_PAYLOAD
        assert kwargs["id"] == "5"
        assert kwargs["document"]["sensor_type"] == "EO/IR"

    async def test_none_sensor_type_becomes_empty_string(self):
        fake_client = AsyncMock()
        search._client = fake_client

        await search.index_payload_type({"id": 6, "name": "X", "sensor_type": None})

        _, kwargs = fake_client.index.call_args
        assert kwargs["document"]["sensor_type"] == ""

    async def test_exception_is_logged_and_swallowed(self):
        fake_client = AsyncMock()
        fake_client.index.side_effect = RuntimeError("es down")
        search._client = fake_client

        await search.index_payload_type({"id": 5, "name": "X"})  # must not raise


class TestIndexThreatSystem:
    async def test_indexes_with_expected_document_shape(self):
        fake_client = AsyncMock()
        search._client = fake_client

        await search.index_threat_system({
            "id": 9, "name": "SAM-1", "manufacturer": "Foo",
            "country": "IN", "category": "SAM", "notes": "n",
        })

        _, kwargs = fake_client.index.call_args
        assert kwargs["index"] == search.INDEX_THREAT
        assert kwargs["id"] == "9"
        assert kwargs["document"]["country"] == "IN"

    async def test_exception_is_logged_and_swallowed(self):
        fake_client = AsyncMock()
        fake_client.index.side_effect = RuntimeError("es down")
        search._client = fake_client

        await search.index_threat_system({"id": 9, "name": "X"})  # must not raise


class TestDeleteDocument:
    async def test_deletes_document_by_id(self):
        fake_client = AsyncMock()
        search._client = fake_client

        await search.delete_document(search.INDEX_DRONE, 7)

        fake_client.delete.assert_awaited_once_with(index=search.INDEX_DRONE, id="7")

    async def test_not_found_is_silently_ignored(self):
        fake_client = AsyncMock()
        fake_client.delete.side_effect = search.NotFoundError("missing", meta=MagicMock(), body=None)
        search._client = fake_client

        await search.delete_document(search.INDEX_DRONE, 7)  # must not raise

    async def test_other_exception_is_logged_and_swallowed(self):
        fake_client = AsyncMock()
        fake_client.delete.side_effect = RuntimeError("es down")
        search._client = fake_client

        await search.delete_document(search.INDEX_DRONE, 7)  # must not raise


class TestSearchInventory:
    async def test_empty_query_returns_empty_list_without_calling_es(self):
        fake_client = AsyncMock()
        search._client = fake_client

        results = await search.search_inventory("   ")

        assert results == []
        fake_client.search.assert_not_called()

    async def test_maps_hits_to_typed_results(self):
        fake_client = AsyncMock()
        fake_client.search.return_value = {
            "hits": {
                "hits": [
                    {"_index": search.INDEX_DRONE, "_id": "1", "_score": 3.14159,
                     "_source": {"name": "Hawk"}},
                    {"_index": search.INDEX_PAYLOAD, "_id": "2", "_score": 2.0,
                     "_source": {"name": "Gimbal"}},
                    {"_index": search.INDEX_THREAT, "_id": "3", "_score": 1.0,
                     "_source": {"name": "SAM"}},
                ]
            }
        }
        search._client = fake_client

        results = await search.search_inventory("hawk")

        assert results[0] == {"type": "drone", "id": 1, "_score": 3.142, "name": "Hawk"}
        assert results[1]["type"] == "payload"
        assert results[2]["type"] == "threat"

    async def test_uses_multi_index_and_limit(self):
        fake_client = AsyncMock()
        fake_client.search.return_value = {"hits": {"hits": []}}
        search._client = fake_client

        await search.search_inventory("query", limit=5)

        _, kwargs = fake_client.search.call_args
        assert kwargs["index"] == f"{search.INDEX_DRONE},{search.INDEX_PAYLOAD},{search.INDEX_THREAT}"
        assert kwargs["body"]["size"] == 5

    async def test_exception_returns_empty_list(self):
        fake_client = AsyncMock()
        fake_client.search.side_effect = RuntimeError("es down")
        search._client = fake_client

        results = await search.search_inventory("hawk")
        assert results == []


class TestBulkIndexAll:
    async def test_indexes_all_active_rows_across_three_models(self):
        drone_row = MagicMock(id=1, name="Hawk", manufacturer="ACS", model="H1",
                               mission_type="ISR", size_class="small",
                               autopilot_type="ArduPilot", notes=None)
        payload_row = MagicMock(id=2, name="Gimbal", manufacturer="ACS", model="G1",
                                 category="sensor", sensor_type="EO/IR", notes=None)
        threat_row = MagicMock(id=3, name="SAM", manufacturer="Foo",
                                country="IN", category="SAM", notes=None)

        def fake_scalars_all(rows):
            result = MagicMock()
            result.scalars.return_value.all.return_value = rows
            return result

        fake_db = AsyncMock()
        fake_db.execute.side_effect = [
            fake_scalars_all([drone_row]),
            fake_scalars_all([payload_row]),
            fake_scalars_all([threat_row]),
        ]

        with patch.object(search, "ensure_indices", AsyncMock()), \
             patch.object(search, "index_drone_type", AsyncMock()) as mock_idx_drone, \
             patch.object(search, "index_payload_type", AsyncMock()) as mock_idx_payload, \
             patch.object(search, "index_threat_system", AsyncMock()) as mock_idx_threat:
            await search.bulk_index_all(fake_db)

        mock_idx_drone.assert_awaited_once()
        mock_idx_payload.assert_awaited_once()
        mock_idx_threat.assert_awaited_once()

    async def test_exception_is_logged_and_does_not_raise(self):
        fake_db = AsyncMock()
        fake_db.execute.side_effect = RuntimeError("db down")

        with patch.object(search, "ensure_indices", AsyncMock()):
            await search.bulk_index_all(fake_db)  # must not raise
