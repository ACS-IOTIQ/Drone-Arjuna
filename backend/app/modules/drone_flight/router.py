from typing import Annotated
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete, func

from app.database import get_db
from app.core.rbac import require_min_role, Role
from app.models.user import User
from app.models.mission import Mission, Waypoint
from app.schemas.mission import (
    MissionCreate, MissionOut, MissionSummary,
    MissionStatusUpdate, MissionUpdate, WaypointOut, LiveWaypointSync,
)
from app.modules.drone_control import mavlink_manager
from app.modules.drone_flight.geo_service import compute_mission_summary
from app.modules.drone_flight.mission_planner import MissionPlanner, deconflict_missions
from app.modules.drone_flight.airspace_service import validate_mission_airspace
from app.modules.drone_flight.fleet_router import (
    AssignmentProblem, FleetAssignRequest,
    classical_assignment, quantum_assignment, decompose_fleet_indices,
)

router = APIRouter()
DbDep = Annotated[AsyncSession, Depends(get_db)]
PilotDep = Annotated[User, Depends(require_min_role(Role.FLIGHT_CONTROLLER))]
ViewerDep = Annotated[User, Depends(require_min_role(Role.VIEWER))]


@router.get("/missions", response_model=list[MissionOut])
async def list_missions(db: DbDep, _: ViewerDep):
    result = await db.execute(select(Mission).order_by(Mission.created_at.desc()))
    missions = result.scalars().all()
    # Attach waypoints
    out = []
    for m in missions:
        wps = await db.execute(
            select(Waypoint).where(Waypoint.mission_id == m.id).order_by(Waypoint.sequence)
        )
        m_dict = MissionOut.model_validate(m).model_dump()
        m_dict["waypoints"] = [WaypointOut.model_validate(w) for w in wps.scalars().all()]
        out.append(m_dict)
    return out


def _enforce_airspace(waypoints_body, geofence_body):
    """Raise 422 if the mission violates any government airspace restriction."""
    wp_points = [
        (wp.latitude, wp.longitude, f"Waypoint {i + 1}")
        for i, wp in enumerate(waypoints_body or [])
    ]
    result = validate_mission_airspace(wp_points, geofence_body)
    if not result.ok:
        raise HTTPException(status_code=422, detail={"errors": result.error_messages})


@router.post("/missions", response_model=MissionOut, status_code=201)
async def create_mission(body: MissionCreate, db: DbDep, user: PilotDep):
    _enforce_airspace(body.waypoints, body.geofence)

    existing_count = await db.scalar(
        select(func.count()).select_from(Mission).where(
            Mission.drone_instance_id == body.drone_instance_id
        )
    )
    # A drone's first mission is auto-approved; any additional mission
    # for the same drone must go through commander approval (stays "planning").
    initial_status = "approved" if existing_count == 0 else "planning"

    m = Mission(
        name=body.name,
        description=body.description,
        mission_type=body.mission_type,
        drone_instance_id=body.drone_instance_id,
        created_by=user.id,
        notes=body.notes,
        geofence=body.geofence,
        payload_weight_kg=body.payload_weight_kg,
        status=initial_status,
    )
    db.add(m)
    await db.flush()   # get m.id

    for i, wp_data in enumerate(body.waypoints):
        wp = Waypoint(mission_id=m.id, **wp_data.model_dump())
        db.add(wp)

    await db.flush()
    await db.refresh(m)

    wps = await db.execute(
        select(Waypoint).where(Waypoint.mission_id == m.id).order_by(Waypoint.sequence)
    )
    result = MissionOut.model_validate(m).model_dump()
    result["waypoints"] = [WaypointOut.model_validate(w) for w in wps.scalars().all()]
    return result


@router.get("/missions/{mid}", response_model=MissionOut)
async def get_mission(mid: int, db: DbDep, _: ViewerDep):
    m = await db.get(Mission, mid)
    if not m:
        raise HTTPException(404, "Mission not found")
    wps = await db.execute(
        select(Waypoint).where(Waypoint.mission_id == mid).order_by(Waypoint.sequence)
    )
    result = MissionOut.model_validate(m).model_dump()
    result["waypoints"] = [WaypointOut.model_validate(w) for w in wps.scalars().all()]
    return result


@router.get("/missions/{mid}/summary", response_model=MissionSummary)
async def mission_summary(mid: int, db: DbDep, _: ViewerDep):
    """Computes estimated distance, flight time, and battery usage."""
    wps = await db.execute(
        select(Waypoint).where(Waypoint.mission_id == mid).order_by(Waypoint.sequence)
    )
    wp_list = wps.scalars().all()
    if not wp_list:
        raise HTTPException(400, "Mission has no waypoints")
    return compute_mission_summary(wp_list)


