"""
Analyst Job-Queue Consumer
==========================
RabbitMQ worker that drains the drone_analyst.job_submitted queue and
drives each AnalysisJob through its state machine:

    queued -> running -> done
                       -> failed

V1 has no real inference backend, so "running" jobs are resolved with a
placeholder result. V2 replaces `_execute_job` with actual model calls
(Ultralytics / ONNX Runtime / etc.) while keeping the same state machine.
"""
import structlog

from app.core.events import subscribe
from app.database import AsyncSessionLocal
from app.models.analysis import AnalysisJob
from app.modules.drone_analyst.service import _utcnow

log = structlog.get_logger()

QUEUE_NAME = "analyst_job_queue"
ROUTING_KEY = "drone_analyst.job_submitted"


async def _execute_job(job: AnalysisJob) -> dict:
    """
    Placeholder inference step.
    V2 dispatches to the appropriate model pipeline based on job.job_type
    and job.model_id, reading source imagery/video from MinIO via the
    job's JobArtifact rows; for now this simply acknowledges the job as
    processed.
    """
    return {
        "note": "AI inference pipeline not yet implemented (V2)",
        "job_type": job.job_type,
        "model_id": job.model_id,
    }


async def _handle_job_message(payload: dict):
    job_id = payload.get("job_id")
    if not job_id:
        log.warning("Job message missing job_id", payload=payload)
        return

    async with AsyncSessionLocal() as db:
        job = await db.get(AnalysisJob, job_id)
        if job is None:
            log.warning("Job not found for queued message", job_id=job_id)
            return
        if job.status != "queued":
            log.info("Skipping job not in queued state", job_id=job_id, status=job.status)
            return

        job.status = "running"
        job.started_at = _utcnow()
        await db.commit()

        try:
            result = await _execute_job(job)
        except Exception as e:
            job.status = "failed"
            job.error = str(e)
            job.completed_at = _utcnow()
            await db.commit()
            log.error("Analysis job failed", job_id=job_id, error=str(e))
            return

        job.status = "done"
        job.result = result
        job.completed_at = _utcnow()
        await db.commit()
        log.info("Analysis job completed", job_id=job_id)


async def start_job_consumer():
    """Subscribe to the analyst job queue. Called once during app startup."""
    await subscribe(
        routing_key_pattern=ROUTING_KEY,
        queue_name=QUEUE_NAME,
        handler=_handle_job_message,
    )
