"""
MinIO / S3 Storage Helper Tests
================================
Unit tests for app/core/storage.py in isolation from the Analyst module.
The boto3 S3 client is fully mocked — no live MinIO/network access.

Covers:
  - build_object_key() produces the jobs/{job_id}/{uuid}_{filename} layout
    and sanitizes path separators
  - ensure_bucket() creates the bucket only when head_bucket fails
  - ensure_bucket() is a no-op (no create_bucket call) when the bucket exists
  - upload_bytes() calls put_object with the right bucket/key/body/content-type
  - get_presigned_url() calls generate_presigned_url with the right params
  - delete_object() calls delete_object with the right bucket/key
  - _get_client() is a lazy singleton — boto3.client constructed only once
"""
import pytest
from unittest.mock import MagicMock, patch
from botocore.exceptions import ClientError

import app.core.storage as storage


@pytest.fixture(autouse=True)
def _reset_client_singleton():
    """Each test gets a fresh lazy client so mocks don't leak across tests."""
    original = storage._client
    storage._client = None
    yield
    storage._client = original


def _client_error():
    return ClientError({"Error": {"Code": "404", "Message": "Not Found"}}, "HeadBucket")


# ══════════════════════════════════════════════════════════════════════
# classify_content_type
# ══════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("content_type,expected_kind", [
    ("image/jpeg", storage.KIND_IMAGE),
    ("image/png", storage.KIND_IMAGE),
    ("IMAGE/PNG", storage.KIND_IMAGE),
    ("video/mp4", storage.KIND_VIDEO),
    ("video/quicktime", storage.KIND_VIDEO),
    ("application/pdf", storage.KIND_REPORT_PDF),
    ("Application/PDF", storage.KIND_REPORT_PDF),
])
def test_classify_content_type_recognized(content_type, expected_kind):
    assert storage.classify_content_type(content_type) == expected_kind


@pytest.mark.parametrize("content_type", [
    "text/plain",
    "application/json",
    "application/zip",
    "",
])
def test_classify_content_type_rejects_unsupported(content_type):
    with pytest.raises(ValueError):
        storage.classify_content_type(content_type)


def test_allowed_kinds_matches_classifier_outputs():
    assert storage.ALLOWED_KINDS == {
        storage.KIND_IMAGE, storage.KIND_VIDEO, storage.KIND_REPORT_PDF
    }


# ══════════════════════════════════════════════════════════════════════
# build_object_key
# ══════════════════════════════════════════════════════════════════════

def test_build_object_key_layout():
    key = storage.build_object_key("job-123", "photo.jpg")
    assert key.startswith("jobs/job-123/")
    assert key.endswith("_photo.jpg")


def test_build_object_key_is_unique_per_call():
    k1 = storage.build_object_key("job-123", "photo.jpg")
    k2 = storage.build_object_key("job-123", "photo.jpg")
    assert k1 != k2


def test_build_object_key_sanitizes_forward_slashes():
    key = storage.build_object_key("job-123", "a/b/c.jpg")
    assert key.startswith("jobs/job-123/")
    # Everything after the job prefix must not reintroduce extra path segments
    suffix = key[len("jobs/job-123/"):]
    assert "/" not in suffix


def test_build_object_key_sanitizes_backslashes():
    key = storage.build_object_key("job-123", "a\\b\\c.jpg")
    suffix = key[len("jobs/job-123/"):]
    assert "\\" not in suffix


# ══════════════════════════════════════════════════════════════════════
# _get_client — lazy singleton
# ══════════════════════════════════════════════════════════════════════

def test_get_client_constructs_once():
    with patch("app.core.storage.boto3.client") as mock_boto:
        mock_boto.return_value = MagicMock()
        c1 = storage._get_client()
        c2 = storage._get_client()
    assert c1 is c2
    mock_boto.assert_called_once()