@router.patch("/missions/{mid}", response_model=MissionOut)
async def update_mission(
    mid: int, body: MissionUpdate, db: DbDep, _: PilotDep,
):
    """Update mission fields (name, geofence, waypoints, etc.). Only allowed in 'planning' status."""
    m = await db.get(Mission, mid)
    if not m:
        raise HTTPException(404, "Mission not found")
    if m.status not in ("planning",):
        raise HTTPException(409, f"Cannot edit a mission with status '{m.status}'")

    _enforce_airspace(body.waypoints, body.geofence)

    update_data = body.model_dump(exclude_unset=True, exclude={"waypoints"})
    for field, value in update_data.items():
        setattr(m, field, value)

    if body.waypoints is not None:
        await db.execute(delete(Waypoint).where(Waypoint.mission_id == mid))
        for wp_data in body.waypoints:
            db.add(Waypoint(mission_id=mid, **wp_data.model_dump()))

    await db.flush()
    await db.refresh(m)
    wps = await db.execute(
        select(Waypoint).where(Waypoint.mission_id == mid).order_by(Waypoint.sequence)
    )
    result = MissionOut.model_validate(m).model_dump()
    result["waypoints"] = [WaypointOut.model_validate(w) for w in wps.scalars().all()]
    return result


@router.patch("/missions/{mid}/status")
async def update_mission_status(
    mid: int,
    body: MissionStatusUpdate,
    db: DbDep,
    _: Annotated[User, Depends(require_min_role(Role.MISSION_COMMANDER))],
):
    m = await db.get(Mission, mid)
    if not m:
        raise HTTPException(404, "Mission not found")

    if body.status == "approved":
        # Load waypoints for the mission being approved
        wps_result = await db.execute(
            select(Waypoint).where(Waypoint.mission_id == mid).order_by(Waypoint.sequence)
        )
        target_wps = wps_result.scalars().all()

        # Load all currently active missions (approved or executing), excluding this one.
        # Missions assigned to a different drone can't physically collide, so only
        # missions sharing the same assigned drone are considered for deconfliction.
        active_result = await db.execute(
            select(Mission).where(
                Mission.status.in_(["approved", "executing"]),
                Mission.id != mid,
                Mission.drone_instance_id == m.drone_instance_id,
            )
        )
        active_missions = active_result.scalars().all()

        # Load waypoints for each active mission
        missions_with_waypoints: list[tuple[Mission, list[Waypoint]]] = [
            (m, list(target_wps))
        ]
        for active in active_missions:
            aw_result = await db.execute(
                select(Waypoint)
                .where(Waypoint.mission_id == active.id)
                .order_by(Waypoint.sequence)
            )
            missions_with_waypoints.append((active, aw_result.scalars().all()))

        conflicts = deconflict_missions(missions_with_waypoints)
        if conflicts:
            raise HTTPException(
                status_code=409,
                detail={
                    "message": (
                        "Approval blocked — airspace conflict detected with "
                        f"{len(conflicts)} active mission(s)"
                    ),
                    "conflicts": conflicts,
                },
            )

    m.status = body.status
    return {"detail": "Status updated", "status": body.status}


@router.delete("/missions/{mid}", status_code=204)
async def delete_mission(mid: int, db: DbDep, _: PilotDep):
    m = await db.get(Mission, mid)
    if not m:
        raise HTTPException(404, "Mission not found")
    if m.status == "executing":
        raise HTTPException(409, "Cannot delete an executing mission")
    await db.execute(delete(Waypoint).where(Waypoint.mission_id == mid))
    await db.delete(m)


@router.post("/missions/{mid}/validate")
async def validate_mission(mid: int, db: DbDep, _: PilotDep):
    """
    Runs MissionValidator against the mission and returns
    any errors or warnings without changing mission state.
    """
    m = await db.get(Mission, mid)
    if not m:
        raise HTTPException(404, "Mission not found")
    wps_result = await db.execute(
        select(Waypoint).where(Waypoint.mission_id == mid).order_by(Waypoint.sequence)
    )
    wps = wps_result.scalars().all()
    result = await MissionPlanner(db).validate_mission(m, wps)
    return {
        "valid":    result.valid,
        "errors":   result.errors,
        "warnings": result.warnings,
    }


@router.post("/missions/{mid}/upload")
async def upload_mission(
    mid: int, db: DbDep,
    _: Annotated[User, Depends(require_min_role(Role.FLIGHT_CONTROLLER))],
):
    """
    Validates and uploads the mission waypoints to the assigned
    drone via MAVLink mission protocol. Drone must be connected.
    """
    m = await db.get(Mission, mid)
    if not m:
        raise HTTPException(404, "Mission not found")
    wps_result = await db.execute(
        select(Waypoint).where(Waypoint.mission_id == mid).order_by(Waypoint.sequence)
    )
    wps = wps_result.scalars().all()
    return await MissionPlanner(db).upload_to_drone(m, wps)


