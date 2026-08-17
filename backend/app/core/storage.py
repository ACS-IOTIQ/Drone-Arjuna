"""
MinIO / S3 object storage client — Drone Analyst source imagery.

boto3 has no native asyncio API, so every call is offloaded to a thread
via asyncio.to_thread — the same pattern FastAPI itself uses for sync
dependencies. Callers always await these functions.

Bucket: da-analyst-imagery (created on first use if missing).
"""
import asyncio
import uuid
import structlog
import boto3
from botocore.exceptions import ClientError

from app.config import get_settings

log = structlog.get_logger()

BUCKET_NAME = "da-analyst-imagery"

# Artifact kinds permitted in the Analyst pipeline, and the content-type
# prefixes/values that map to each. Anything outside these is rejected —
# this bucket is for source imagery, generated video, and PDF reports only.
KIND_IMAGE = "image"
KIND_VIDEO = "video"
KIND_REPORT_PDF = "report_pdf"

ALLOWED_KINDS = {KIND_IMAGE, KIND_VIDEO, KIND_REPORT_PDF}


def classify_content_type(content_type: str) -> str:
    """
    Maps a MIME content type to an artifact kind (image/video/report_pdf).
    Raises ValueError if the content type isn't one of the types this
    pipeline stores.
    """
    ct = (content_type or "").lower()
    if ct == "application/pdf":
        return KIND_REPORT_PDF
    if ct.startswith("image/"):
        return KIND_IMAGE
    if ct.startswith("video/"):
        return KIND_VIDEO
    raise ValueError(
        f"Unsupported content type '{content_type}' — only images, videos, "
        "and PDF reports may be stored"
    )


_client = None


def _get_client():
    global _client
    if _client is None:
        cfg = get_settings()
        _client = boto3.client(
            "s3",
            endpoint_url=f"{'https' if cfg.minio_secure else 'http'}://{cfg.minio_endpoint}",
            aws_access_key_id=cfg.minio_user,
            aws_secret_access_key=cfg.minio_password,
        )
    return _client


async def ensure_bucket() -> None:
    """Create the analyst imagery bucket if it doesn't already exist."""
    def _ensure():
        client = _get_client()
        try:
            client.head_bucket(Bucket=BUCKET_NAME)
        except ClientError:
            client.create_bucket(Bucket=BUCKET_NAME)

    await asyncio.to_thread(_ensure)


def build_object_key(job_id: str, filename: str) -> str:
    """
    Deterministic, collision-resistant object key for a job's source image.
    Layout: jobs/{job_id}/{uuid4}_{original_filename}
    """
    safe_name = filename.replace("/", "_").replace("\\", "_")
    return f"jobs/{job_id}/{uuid.uuid4().hex}_{safe_name}"


async def upload_bytes(object_key: str, data: bytes, content_type: str = "application/octet-stream") -> None:
    """Upload raw bytes to the analyst imagery bucket under object_key."""
    def _put():
        _get_client().put_object(
            Bucket=BUCKET_NAME,
            Key=object_key,
            Body=data,
            ContentType=content_type,
        )

    await asyncio.to_thread(_put)


async def get_presigned_url(object_key: str, expires_seconds: int = 3600) -> str:
    """Generate a time-limited GET URL for an object, for UI download/preview."""
    def _presign():
        return _get_client().generate_presigned_url(
            "get_object",
            Params={"Bucket": BUCKET_NAME, "Key": object_key},
            ExpiresIn=expires_seconds,
        )

    return await asyncio.to_thread(_presign)


async def delete_object(object_key: str) -> None:
    def _delete():
        _get_client().delete_object(Bucket=BUCKET_NAME, Key=object_key)

    await asyncio.to_thread(_delete)
