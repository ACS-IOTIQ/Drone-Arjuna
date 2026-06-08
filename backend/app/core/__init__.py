
# app/core/__init__.py
# Package marker for cross-cutting concerns:
#   auth, rbac, events (RabbitMQ), security
from app.core.auth      import get_current_user
from app.core.rbac      import require_min_role, Role
from app.core.security  import PasswordPolicy, TokenBlacklist, AuditLogger, RateLimiter
from app.core.events    import publish, emit_telemetry_update
