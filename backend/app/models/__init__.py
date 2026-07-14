# app/models/__init__.py
# Import all models here so SQLAlchemy metadata and
# Alembic autogenerate can discover every table.
from app.models.user     import User                      # noqa: F401
from app.models.drone    import DroneType, DroneInstance, DroneConfigTemplate  # noqa: F401
from app.models.mission  import Mission, Waypoint         # noqa: F401
from app.models.vessel   import NavalVessel               # noqa: F401
from app.models.payload  import PayloadType               # noqa: F401
from app.models.threat   import ThreatSystem              # noqa: F401
