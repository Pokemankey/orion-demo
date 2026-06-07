"""
Storage abstraction for document access.

Submissions reference documents by URI. In production those documents live in
object storage (S3 / GCS / Azure Blob) and must be fetched at runtime, because a
serverless function starts with no durable local disk. This module is the single
seam where that fetch happens: the pipeline only ever calls `read_bytes(uri)` and
gets bytes back, so swapping the backend never touches pipeline code.

The demo binds the `file://` (and bare-path) scheme to the local filesystem.
`s3://` is stubbed — the interface is present and the real implementation is
documented inline, but it is not active so the demo runs with no cloud SDKs or
credentials. GCS/Azure would be added the same way: one branch + that SDK.

All parsers downstream accept a file-like object, so callers wrap the returned
bytes in io.BytesIO and never need to touch local disk.
"""
from pathlib import Path
from urllib.parse import urlparse

# Schemes for which read_bytes() actually returns data in the demo.
SUPPORTED_SCHEMES = ("", "file")


def exists(uri: str) -> bool:
    """
    Cheap existence check used during ingestion, before any parsing.
    For local URIs this stats the file; for remote backends it would issue a
    HEAD / metadata request. Stubbed backends report False.
    """
    scheme = urlparse(uri).scheme
    if scheme in SUPPORTED_SCHEMES:
        return Path(_local_path(uri)).exists()
    return False


def read_bytes(uri: str) -> bytes:
    """Fetch a document's raw bytes from storage, dispatching on URI scheme."""
    scheme = urlparse(uri).scheme

    if scheme in SUPPORTED_SCHEMES:
        return Path(_local_path(uri)).read_bytes()

    if scheme == "s3":
        return _read_s3(uri)

    raise ValueError(f"Unsupported storage scheme: {scheme!r} (in {uri!r})")


def _local_path(uri: str) -> str:
    """Strip a leading file:// scheme if present; otherwise treat as a bare path."""
    if uri.startswith("file://"):
        return uri[len("file://"):]
    return uri


def _read_s3(uri: str) -> bytes:
    """
    STUB: production object-storage path, intentionally inactive in the demo.

    Enabling it is a self-contained change — add boto3 to requirements.txt,
    configure AWS credentials, and replace the raise below with:

        import boto3
        parsed = urlparse(uri)                 # s3://<bucket>/<key...>
        bucket, key = parsed.netloc, parsed.path.lstrip("/")
        obj = boto3.client("s3").get_object(Bucket=bucket, Key=key)
        return obj["Body"].read()

    No other pipeline code changes: ingest/parse already go through read_bytes().
    S3-compatible stores (MinIO, Cloudflare R2, Backblaze B2) work through the
    same client by setting endpoint_url. GCS/Azure are added as sibling branches.
    """
    raise NotImplementedError(
        "S3 backend is stubbed in the demo. Install boto3, configure AWS "
        "credentials, and implement _read_s3() to enable object-storage access."
    )
