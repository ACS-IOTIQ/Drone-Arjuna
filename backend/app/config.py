from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import field_validator
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
    access_token_expire_minutes: int = 60
    refresh_token_expire_days: int = 7
    algorithm: str = "HS256"

    # CORS — stored as comma-separated string, parsed into list below
    allowed_origins_str: str = "http://localhost:8080,http://localhost:3000,http://localhost:5173,http://127.0.0.1:8080,http://127.0.0.1:3000"

    @property
    def allowed_origins(self) -> list[str]:
        return [o.strip() for o in self.allowed_origins_str.split(",")]

    # MinIO / S3
    minio_endpoint: str = "minio:9000"
    minio_user: str = "da_minio"
    minio_password: str = "changeme123"
    minio_secure: bool = False

    # MAVLink SITL defaults
    sitl_host: str = "host.docker.internal"
    sitl_port: int = 14550


@lru_cache
def get_settings() -> Settings:
    return Settings()