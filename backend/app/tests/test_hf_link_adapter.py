"""
Unit tests for app.modules.drone_control.hf_link_adapter.

Covers:
  - should_forward: priority lookup, rate limiting, LOW-tier blocking
  - link state machine: CONNECTED -> DEGRADED -> LOST transitions,
    recovery via on_message_received
  - update_link_quality / get_status
  - module-level adapter registry (get_or_create/remove/get_all_statuses)
  - run_tick_loop background coroutine ticks all registered adapters
"""
import asyncio
from unittest.mock import patch

import pytest

from app.modules.drone_control import hf_link_adapter as hla
from app.modules.drone_control.hf_link_adapter import (
    HFLinkAdapter,
    HFLinkState,
    MsgPriority,
    HF_DEGRADED_THRESHOLD_S,
    HF_LOST_THRESHOLD_S,
)


@pytest.fixture(autouse=True)
def _reset_registry():
    hla._hf_adapters.clear()
    yield
    hla._hf_adapters.clear()


# ── should_forward / rate limiting ───────────────────────────────────────────

def test_should_forward_critical_never_rate_limited():
    adapter = HFLinkAdapter(drone_id=1)
    assert adapter.should_forward("COMMAND_ACK") is True
    assert adapter.should_forward("COMMAND_ACK") is True
    assert adapter.should_forward("COMMAND_ACK") is True


def test_should_forward_low_priority_always_blocked():
    adapter = HFLinkAdapter(drone_id=1)
    assert adapter.should_forward("STATUSTEXT") is False
    assert adapter.should_forward("RAW_IMU") is False


def test_should_forward_unknown_message_type_defaults_to_low_and_is_blocked():
    adapter = HFLinkAdapter(drone_id=1)
    assert adapter.should_forward("SOME_UNKNOWN_MSG") is False


def test_should_forward_high_priority_rate_limited():
    adapter = HFLinkAdapter(drone_id=1)
    t = [1000.0]
    with patch("app.modules.drone_control.hf_link_adapter.time.monotonic", side_effect=lambda: t[0]):
        assert adapter.should_forward("GLOBAL_POSITION_INT") is True
        # Immediately again -> rate-limited (min interval 0.5s for HIGH)
        assert adapter.should_forward("GLOBAL_POSITION_INT") is False
        # Advance past the 0.5s interval
        t[0] += 0.6
        assert adapter.should_forward("GLOBAL_POSITION_INT") is True


def test_should_forward_medium_priority_rate_limited_independently_of_high():
    adapter = HFLinkAdapter(drone_id=1)
    t = [0.0]
    with patch("app.modules.drone_control.hf_link_adapter.time.monotonic", side_effect=lambda: t[0]):
        assert adapter.should_forward("VFR_HUD") is True
        assert adapter.should_forward("VFR_HUD") is False
        # HIGH tier is independent of MEDIUM tier's last-sent tracking
        assert adapter.should_forward("GLOBAL_POSITION_INT") is True
        t[0] += 2.1
        assert adapter.should_forward("VFR_HUD") is True


# ── link state machine ───────────────────────────────────────────────────────

def test_initial_state_is_connected():
    adapter = HFLinkAdapter(drone_id=5)
    assert adapter.state == HFLinkState.CONNECTED


def test_tick_stays_connected_within_degraded_threshold():
    adapter = HFLinkAdapter(drone_id=5)
    t = [100.0]
    with patch("app.modules.drone_control.hf_link_adapter.time.monotonic", side_effect=lambda: t[0]):
        adapter._last_rx = t[0]
        t[0] += HF_DEGRADED_THRESHOLD_S - 1
        assert adapter.tick() == HFLinkState.CONNECTED


def test_tick_transitions_to_degraded_after_threshold():
    adapter = HFLinkAdapter(drone_id=5)
    t = [100.0]
    with patch("app.modules.drone_control.hf_link_adapter.time.monotonic", side_effect=lambda: t[0]):
        adapter._last_rx = t[0]
        t[0] += HF_DEGRADED_THRESHOLD_S + 1
        assert adapter.tick() == HFLinkState.DEGRADED
        assert adapter._degraded_at == t[0]


