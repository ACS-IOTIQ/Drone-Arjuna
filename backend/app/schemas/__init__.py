# Re-export all schemas so routers can do:
#   from app.schemas import UserOut, MissionCreate, etc.
# instead of importing from deep paths.

from app.schemas.user      import UserCreate, UserUpdate, UserOut, TokenOut, TokenPayload
from app.schemas.drone     import (
    DroneTypeCreate, DroneTypeUpdate, DroneTypeOut,
    DroneInstanceCreate, DroneInstanceUpdate, DroneInstanceOut,
    ConnectRequest, CommandRequest, ConnectionStatusOut,
    DroneConfigTemplateCreate, DroneConfigTemplateUpdate, DroneConfigTemplateOut,
)
from app.schemas.payload   import (
    PayloadTypeCreate, PayloadTypeUpdate, PayloadTypeOut,
)
from app.schemas.mission   import (
    WaypointCreate, WaypointUpdate, WaypointOut,
    MissionCreate, MissionUpdate, MissionOut,
    MissionStatusUpdate, MissionSummary,
)
from app.schemas.telemetry import (
    TelemetryFrameOut, TelemetryQueryParams, TelemetryStats,
)

__all__ = [
    # User
    "UserCreate", "UserUpdate", "UserOut", "TokenOut", "TokenPayload",
    # Drone
    "DroneTypeCreate", "DroneTypeUpdate", "DroneTypeOut",
    "DroneInstanceCreate", "DroneInstanceUpdate", "DroneInstanceOut",
    "ConnectRequest", "CommandRequest", "ConnectionStatusOut",
    "DroneConfigTemplateCreate", "DroneConfigTemplateUpdate", "DroneConfigTemplateOut",
    # Payload
    "PayloadTypeCreate", "PayloadTypeUpdate", "PayloadTypeOut",
    # Mission
    "WaypointCreate", "WaypointUpdate", "WaypointOut",
    "MissionCreate", "MissionUpdate", "MissionOut",
    "MissionStatusUpdate", "MissionSummary",
    # Telemetry
    "TelemetryFrameOut", "TelemetryQueryParams", "TelemetryStats",
]