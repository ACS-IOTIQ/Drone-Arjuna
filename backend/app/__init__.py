import os as _os

# MAVLink 2 is required for message signing; pymavlink reads this at import
# time, so it must be set before anything imports pymavlink.
_os.environ.setdefault("MAVLINK20", "1")
# Package marker for the DroneArjuna application.
# Required so Python treats app/ as a package and resolves
# all `from app.xxx import` statements correctly.