"""
Drone Analyst Service
=====================
Business logic for the Drone Analyst module.

V1 scope:
  - Analysis job registry (create, track, retrieve results) — persisted in
    PostgreSQL and processed asynchronously via a RabbitMQ job-queue consumer
  - Mission telemetry statistics from TimescaleDB
  - Detection result storage and query (schema ready, no AI inference yet)
  - Model registry (records available models for V2 activation)

V2 will add:
  - YOLOv8 object detection pipeline (Ultralytics)
  - PyTorch / ONNX Runtime inference workers via Celery
  - Video stream processing (FFmpeg frame extraction → model → results)
  - Change detection across mission timeframes
  - Automated report generation
  - Elasticsearch indexing of detection results
"""
import structlog
from datetime import datetime, timezone
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, text
from fastapi import HTTPException

from app.database import TSSessionLocal
from app.models.analysis import AnalysisJob, JobArtifact
from app.core.events import publish
from app.core import storage

log = structlog.get_logger()

JOB_QUEUE_ROUTING_KEY = "drone_analyst.job_submitted"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)

# ── Model registry (V1) ───────────────────────────────────────────
# V2 will load these from a DB table populated by the model deployment pipeline.
_MODEL_REGISTRY: list[dict] = [
    {
        "id":          "yolov8n-coco",
        "name":        "YOLOv8 Nano — COCO",
        "type":        "object_detection",
        "framework":   "ultralytics",
        "status":      "pending_v2",
        "description": "General-purpose object detection, 80 COCO classes",
        "input":       "image/video",
        "precision":   "FP32",
    },
    {
        "id":          "yolov8m-military",
        "name":        "YOLOv8 Medium — Military Assets",
        "type":        "object_detection",
        "framework":   "ultralytics",
        "status":      "pending_v2",
        "description": "Fine-tuned on military vehicle and personnel classes",
        "input":       "image/video",
        "precision":   "FP32",
    },
    {
        "id":          "change-detect-v1",
        "name":        "Change Detection v1",
        "type":        "change_detection",
        "framework":   "pytorch",
        "status":      "pending_v2",
        "description": "Temporal change detection across repeat-pass imagery",
        "input":       "image_pair",
        "precision":   "FP32",
    },
]


# ══════════════════════════════════════════════════════════════════
# AnalystService
# ══════════════════════════════════════════════════════════════════

