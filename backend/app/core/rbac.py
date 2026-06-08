from enum import StrEnum
from typing import Annotated
from fastapi import Depends, HTTPException, status
from app.core.auth import get_current_user
from app.models.user import User


class Role(StrEnum):
    ADMIN            = "admin"
    MISSION_COMMANDER = "mission_commander"
    FLIGHT_CONTROLLER = "flight_controller"
    VIEWER           = "viewer"


# Role hierarchy: higher index = more permissions
_HIERARCHY = [Role.VIEWER, Role.FLIGHT_CONTROLLER, Role.MISSION_COMMANDER, Role.ADMIN]


def require_role(*roles: Role):
    """
    FastAPI dependency factory.
    Usage: Depends(require_role(Role.FLIGHT_CONTROLLER, Role.ADMIN))
    """
    allowed = set(roles)

    async def _check(user: Annotated[User, Depends(get_current_user)]) -> User:
        if Role(user.role) not in allowed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Role '{user.role}' is not permitted for this action.",
            )
        return user

    return _check


def require_min_role(min_role: Role):
    """Allow min_role and anything above it in the hierarchy."""
    min_idx = _HIERARCHY.index(min_role)
    allowed = {r for r in _HIERARCHY[min_idx:]}
    return require_role(*allowed)