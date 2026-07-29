from unittest.mock import AsyncMock

import pytest

from app.modules.drone_control.state_manager import StateManager

pytestmark = pytest.mark.asyncio


async def test_proximity_alert_requires_manual_control_below_200m():
    state = StateManager()
    state.init_drone(1, "ALPHA")
    state.init_drone(2, "BRAVO")

    listener = AsyncMock()
    state.subscribe(listener)

    await state.update(1, {"lat": 12.9716, "lon": 77.5946})
    await state.update(2, {"lat": 12.9724, "lon": 77.5946})

    left = state.get(1)
    right = state.get(2)

    assert left["proximity_alert"] is True
    assert left["manual_control_required"] is True
    assert left["proximity_intruder_drone_id"] == 2
    assert left["proximity_distance_m"] < 200

    assert right["proximity_alert"] is True
    assert right["manual_control_required"] is True
    assert right["proximity_intruder_drone_id"] == 1
    assert right["proximity_distance_m"] < 200

    assert listener.await_count >= 2


async def test_proximity_alert_clears_when_drones_separate():
    state = StateManager()
    state.init_drone(1, "ALPHA")
    state.init_drone(2, "BRAVO")

    await state.update(1, {"lat": 12.9716, "lon": 77.5946})
    await state.update(2, {"lat": 12.9724, "lon": 77.5946})
    await state.update(2, {"lat": 12.9805, "lon": 77.5946})

    left = state.get(1)
    right = state.get(2)

    assert left["proximity_alert"] is False
    assert left["manual_control_required"] is False
    assert left["proximity_distance_m"] is None
    assert left["proximity_intruder_drone_id"] is None

    assert right["proximity_alert"] is False
    assert right["manual_control_required"] is False
    assert right["proximity_distance_m"] is None
    assert right["proximity_intruder_drone_id"] is None
