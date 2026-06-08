from typing import Annotated, Optional
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_db
from app.core.rbac import require_min_role, Role
from app.models.user import User
from app.modules.drone_analyst.service import AnalystService

router = APIRouter()
DbDep      = Annotated[AsyncSession, Depends(get_db)]
ViewerDep  = Annotated[User, Depends(require_min_role(Role.VIEWER))]
AnalystDep = Annotated[User, Depends(require_min_role(Role.MISSION_COMMANDER))]


# ── Module status ─────────────────────────────────────────────────

@router.get("/status")
async def analyst_status(db: DbDep, _: ViewerDep):
    """Module health and capability summary."""
    return AnalystService(db).get_status()


# ── Analysis jobs ─────────────────────────────────────────────────

@router.post("/jobs", status_code=201)
async def create_job(
    body: dict,
    db: DbDep,
    user: AnalystDep,
):
    """
    Submit an analysis job.

    Body fields:
      job_type    — object_detection | change_detection |
                    video_analysis | telemetry_report
      mission_id  — (optional) source mission
      drone_id    — (optional) source drone
      model_id    — (optional) model from registry
      params      — job-specific parameters dict
    """
    return AnalystService(db).create_job(
        job_type     = body.get("job_type", "telemetry_report"),
        mission_id   = body.get("mission_id"),
        drone_id     = body.get("drone_id"),
        model_id     = body.get("model_id"),
        params       = body.get("params", {}),
        submitted_by = user.id,
    )


@router.get("/jobs")
async def list_jobs(
    db: DbDep,
    _: ViewerDep,
    mission_id: Optional[int] = Query(None),
    job_type:   Optional[str] = Query(None),
    status:     Optional[str] = Query(None),
    limit:      int           = Query(50, ge=1, le=200),
):
    """List analysis jobs with optional filters."""
    jobs = AnalystService(db).list_jobs(mission_id, job_type, status, limit)
    return {"jobs": jobs, "total": len(jobs)}


@router.get("/jobs/{job_id}")
async def get_job(job_id: str, db: DbDep, _: ViewerDep):
    """Retrieve a single analysis job by ID."""
    return AnalystService(db).get_job(job_id)


@router.post("/jobs/{job_id}/cancel")
async def cancel_job(job_id: str, db: DbDep, _: AnalystDep):
    """Cancel a pending or running analysis job."""
    return AnalystService(db).cancel_job(job_id)


# ── Detection results ─────────────────────────────────────────────

@router.get("/results")
async def list_results(
    db: DbDep,
    _: ViewerDep,
    mission_id: Optional[int] = Query(None),
    limit:      int           = Query(100, ge=1, le=500),
):
    """
    Query detection results.
    V1 returns empty list — populated by inference workers in V2.
    """
    return AnalystService(db).list_results(mission_id, limit)


# ── Model registry ────────────────────────────────────────────────

@router.get("/models")
async def list_models(db: DbDep, _: ViewerDep):
    """List all registered AI/ML models and their deployment status."""
    models = AnalystService(db).list_models()
    return {"models": models, "total": len(models)}


@router.get("/models/{model_id}")
async def get_model(model_id: str, db: DbDep, _: ViewerDep):
    """Get detail for a specific model."""
    return AnalystService(db).get_model(model_id)


# ── Telemetry analytics (V1 available) ───────────────────────────

@router.get("/missions/{mission_id}/stats")
async def mission_stats(mission_id: int, db: DbDep, _: ViewerDep):
    """
    Aggregate telemetry statistics for a completed mission.
    Queries TimescaleDB — returns real data from recorded telemetry.
    """
    return await AnalystService(db).mission_telemetry_stats(mission_id)


@router.get("/missions/{mission_id}/series")
async def mission_series(
    mission_id: int,
    db: DbDep,
    _: ViewerDep,
    param:          str = Query("alt_agl", description="Telemetry parameter to plot"),
    bucket_seconds: int = Query(5, ge=1, le=300, description="Time-bucket size in seconds"),
):
    """
    Downsampled time-series for a single telemetry parameter over a mission.
    Used by the Monitor workspace chart for post-mission review.
    """
    return await AnalystService(db).mission_telemetry_series(
        mission_id, param, bucket_seconds
    )