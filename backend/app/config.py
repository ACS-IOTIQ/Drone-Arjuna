from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import field_validator, model_validator
from functools import lru_cache


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # App
    app_name: str = "DroneArjuna GCS"
    app_version: str = "1.0.0"
    debug: bool = False

    # Database
    database_url: str
    timescale_url: str

    # Redis
    redis_url: str

    # RabbitMQ
    rabbitmq_url: str

    # Auth
    secret_key: str
    access_token_expire_minutes: int = 15
    refresh_token_expire_days: int = 7
    algorithm: str = "HS256"

    # CORS — stored as comma-separated string, parsed into list below
    allowed_origins_str: str = "http://localhost:8080,http://localhost:3000,http://localhost:5173,http://127.0.0.1:8080,http://127.0.0.1:3000"

    @property
    def allowed_origins(self) -> list[str]:
        return [o.strip() for o in self.allowed_origins_str.split(",")]

    # MinIO / S3
    minio_endpoint: str = "minio:9000"
    # Host:port the BROWSER can resolve, used only when presigning URLs handed
    # to the frontend — minio_endpoint above is Docker-internal DNS and is
    # unreachable from the host browser (same class of bug as DEF-08).
    minio_public_endpoint: str = "localhost:9000"
    minio_user: str
    minio_password: str
    minio_secure: bool = False

    # MAVLink SITL defaults
    sitl_host: str = "host.docker.internal"
    sitl_port: int = 14550

    # Simulated-drone MAVLink broadcast — deliberately NOT 14550/14551/14552,
    # since those are already published inbound (docker-compose.yml) for real
    # SITL and would collide with an external GCS trying to listen there too.
    mavlink_broadcast_port: int = 14560

    # MAVLink 2 message signing. Set to a 64-char hex string (32 bytes) shared
    # with the autopilots (ArduPilot: MAVLink2 signing via `signing setup`).
    # When set, outgoing messages are signed and unsigned incoming messages
    # (other than RADIO_STATUS) are dropped. Empty = signing disabled (dev).
    mavlink_signing_key: str = ""

    # Vessel NMEA feed
    # Bind to loopback unless told otherwise; docker-compose sets HF_FEED_HOST=0.0.0.0
    # inside the container and limits the host side with RADIO_BIND_ADDR.
    hf_feed_host: str = "127.0.0.1"
    # Comma-separated IPs/CIDRs allowed to send NMEA (empty = any; a warning is logged).
    hf_feed_allowed_sources_str: str = ""
    hf_feed_max_speed_ms: float = 40.0      # reject fixes implying a faster move than this (~78 kn)
    hf_feed_max_msgs_per_sec: int = 20
    hf_feed_port: int = 10110

    # Elasticsearch
    elasticsearch_url: str = "http://localhost:9200"

    # Database backup / auto-restore
    backup_interval_minutes: int = 60
    backup_retention_count: int = 24
    # Dumps are always HMAC-signed (key derived from SECRET_KEY unless overridden)
    # and a dump whose signature fails is never restored. Set REQUIRE_SIGNATURE=true
    # once all pre-upgrade (unsigned) dumps have rotated out.
    backup_require_signature: bool = False
    backup_signing_key: str = ""
    # Optional encryption at rest (Fernet key: python -c "from cryptography.fernet
    # import Fernet;print(Fernet.generate_key().decode())"). Losing this key makes
    # encrypted dumps unreadable — store it separately from the backups.
    backup_encryption_key: str = ""
    # false = detected data loss is reported but only restored when an admin
    # confirms via POST /api/system/backup/restore.
    backup_auto_restore: bool = True
    # Last-resort restore source: pg_dump .sql files (see core/sql_dump_loader.py).
    # Inside the container the project root is mounted read-only at /project.
    backup_sql_dump_dir: str = "/project/database_dumps"
    integrity_check_interval_minutes: int = 15

    # SMTP — email notifications
    smtp_enabled: bool = False
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = "DroneArjuna GCS <noreply@dronearjuna.local>"
    # MailHog (dev) has no TLS support at all — STARTTLS against it fails with
    # "SMTP STARTTLS extension not supported by server". Real SMTP (Gmail, etc.)
    # requires it. Default True for prod safety; set false in .env for MailHog.
    smtp_use_tls: bool = True

    # Security
    # Docs/OpenAPI are only served when explicitly enabled (dev).
    enable_api_docs: bool = False
    # Roles that must enrol in TOTP MFA (comma-separated, e.g. "admin,mission_commander").
    # Users in these roles can still sign in, but the login response carries
    # mfa_enrollment_required=true so the UI can force enrolment.
    mfa_required_roles_str: str = ""
    # Record every state-changing API call in audit_log (core/audit_middleware.py).
    audit_mutations: bool = True
    frontend_base_url: str = "http://localhost:3000"
    # Set true only behind a trusted reverse proxy that sets X-Forwarded-For.
    trust_proxy_headers: bool = False
    # Login lockout
    login_max_failures: int = 5
    login_lockout_seconds: int = 900
    # Camera SSRF guard: comma-separated hostnames/IPs allowed even if private
    camera_allowed_hosts_str: str = ""

    @property
    def mfa_required_roles(self) -> set[str]:
        return {r.strip() for r in self.mfa_required_roles_str.split(",") if r.strip()}

    @property
    def camera_allowed_hosts(self) -> set[str]:
        return {h.strip().lower() for h in self.camera_allowed_hosts_str.split(",") if h.strip()}

    _WEAK = {"changeme", "changeme123", "please-change-this-secret-key-in-production",
             "secret", "password", "admin", ""}

    @model_validator(mode="after")
    def _reject_weak_secrets(self):
        sk = self.secret_key
        if len(sk.encode()) < 32 or sk.lower() in self._WEAK or "changeme" in sk.lower()                 or "please-change" in sk.lower():
            raise ValueError("SECRET_KEY must be >= 32 bytes and not a placeholder "
                             "(generate: python -c \"import secrets;print(secrets.token_hex(32))\")")
        if self.minio_password.lower() in self._WEAK or self.minio_user.lower() in self._WEAK:
            raise ValueError("MINIO_USER/MINIO_PASSWORD must be set to non-default values")
        key = self.mavlink_signing_key.strip()
        if key:
            try:
                ok = len(bytes.fromhex(key)) == 32
            except ValueError:
                ok = False
            if not ok:
                raise ValueError("MAVLINK_SIGNING_KEY must be 64 hex characters (32 bytes) "
                                 "(generate: python -c \"import secrets;print(secrets.token_hex(32))\")")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