def test_tick_transitions_to_lost_after_lost_threshold():
    adapter = HFLinkAdapter(drone_id=5)
    t = [100.0]
    with patch("app.modules.drone_control.hf_link_adapter.time.monotonic", side_effect=lambda: t[0]):
        adapter._last_rx = t[0]
        t[0] += HF_LOST_THRESHOLD_S + 1
        assert adapter.tick() == HFLinkState.LOST


def test_on_message_received_restores_connected_state_from_degraded():
    adapter = HFLinkAdapter(drone_id=5)
    adapter.state = HFLinkState.DEGRADED
    adapter._degraded_at = 123.0

    adapter.on_message_received()

    assert adapter.state == HFLinkState.CONNECTED
    assert adapter._degraded_at is None


def test_on_message_received_updates_last_rx_timestamp():
    adapter = HFLinkAdapter(drone_id=5)
    with patch("app.modules.drone_control.hf_link_adapter.time.monotonic", return_value=999.0):
        adapter.on_message_received()
    assert adapter._last_rx == 999.0


# ── update_link_quality / get_status ─────────────────────────────────────────

def test_update_link_quality_stores_snr_and_ber():
    adapter = HFLinkAdapter(drone_id=7)
    adapter.update_link_quality(snr_db=12.5, ber=0.001)
    assert adapter.snr_db == 12.5
    assert adapter.ber == 0.001


def test_update_link_quality_logs_warning_on_poor_snr():
    adapter = HFLinkAdapter(drone_id=7)
    with patch("app.modules.drone_control.hf_link_adapter.log") as mock_log:
        adapter.update_link_quality(snr_db=2.0, ber=0.1)
        mock_log.warning.assert_called_once()


def test_get_status_reports_expected_fields():
    adapter = HFLinkAdapter(drone_id=9, modem_type="harris")
    adapter.update_link_quality(snr_db=10.0, ber=0.01)

    status = adapter.get_status()

    assert status["drone_id"] == 9
    assert status["link_type"] == "hf"
    assert status["state"] == HFLinkState.CONNECTED.value
    assert status["modem_type"] == "harris"
    assert status["snr_db"] == 10.0
    assert status["ber"] == 0.01
    assert "silence_s" in status
    assert status["heartbeat_timeout_s"] == hla.HF_HEARTBEAT_TIMEOUT_S
    assert status["command_ack_timeout_s"] == hla.HF_COMMAND_ACK_TIMEOUT_S


# ── module-level registry ────────────────────────────────────────────────────

def test_get_or_create_returns_same_instance_for_same_drone_id():
    a1 = hla.get_or_create(1, "codan")
    a2 = hla.get_or_create(1, "different_modem_ignored")
    assert a1 is a2
    assert a1.modem_type == "codan"


def test_get_or_create_creates_distinct_adapters_per_drone_id():
    a1 = hla.get_or_create(1)
    a2 = hla.get_or_create(2)
    assert a1 is not a2


def test_remove_deletes_adapter_and_is_idempotent():
    hla.get_or_create(3)
    hla.remove(3)
    assert 3 not in hla._hf_adapters
    # Removing again should not raise.
    hla.remove(3)


def test_get_all_statuses_returns_status_for_every_registered_adapter():
    hla.get_or_create(1)
    hla.get_or_create(2)

    statuses = hla.get_all_statuses()

    assert {s["drone_id"] for s in statuses} == {1, 2}


# ── run_tick_loop ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_run_tick_loop_ticks_all_registered_adapters():
    a1 = hla.get_or_create(1)
    a2 = hla.get_or_create(2)

    with patch.object(a1, "tick") as tick1, patch.object(a2, "tick") as tick2:
        task = asyncio.create_task(hla.run_tick_loop(interval_s=0))
        # Allow the loop to run a couple of iterations.
        for _ in range(3):
            await asyncio.sleep(0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

        tick1.assert_called()
        tick2.assert_called()