class AnalystService:

    def __init__(self, db: AsyncSession):
        self.db = db   # Main PostgreSQL session

    # ── Module status ─────────────────────────────────────────────

    async def get_status(self) -> dict:
        total = (await self.db.execute(select(AnalysisJob.id))).scalars().all()
        running = (await self.db.execute(
            select(AnalysisJob.id).where(AnalysisJob.status == "running")
        )).scalars().all()
        queued = (await self.db.execute(
            select(AnalysisJob.id).where(AnalysisJob.status == "queued")
        )).scalars().all()
        done = (await self.db.execute(
            select(AnalysisJob.id).where(AnalysisJob.status == "done")
        )).scalars().all()

        return {
            "module_version":     "1.0.0",
            "ai_inference_ready": False,    # Becomes True in V2
            "jobs": {
                "active":   len(running),
                "pending":  len(queued),
                "complete": len(done),
                "total":    len(total),
            },
            "registered_models": len(_MODEL_REGISTRY),
            "capabilities": {
                "object_detection":   "pending_v2",
                "change_detection":   "pending_v2",
                "video_processing":   "pending_v2",
                "automated_reports":  "pending_v2",
                "telemetry_stats":    "available",   # V1 available via TimescaleDB
                "mission_replay":     "available",   # V1 available
            },
        }

    # ── Analysis jobs ─────────────────────────────────────────────

    async def create_job(
        self,
        job_type: str,
        mission_id: Optional[int],
        drone_id: Optional[int],
        model_id: Optional[str],
        params: dict,
        submitted_by: int,
    ) -> AnalysisJob:
        """
        Creates an analysis job record and enqueues it for processing.
        Status starts at 'queued'; the job-queue consumer transitions it
        to 'running' and finally 'done'/'failed'.
        """
        valid_types = {
            "object_detection", "change_detection",
            "video_analysis", "telemetry_report",
        }
        if job_type not in valid_types:
            raise HTTPException(400, f"job_type must be one of {valid_types}")

        if model_id and model_id not in {m["id"] for m in _MODEL_REGISTRY}:
            raise HTTPException(404, f"Model '{model_id}' not found in registry")

        job = AnalysisJob(
            job_type=job_type,
            mission_id=mission_id,
            drone_id=drone_id,
            model_id=model_id,
            params=params,
            submitted_by=submitted_by,
            status="queued",
        )
        self.db.add(job)
        await self.db.commit()
        await self.db.refresh(job)

        await publish(JOB_QUEUE_ROUTING_KEY, {"job_id": job.id})
        log.info("Analysis job queued", job_id=job.id, type=job_type)
        return job

    async def get_job(self, job_id: str) -> AnalysisJob:
        job = await self.db.get(AnalysisJob, job_id)
        if not job:
            raise HTTPException(404, f"Analysis job '{job_id}' not found")
        return job

    async def list_jobs(
        self,
        mission_id: Optional[int] = None,
        job_type:   Optional[str] = None,
        status:     Optional[str] = None,
        limit:      int = 50,
    ) -> list[AnalysisJob]:
        stmt = select(AnalysisJob)
        if mission_id is not None:
            stmt = stmt.where(AnalysisJob.mission_id == mission_id)
        if job_type:
            stmt = stmt.where(AnalysisJob.job_type == job_type)
        if status:
            stmt = stmt.where(AnalysisJob.status == status)
        stmt = stmt.order_by(AnalysisJob.created_at.desc()).limit(limit)
        return (await self.db.execute(stmt)).scalars().all()

    # ── Job artifacts (images, videos, PDF reports) — stored in MinIO ─

    async def upload_artifact(
        self,
        job_id: str,
        filename: str,
        content: bytes,
        content_type: str,
        uploaded_by: int,
    ) -> JobArtifact:
        """
        Uploads a source image, video, or generated PDF report for a job to
        MinIO and records it as a JobArtifact row. Only images, videos, and
        application/pdf content types are accepted.
        """
        job = await self.get_job(job_id)

        try:
            kind = storage.classify_content_type(content_type)
        except ValueError as e:
            raise HTTPException(400, str(e))

        object_key = storage.build_object_key(job_id, filename)
        await storage.ensure_bucket()
        await storage.upload_bytes(object_key, content, content_type)

        artifact = JobArtifact(
            job_id=job_id,
            kind=kind,
            object_key=object_key,
            filename=filename,
            content_type=content_type,
            size_bytes=len(content),
            uploaded_by=uploaded_by,
        )
        self.db.add(artifact)
        await self.db.commit()
        await self.db.refresh(artifact)
        log.info(
            "Job artifact uploaded",
            job_id=job_id, kind=kind, object_key=object_key,
        )
        return artifact

    async def list_artifacts(
        self,
        job_id: str,
        kind: Optional[str] = None,
    ) -> list[JobArtifact]:
        await self.get_job(job_id)  # 404 if job doesn't exist
        stmt = select(JobArtifact).where(JobArtifact.job_id == job_id)
        if kind:
            stmt = stmt.where(JobArtifact.kind == kind)
        stmt = stmt.order_by(JobArtifact.created_at.desc())
        return (await self.db.execute(stmt)).scalars().all()

    async def get_artifact_url(self, job_id: str, artifact_id: str) -> dict:
        artifact = await self.db.get(JobArtifact, artifact_id)
        if not artifact or artifact.job_id != job_id:
            raise HTTPException(404, f"Artifact '{artifact_id}' not found for job '{job_id}'")
        url = await storage.get_presigned_url(artifact.object_key)
        return {
            "artifact_id": artifact.id,
            "job_id": job_id,
            "kind": artifact.kind,
            "filename": artifact.filename,
            "object_key": artifact.object_key,
            "url": url,
        }

    async def delete_artifact(self, job_id: str, artifact_id: str) -> None:
        artifact = await self.db.get(JobArtifact, artifact_id)
        if not artifact or artifact.job_id != job_id:
            raise HTTPException(404, f"Artifact '{artifact_id}' not found for job '{job_id}'")
        await storage.delete_object(artifact.object_key)
        await self.db.delete(artifact)
        await self.db.commit()

    async def cancel_job(self, job_id: str) -> AnalysisJob:
        job = await self.get_job(job_id)
        if job.status in ("done", "failed", "cancelled"):
            raise HTTPException(409, f"Cannot cancel job in status '{job.status}'")
        job.status = "cancelled"
        job.completed_at = _utcnow()
        await self.db.commit()
        await self.db.refresh(job)
        return job

    # ── Detection results ─────────────────────────────────────────

    def list_results(
        self,
        mission_id: Optional[int] = None,
        limit:      int = 100,
    ) -> dict:
        """
        V1: Returns empty list — no inference has run yet.
        V2: Queries PostgreSQL detection_results table populated
            by the Celery inference worker.
        """
        return {
            "results": [],
            "total":   0,
            "mission_id": mission_id,
            "note": "Object detection results populated in V2",
        }

    # ── Model registry ────────────────────────────────────────────

    def list_models(self) -> list[dict]:
        return _MODEL_REGISTRY

    def get_model(self, model_id: str) -> dict:
        model = next((m for m in _MODEL_REGISTRY if m["id"] == model_id), None)
        if not model:
            raise HTTPException(404, f"Model '{model_id}' not found")
        return model

    # ── Telemetry statistics (V1 available via TimescaleDB) ───────

    async def mission_telemetry_stats(self, mission_id: int) -> dict:
        """
        Queries TimescaleDB for aggregate stats over the telemetry
        recorded during a given mission.
        Uses raw SQL because TimescaleDB time_bucket aggregations
        don't map cleanly to SQLAlchemy ORM.
        """
        async with TSSessionLocal() as ts:
            # Check if any telemetry exists for this mission
            count_result = await ts.execute(
                text("""
                    SELECT COUNT(*) FROM telemetry
                    WHERE mission_id = :mid
                """),
                {"mid": mission_id},
            )
            count = count_result.scalar_one()

            if count == 0:
                return {
                    "mission_id":        mission_id,
                    "frame_count":       0,
                    "start_time":        None,
                    "end_time":          None,
                    "duration_min":      0,
                    "avg_altitude_m":    0,
                    "max_altitude_m":    0,
                    "avg_speed_ms":      0,
                    "max_speed_ms":      0,
                    "min_battery_pct":   -1,
                    "avg_cpu_pct":       0,
                    "total_distance_km": 0,
                }

            stats = await ts.execute(
                text("""
                    SELECT
                        COUNT(*)                          AS frame_count,
                        MIN(recorded_at)                  AS start_time,
                        MAX(recorded_at)                  AS end_time,
                        ROUND(AVG(alt_agl)::numeric, 1)   AS avg_altitude_m,
                        ROUND(MAX(alt_agl)::numeric, 1)   AS max_altitude_m,
                        ROUND(AVG(groundspeed_ms)::numeric, 2) AS avg_speed_ms,
                        ROUND(MAX(groundspeed_ms)::numeric, 2) AS max_speed_ms,
                        MIN(battery_remaining_pct)        AS min_battery_pct,
                        ROUND(AVG(cpu_load_pct)::numeric, 1)   AS avg_cpu_pct
                    FROM telemetry
                    WHERE mission_id = :mid
                """),
                {"mid": mission_id},
            )
            row = stats.mappings().one()

            # Compute rough flight distance from position deltas
            dist_result = await ts.execute(
                text("""
                    SELECT COALESCE(SUM(
                        ST_Distance(
                            ST_SetSRID(ST_MakePoint(lon, lat), 4326)::geography,
                            ST_SetSRID(ST_MakePoint(prev_lon, prev_lat), 4326)::geography
                        )
                    ), 0) AS total_distance_m
                    FROM (
                        SELECT
                            lat, lon,
                            LAG(lat) OVER (ORDER BY recorded_at) AS prev_lat,
                            LAG(lon) OVER (ORDER BY recorded_at) AS prev_lon
                        FROM telemetry
                        WHERE mission_id = :mid
                        ORDER BY recorded_at
                    ) sub
                    WHERE prev_lat IS NOT NULL
                """),
                {"mid": mission_id},
            )
            dist_row = dist_result.mappings().one()

            duration_s = (
                (row["end_time"] - row["start_time"]).total_seconds()
                if row["start_time"] and row["end_time"] else 0
            )

            return {
                "mission_id":         mission_id,
                "frame_count":        row["frame_count"],
                "start_time":         row["start_time"].isoformat() if row["start_time"] else None,
                "end_time":           row["end_time"].isoformat()   if row["end_time"]   else None,
                "duration_min":       round(duration_s / 60, 1),
                "avg_altitude_m":     float(row["avg_altitude_m"] or 0),
                "max_altitude_m":     float(row["max_altitude_m"] or 0),
                "avg_speed_ms":       float(row["avg_speed_ms"]   or 0),
                "max_speed_ms":       float(row["max_speed_ms"]   or 0),
                "min_battery_pct":    int(row["min_battery_pct"]  or -1),
                "avg_cpu_pct":        float(row["avg_cpu_pct"]    or 0),
                "total_distance_km":  round(
                    float(dist_row["total_distance_m"] or 0) / 1000, 2
                ),
            }

    async def mission_telemetry_series(
        self,
        mission_id: int,
        param: str,
        bucket_seconds: int = 5,
    ) -> dict:
        """
        Returns a downsampled time-series for a single telemetry
        parameter over a mission — used by the Monitor chart.

        V2 will use the telemetry_1min continuous aggregate for
        longer time windows.
        """
        allowed_params = {
            "alt_agl", "alt_msl", "groundspeed_ms", "airspeed_ms",
            "climb_rate_ms", "battery_remaining_pct", "battery_voltage_v",
            "heading", "roll_deg", "pitch_deg", "rssi", "cpu_load_pct",
        }
        if param not in allowed_params:
            raise HTTPException(
                400,
                f"param must be one of {sorted(allowed_params)}"
            )

        async with TSSessionLocal() as ts:
            result = await ts.execute(
                text(f"""
                    SELECT
                        time_bucket(
                            MAKE_INTERVAL(secs => :bucket),
                            recorded_at
                        ) AS bucket,
                        AVG({param}) AS value
                    FROM telemetry
                    WHERE mission_id = :mid
                    GROUP BY bucket
                    ORDER BY bucket
                """),
                {"mid": mission_id, "bucket": bucket_seconds},
            )
            rows = result.mappings().all()

        return {
            "mission_id":    mission_id,
            "param":         param,
            "bucket_seconds": bucket_seconds,
            "series": [
                {
                    "t":     row["bucket"].isoformat(),
                    "value": round(float(row["value"]), 2) if row["value"] is not None else None,
                }
                for row in rows
            ],
        }