"""
Analyst Job-Queue Consumer Tests
================================
Verifies backend/app/modules/drone_analyst/job_consumer.py — the RabbitMQ
worker that drives AnalysisJob through queued -> running -> done/failed.

Architecture under test
------------------------
  1. AnalystService.create_job() persists an AnalysisJob row with
     status='queued' and publishes {"job_id": ...} to routing key
     "drone_analyst.job_submitted" (covered in test_analyst_api.py).
  2. start_job_consumer() subscribes to that routing key on queue
     "analyst_job_queue" via app.core.events.subscribe.
  3. The handler loads the job, transitions queued -> running, executes
     the (V1 placeholder) inference step, then transitions to done (with
     a result) or failed (with an error message).

Test strategy
-------------
  - app.core.events.subscribe is mocked so tests run without a broker;
    the handler closure is captured and invoked directly.
  - The handler is exercised against the real SQLite test DB (via the
    AsyncSessionLocal override) so state transitions are verified through
    actual persistence, not mocks.
"""
import pytest
from unittest.mock import AsyncMock, patch

from app.models.analysis import AnalysisJob
from app.modules.drone_analyst.job_consumer import (
    start_job_consumer,
    _handle_job_message,
    QUEUE_NAME,
    ROUTING_KEY,
)


async def _create_queued_job(session_factory, **overrides):
    """Insert an AnalysisJob directly and return its id."""
    defaults = dict(
        job_type="telemetry_report",
        status="queued",
        mission_id=None,
        drone_id=None,
        model_id=None,
        params={},
        submitted_by=1,
    )
    defaults.update(overrides)
    async with session_factory() as session:
        job = AnalysisJob(**defaults)
        session.add(job)
        await session.commit()
        await session.refresh(job)
        return job.id


@pytest.fixture
def patched_session_factory():
    """
    Point job_consumer.AsyncSessionLocal at the same in-memory SQLite
    engine the API tests use, so the consumer handler and the test
    assertions see the same data.
    """
    from app.tests.conftest import _TestSession
    import app.modules.drone_analyst.job_consumer as consumer_mod

    original = consumer_mod.AsyncSessionLocal
    consumer_mod.AsyncSessionLocal = _TestSession
    yield _TestSession
    consumer_mod.AsyncSessionLocal = original


# ══════════════════════════════════════════════════════════════════════
# Subscription wiring
# ══════════════════════════════════════════════════════════════════════

async def test_start_job_consumer_subscribes_with_correct_routing():
    """start_job_consumer() must subscribe to the expected routing key/queue."""
    captured = {}

    async def fake_subscribe(routing_key_pattern, queue_name, handler):
        captured["routing_key"] = routing_key_pattern
        captured["queue_name"] = queue_name
        captured["handler"] = handler

    with patch("app.modules.drone_analyst.job_consumer.subscribe", side_effect=fake_subscribe):
        await start_job_consumer()

    assert captured["routing_key"] == ROUTING_KEY == "drone_analyst.job_submitted"
    assert captured["queue_name"] == QUEUE_NAME == "analyst_job_queue"
    assert callable(captured["handler"])


# ══════════════════════════════════════════════════════════════════════
# State machine: queued -> running -> done
# ══════════════════════════════════════════════════════════════════════

async def test_handler_transitions_queued_to_done(patched_session_factory):
    """A queued job must end up 'done' with a result and timestamps set."""
    job_id = await _create_queued_job(patched_session_factory)

    await _handle_job_message({"job_id": job_id})

    async with patched_session_factory() as session:
        job = await session.get(AnalysisJob, job_id)
        assert job.status == "done"
        assert job.started_at is not None
        assert job.completed_at is not None
        assert job.result is not None
        assert job.error is None


async def test_handler_result_reflects_job_type_and_model(patched_session_factory):
    """The placeholder result must echo back job_type/model_id for traceability."""
    job_id = await _create_queued_job(
        patched_session_factory,
        job_type="object_detection",
        model_id="yolov8n-coco",
    )

    await _handle_job_message({"job_id": job_id})

    async with patched_session_factory() as session:
        job = await session.get(AnalysisJob, job_id)
        assert job.status == "done"
        assert job.result["job_type"] == "object_detection"
        assert job.result["model_id"] == "yolov8n-coco"


