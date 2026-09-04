"""
Direct unit tests for app.modules.drone_master.vessel_service.NavalVesselService,
using a fully mocked AsyncSession (same convention as test_inventory_kb_service.py).

Complements test_vessels_api.py (which mostly exercises the API/RBAC surface,
where many requests are rejected before reaching the service) by exercising
service-level branches: get_by_vessel_id, update() partial-field semantics,
update_position()'s optional heading/speed, and assign/unassign/archive 404s.
"""
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from app.models.vessel import NavalVessel
from app.models.drone import DroneInstance
from app.modules.drone_master.vessel_service import NavalVesselService
from app.schemas.vessel import NavalVesselCreate, NavalVesselUpdate, VesselPositionUpdate


@pytest.fixture
def mock_db():
    return AsyncMock()


def _vessel(id=1, vessel_id="INS-VIKRANT", is_active=True):
    return NavalVessel(
        id=id, vessel_id=vessel_id, name="INS Vikrant", vessel_type="frigate",
        is_active=is_active, sea_state=0, deck_status="clear", landing_spots=1,
        hf_link_encrypted=True,
    )


def _drone(id=1, call_sign="ALPHA-1", home_vessel_id=None):
    return DroneInstance(
        id=id, call_sign=call_sign, serial_number=f"SN-{id}",
        drone_type_id=1, status="idle", home_vessel_id=home_vessel_id,
    )


def _scalar_result(value):
    """Mimic db.execute(...).scalar_one_or_none() / .scalars().all()."""
    result = MagicMock()
    result.scalar_one_or_none.return_value = value
    result.scalars.return_value.all.return_value = value if isinstance(value, list) else ([value] if value else [])
    return result


class TestListActive:
    async def test_returns_active_vessels(self, mock_db):
        vessels = [_vessel(1), _vessel(2, "INS-SHIVALIK")]
        result = MagicMock()
        result.scalars.return_value.all.return_value = vessels
        mock_db.execute.return_value = result

        out = await NavalVesselService(mock_db).list_active()
        assert out == vessels


class TestGetById:
    async def test_found_and_active_returned(self, mock_db):
        v = _vessel()
        mock_db.get.return_value = v
        out = await NavalVesselService(mock_db).get_by_id(1)
        assert out is v

    async def test_missing_raises_404(self, mock_db):
        mock_db.get.return_value = None
        with pytest.raises(HTTPException) as exc:
            await NavalVesselService(mock_db).get_by_id(999)
        assert exc.value.status_code == 404

    async def test_inactive_raises_404(self, mock_db):
        mock_db.get.return_value = _vessel(is_active=False)
        with pytest.raises(HTTPException) as exc:
            await NavalVesselService(mock_db).get_by_id(1)
        assert exc.value.status_code == 404


class TestGetByVesselId:
    async def test_found_by_upper_vessel_id(self, mock_db):
        v = _vessel(vessel_id="INS-SHIVALIK")
        mock_db.execute.return_value = _scalar_result(v)

        out = await NavalVesselService(mock_db).get_by_vessel_id("ins-shivalik")
        assert out is v

    async def test_not_found_raises_404(self, mock_db):
        mock_db.execute.return_value = _scalar_result(None)
        with pytest.raises(HTTPException) as exc:
            await NavalVesselService(mock_db).get_by_vessel_id("NONEXISTENT")
        assert exc.value.status_code == 404


class TestCreate:
    async def test_duplicate_vessel_id_raises_409(self, mock_db):
        mock_db.execute.return_value = _scalar_result(_vessel())
        body = NavalVesselCreate(vessel_id="ins-vikrant", name="X", vessel_type="frigate")

        with pytest.raises(HTTPException) as exc:
            await NavalVesselService(mock_db).create(body)
        assert exc.value.status_code == 409

    async def test_creates_with_uppercased_vessel_id(self, mock_db):
        mock_db.execute.return_value = _scalar_result(None)
        mock_db.add = MagicMock()
        body = NavalVesselCreate(vessel_id="ins-delhi", name="INS Delhi", vessel_type="destroyer")

        async def fake_refresh(obj):
            obj.id = 42

        mock_db.refresh.side_effect = fake_refresh

        result = await NavalVesselService(mock_db).create(body)
        assert result.vessel_id == "INS-DELHI"
        mock_db.add.assert_called_once()
        mock_db.flush.assert_awaited_once()