@router.post("/missions/live-sync/{drone_instance_id}")
async def live_sync_waypoints(
    drone_instance_id: int, body: LiveWaypointSync, _: PilotDep,
):
    """
    Pushes the waypoints currently being drawn/dragged in the UI straight to
    the connected drone over its live MAVLink link (e.g. UDP to ArduPilot
    SITL) — no saved Mission required. Meant to be called repeatedly
    (debounced) while the operator edits the route on the map, so the
    vehicle's onboard mission stays in sync in real time.
    """
    if body.waypoints:
        _enforce_airspace(body.waypoints, body.geofence)
    return await MissionPlanner.upload_live_waypoints(drone_instance_id, body.waypoints)


@router.get("/missions/{mid}/simulate")
async def simulate_mission(mid: int, db: DbDep, _: ViewerDep):
    """
    Returns a sequence of position/battery frames at 1-second resolution
    for the frontend pre-flight animation.
    """
    wps_result = await db.execute(
        select(Waypoint).where(Waypoint.mission_id == mid).order_by(Waypoint.sequence)
    )
    wps = wps_result.scalars().all()
    if not wps:
        raise HTTPException(400, "Mission has no waypoints")
    frames = await MissionPlanner(db).build_simulation(wps)
    return {"mission_id": mid, "frame_count": len(frames), "frames": frames}


@router.post("/assign-fleet")
async def assign_fleet(body: FleetAssignRequest, _: PilotDep):
    """
    Multi-drone -> target assignment (Q-SWARM port).
    Uses live drone positions from the telemetry hot-cache (mavlink_manager.state) --
    does not require a Mission to exist yet. Returns which drone should go
    to which target, minimising total travel distance.
    """
    live = mavlink_manager.state.get_all()
    if body.drone_instance_ids is not None:
        live = {did: s for did, s in live.items() if did in body.drone_instance_ids}
    live = {did: s for did, s in live.items() if s.get("connected")}

    if not live:
        raise HTTPException(400, "No connected drones available for assignment")
    if not body.targets:
        raise HTTPException(400, "At least one target is required")

    drone_ids = list(live.keys())
    drones = [(live[did]["lat"], live[did]["lon"]) for did in drone_ids]
    targets = [(t.lat, t.lon) for t in body.targets]

    if body.use_quantum:
        subs = decompose_fleet_indices(drones, targets, body.qubit_budget)
    else:
        subs = [(list(range(len(drones))), list(range(len(targets))))]

    solver_name = "QAOA (Aer)" if body.use_quantum else "OR-Tools"
    assignments: list[dict] = []
    total_distance_m = 0.0
    all_feasible = True

    for d_idx, t_idx in subs:
        problem = AssignmentProblem(
            drones=[drones[i] for i in d_idx],
            targets=[targets[j] for j in t_idx],
        )
        if body.use_quantum:
            bits, cost_m, _ms = quantum_assignment(problem)
        else:
            bits, cost_m, _ms = classical_assignment(problem)

        all_feasible &= problem.is_feasible(bits)
        total_distance_m += cost_m

        for local_j, local_is in problem.decode(bits).items():
            target = body.targets[t_idx[local_j]]
            for local_i in local_is:
                drone_id = drone_ids[d_idx[local_i]]
                assignments.append({
                    "drone_instance_id": drone_id,
                    "call_sign": live[drone_id].get("call_sign"),
                    "target_id": target.id,
                    "target_lat": target.lat,
                    "target_lon": target.lon,
                    "distance_m": round(problem.cost[local_i][local_j], 1),
                })

    return {
        "solver": solver_name,
        "num_subproblems": len(subs),
        "total_distance_m": round(total_distance_m, 1),
        "all_feasible": all_feasible,
        "assignments": assignments,
    }


@router.post("/survey-grid")
async def generate_survey_grid(body: dict, _: PilotDep):
    """
    Generates lawnmower survey waypoints from a polygon.
    Body: { polygon: [[lat,lon],...], altitude_m, spacing_m, speed_ms }
    Returns waypoint list ready to insert into a mission.
    """
    try:
        polygon  = [tuple(p) for p in body["polygon"]]
        altitude = float(body["altitude_m"])
        spacing  = float(body.get("spacing_m", 50.0))
        speed    = body.get("speed_ms")
    except (KeyError, TypeError, ValueError) as e:
        raise HTTPException(400, f"Invalid body: {e}")

    waypoints = MissionPlanner.generate_survey_grid(polygon, altitude, spacing, speed_ms=speed)
    return {"waypoints": waypoints, "count": len(waypoints)}