def test_get_client_uses_configured_endpoint():
    with patch("app.core.storage.boto3.client") as mock_boto:
        mock_boto.return_value = MagicMock()
        storage._get_client()
    _, kwargs = mock_boto.call_args
    assert kwargs["endpoint_url"].endswith(":9000") or "minio" in kwargs["endpoint_url"]
    assert "aws_access_key_id" in kwargs
    assert "aws_secret_access_key" in kwargs


# ══════════════════════════════════════════════════════════════════════
# ensure_bucket
# ══════════════════════════════════════════════════════════════════════

async def test_ensure_bucket_creates_when_missing():
    mock_client = MagicMock()
    mock_client.head_bucket.side_effect = _client_error()

    with patch("app.core.storage._get_client", return_value=mock_client):
        await storage.ensure_bucket()

    mock_client.head_bucket.assert_called_once_with(Bucket=storage.BUCKET_NAME)
    mock_client.create_bucket.assert_called_once_with(Bucket=storage.BUCKET_NAME)


async def test_ensure_bucket_noop_when_exists():
    mock_client = MagicMock()
    mock_client.head_bucket.return_value = {}

    with patch("app.core.storage._get_client", return_value=mock_client):
        await storage.ensure_bucket()

    mock_client.head_bucket.assert_called_once_with(Bucket=storage.BUCKET_NAME)
    mock_client.create_bucket.assert_not_called()


# ══════════════════════════════════════════════════════════════════════
# upload_bytes
# ══════════════════════════════════════════════════════════════════════

async def test_upload_bytes_calls_put_object_with_correct_args():
    mock_client = MagicMock()

    with patch("app.core.storage._get_client", return_value=mock_client):
        await storage.upload_bytes("jobs/abc/img.jpg", b"binarydata", "image/jpeg")

    mock_client.put_object.assert_called_once_with(
        Bucket=storage.BUCKET_NAME,
        Key="jobs/abc/img.jpg",
        Body=b"binarydata",
        ContentType="image/jpeg",
    )


async def test_upload_bytes_defaults_content_type():
    mock_client = MagicMock()

    with patch("app.core.storage._get_client", return_value=mock_client):
        await storage.upload_bytes("jobs/abc/img.bin", b"data")

    assert mock_client.put_object.call_args.kwargs["ContentType"] == "application/octet-stream"


# ══════════════════════════════════════════════════════════════════════
# get_presigned_url
# ══════════════════════════════════════════════════════════════════════

async def test_get_presigned_url_calls_generate_presigned_url():
    mock_client = MagicMock()
    mock_client.generate_presigned_url.return_value = "http://minio.local/signed"

    with patch("app.core.storage._get_client", return_value=mock_client):
        url = await storage.get_presigned_url("jobs/abc/img.jpg", expires_seconds=120)

    assert url == "http://minio.local/signed"
    mock_client.generate_presigned_url.assert_called_once_with(
        "get_object",
        Params={"Bucket": storage.BUCKET_NAME, "Key": "jobs/abc/img.jpg"},
        ExpiresIn=120,
    )


async def test_get_presigned_url_default_expiry():
    mock_client = MagicMock()
    mock_client.generate_presigned_url.return_value = "http://minio.local/signed"

    with patch("app.core.storage._get_client", return_value=mock_client):
        await storage.get_presigned_url("jobs/abc/img.jpg")

    assert mock_client.generate_presigned_url.call_args.kwargs["ExpiresIn"] == 3600


# ══════════════════════════════════════════════════════════════════════
# delete_object
# ══════════════════════════════════════════════════════════════════════

async def test_delete_object_calls_delete_object():
    mock_client = MagicMock()

    with patch("app.core.storage._get_client", return_value=mock_client):
        await storage.delete_object("jobs/abc/img.jpg")

    mock_client.delete_object.assert_called_once_with(
        Bucket=storage.BUCKET_NAME, Key="jobs/abc/img.jpg"
    )