class TestUpdate:
    async def test_partial_update_only_changes_given_fields(self, mock_db):
        v = _vessel()
        mock_db.get.return_value = v

        updated = await NavalVesselService(mock_db).update(1, NavalVesselUpdate(name="INS Vikrant Refit"))
        assert updated.name == "INS Vikrant Refit"
        assert updated.vessel_type == "frigate"  # unchanged

    async def test_update_nonexistent_raises_404(self, mock_db):
        mock_db.get.return_value = None
        with pytest.raises(HTTPException) as exc:
            await NavalVesselService(mock_db).update(999, NavalVesselUpdate(name="X"))
        assert exc.value.status_code == 404


class TestUpdatePosition:
    async def test_updates_lat_lon_and_timestamp(self, mock_db):
        v = _vessel()
        mock_db.get.return_value = v

        updated = await NavalVesselService(mock_db).update_position(
            1, VesselPositionUpdate(latitude=10.0, longitude=20.0)
        )
        assert updated.latitude == 10.0
        assert updated.longitude == 20.0
        assert updated.position_updated_at is not None

    async def test_heading_and_speed_updated_when_provided(self, mock_db):
        v = _vessel()
        mock_db.get.return_value = v

        updated = await NavalVesselService(mock_db).update_position(
            1, VesselPositionUpdate(latitude=1.0, longitude=2.0, heading_deg=90.0, speed_kts=15.0)
        )
        assert updated.heading_deg == 90.0
        assert updated.speed_kts == 15.0

    async def test_heading_and_speed_untouched_when_omitted(self, mock_db):
        v = _vessel()
        v.heading_deg = 45.0
        v.speed_kts = 10.0
        mock_db.get.return_value = v

        updated = await NavalVesselService(mock_db).update_position(
            1, VesselPositionUpdate(latitude=3.0, longitude=4.0)
        )
        assert updated.heading_deg == 45.0
        assert updated.speed_kts == 10.0

    async def test_nonexistent_vessel_raises_404(self, mock_db):
        mock_db.get.return_value = None
        with pytest.raises(HTTPException) as exc:
            await NavalVesselService(mock_db).update_position(
                999, VesselPositionUpdate(latitude=1.0, longitude=2.0)
            )
        assert exc.value.status_code == 404


class TestAssignUnassignDrone:
    async def test_assign_drone_not_found_raises_404(self, mock_db):
        mock_db.get.return_value = None
        with pytest.raises(HTTPException) as exc:
            await NavalVesselService(mock_db).assign_drone(999, 1)
        assert exc.value.status_code == 404

    async def test_assign_vessel_not_found_raises_404(self, mock_db):
        drone = _drone()

        async def fake_get(model, pk):
            if model is DroneInstance:
                return drone
            return None

        mock_db.get.side_effect = fake_get

        with pytest.raises(HTTPException) as exc:
            await NavalVesselService(mock_db).assign_drone(drone.id, 999)
        assert exc.value.status_code == 404

    async def test_assign_sets_home_vessel_id(self, mock_db):
        drone = _drone()
        vessel = _vessel()

        async def fake_get(model, pk):
            return drone if model is DroneInstance else vessel

        mock_db.get.side_effect = fake_get

        result = await NavalVesselService(mock_db).assign_drone(drone.id, vessel.id)
        assert result.home_vessel_id == vessel.id
        mock_db.flush.assert_awaited_once()

    async def test_unassign_drone_not_found_raises_404(self, mock_db):
        mock_db.get.return_value = None
        with pytest.raises(HTTPException) as exc:
            await NavalVesselService(mock_db).unassign_drone(999)
        assert exc.value.status_code == 404

    async def test_unassign_clears_home_vessel_id(self, mock_db):
        drone = _drone(home_vessel_id=5)
        mock_db.get.return_value = drone

        result = await NavalVesselService(mock_db).unassign_drone(drone.id)
        assert result.home_vessel_id is None


class TestArchive:
    async def test_archive_nonexistent_raises_404(self, mock_db):
        mock_db.get.return_value = None
        with pytest.raises(HTTPException) as exc:
            await NavalVesselService(mock_db).archive(999)
        assert exc.value.status_code == 404

    async def test_archive_blocked_when_drones_assigned(self, mock_db):
        v = _vessel()
        mock_db.get.return_value = v
        assigned_drone = _drone(call_sign="GAMMA-1", home_vessel_id=v.id)
        mock_db.execute.return_value = _scalar_result([assigned_drone])

        with pytest.raises(HTTPException) as exc:
            await NavalVesselService(mock_db).archive(v.id)
        assert exc.value.status_code == 409
        assert "GAMMA-1" in exc.value.detail

    async def test_archive_succeeds_when_no_drones_assigned(self, mock_db):
        v = _vessel()
        mock_db.get.return_value = v
        mock_db.execute.return_value = _scalar_result([])

        await NavalVesselService(mock_db).archive(v.id)
        assert v.is_active is False
        mock_db.flush.assert_awaited_once()