async def test_handler_sets_running_before_done(patched_session_factory):
    """
    started_at must be populated (proof the job passed through 'running')
    and must be <= completed_at.
    """
    job_id = await _create_queued_job(patched_session_factory)

    await _handle_job_message({"job_id": job_id})

    async with patched_session_factory() as session:
        job = await session.get(AnalysisJob, job_id)
        assert job.started_at <= job.completed_at


# ══════════════════════════════════════════════════════════════════════
# State machine: queued -> running -> failed
# ══════════════════════════════════════════════════════════════════════

async def test_handler_transitions_to_failed_on_exception(patched_session_factory):
    """If _execute_job raises, the job must end up 'failed' with error captured."""
    job_id = await _create_queued_job(patched_session_factory)

    with patch(
        "app.modules.drone_analyst.job_consumer._execute_job",
        new=AsyncMock(side_effect=RuntimeError("inference backend unavailable")),
    ):
        await _handle_job_message({"job_id": job_id})

    async with patched_session_factory() as session:
        job = await session.get(AnalysisJob, job_id)
        assert job.status == "failed"
        assert job.error == "inference backend unavailable"
        assert job.completed_at is not None
        assert job.result is None


# ══════════════════════════════════════════════════════════════════════
# Idempotency / guard conditions
# ══════════════════════════════════════════════════════════════════════

async def test_handler_ignores_missing_job_id(patched_session_factory):
    """A message with no job_id must not raise."""
    await _handle_job_message({})  # should log and return, not crash


async def test_handler_ignores_unknown_job_id(patched_session_factory):
    """A job_id that doesn't exist in the DB must not raise."""
    await _handle_job_message({"job_id": "00000000-0000-0000-0000-000000000000"})


async def test_handler_skips_job_not_in_queued_state(patched_session_factory):
    """
    Redelivery of a message for an already-running/done job must be a no-op
    (prevents double-processing under at-least-once delivery / requeue).
    """
    job_id = await _create_queued_job(patched_session_factory, status="done")

    async with patched_session_factory() as session:
        job = await session.get(AnalysisJob, job_id)
        job.result = {"already": "done"}
        await session.commit()

    await _handle_job_message({"job_id": job_id})

    async with patched_session_factory() as session:
        job = await session.get(AnalysisJob, job_id)
        # Untouched — handler must not re-run or overwrite a completed job
        assert job.status == "done"
        assert job.result == {"already": "done"}


async def test_handler_skips_cancelled_job(patched_session_factory):
    """A cancelled job must never be flipped to running/done by a stale message."""
    job_id = await _create_queued_job(patched_session_factory, status="cancelled")

    await _handle_job_message({"job_id": job_id})

    async with patched_session_factory() as session:
        job = await session.get(AnalysisJob, job_id)
        assert job.status == "cancelled"
        assert job.result is None


# ══════════════════════════════════════════════════════════════════════
# End-to-end: subscribe wiring + handler invocation together
# ══════════════════════════════════════════════════════════════════════

async def test_consumer_end_to_end_via_captured_handler(patched_session_factory):
    """
    Simulate a real message delivery: start_job_consumer() registers the
    handler, then a message is delivered to that exact captured closure.
    """
    job_id = await _create_queued_job(patched_session_factory)

    captured_handler = None

    async def fake_subscribe(routing_key_pattern, queue_name, handler):
        nonlocal captured_handler
        captured_handler = handler

    with patch("app.modules.drone_analyst.job_consumer.subscribe", side_effect=fake_subscribe):
        await start_job_consumer()

    assert captured_handler is not None
    await captured_handler({"job_id": job_id})

    async with patched_session_factory() as session:
        job = await session.get(AnalysisJob, job_id)
        assert job.status == "done"
