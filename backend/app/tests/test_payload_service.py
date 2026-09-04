"""
Direct unit tests for app.modules.drone_master.payload_service.PayloadTypeService,
using a fully mocked AsyncSession (same convention as test_vessel_service.py).
"""
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from app.models.payload import PayloadType
from app.modules.drone_master.payload_service import PayloadTypeService
from app.schemas.payload import PayloadTypeCreate, PayloadTypeUpdate


@pytest.fixture
def mock_db():
    return AsyncMock()


def _payload(id=1, name="EO/IR Gimbal"):
    return PayloadType(
        id=id, name=name, manufacturer="ACS", model="G1",
        category="sensor", weight_kg=1.0, voltage_v=12.0, max_current_a=2.0,
        has_gimbal=True, is_active=True,
    )


def _scalar_result(value):
    result = MagicMock()
    result.scalar_one_or_none.return_value = value
    return result


class TestListAll:
    async def test_returns_all_ordered_by_name(self, mock_db):
        payloads = [_payload(1, "A"), _payload(2, "B")]
        result = MagicMock()
        result.scalars.return_value.all.return_value = payloads
        mock_db.execute.return_value = result

        out = await PayloadTypeService(mock_db).list_all()
        assert out == payloads


class TestGetById:
    async def test_found_returned(self, mock_db):
        pt = _payload()
        mock_db.get.return_value = pt
        out = await PayloadTypeService(mock_db).get_by_id(1)
        assert out is pt

    async def test_missing_raises_404(self, mock_db):
        mock_db.get.return_value = None
        with pytest.raises(HTTPException) as exc:
            await PayloadTypeService(mock_db).get_by_id(999)
        assert exc.value.status_code == 404


class TestCreate:
    async def test_duplicate_name_raises_409(self, mock_db):
        mock_db.execute.return_value = _scalar_result(_payload())
        body = PayloadTypeCreate(name="EO/IR Gimbal", manufacturer="X", model="Y")

        with pytest.raises(HTTPException) as exc:
            await PayloadTypeService(mock_db).create(body)
        assert exc.value.status_code == 409

    async def test_creates_new_payload_type(self, mock_db):
        mock_db.execute.return_value = _scalar_result(None)
        mock_db.add = MagicMock()

        async def fake_refresh(obj):
            obj.id = 7

        mock_db.refresh.side_effect = fake_refresh
        body = PayloadTypeCreate(name="New Sensor", manufacturer="ACS", model="S1")

        result = await PayloadTypeService(mock_db).create(body)
        assert result.name == "New Sensor"
        mock_db.add.assert_called_once()
        mock_db.flush.assert_awaited_once()


class TestUpdate:
    async def test_partial_update_only_changes_given_fields(self, mock_db):
        pt = _payload()
        mock_db.get.return_value = pt

        updated = await PayloadTypeService(mock_db).update(1, PayloadTypeUpdate(name="Renamed"))
        assert updated.name == "Renamed"
        assert updated.manufacturer == "ACS"  # unchanged

    async def test_update_nonexistent_raises_404(self, mock_db):
        mock_db.get.return_value = None
        with pytest.raises(HTTPException) as exc:
            await PayloadTypeService(mock_db).update(999, PayloadTypeUpdate(name="X"))
        assert exc.value.status_code == 404


class TestDelete:
    async def test_deletes_existing_payload_type(self, mock_db):
        pt = _payload()
        mock_db.get.return_value = pt
        mock_db.delete = AsyncMock()

        await PayloadTypeService(mock_db).delete(1)
        mock_db.delete.assert_awaited_once_with(pt)

    async def test_delete_nonexistent_raises_404(self, mock_db):
        mock_db.get.return_value = None
        with pytest.raises(HTTPException) as exc:
            await PayloadTypeService(mock_db).delete(999)
        assert exc.value.status_code == 404
