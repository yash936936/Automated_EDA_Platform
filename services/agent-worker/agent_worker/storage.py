"""
S3-compatible object storage access for the agent worker (Phase 1.1).

Mirrors services/api/src/storage.ts's env vars and MinIO-dev defaults so
both sides of the mixed stack point at the same bucket without duplicating
config in two incompatible ways.
"""
import os
import csv
import hashlib

import boto3
from botocore.config import Config
from dotenv import load_dotenv

load_dotenv()

S3_BUCKET = os.environ.get("S3_BUCKET", "eda-platform-datasets")
_CHUNK_SIZE = 1024 * 1024  # 1MB read chunks -- bounds memory regardless of file size


def get_s3_client():
    return boto3.client(
        "s3",
        endpoint_url=os.environ.get("S3_ENDPOINT", "http://127.0.0.1:8333"),
        aws_access_key_id=os.environ.get("S3_ACCESS_KEY", "devkey"),
        aws_secret_access_key=os.environ.get("S3_SECRET_KEY", "devsecret"),
        region_name=os.environ.get("S3_REGION", "us-east-1"),
        # MinIO needs path-style addressing (bucket.minio.local doesn't
        # resolve); real AWS S3 works with either, so this default is safe
        # to leave as-is even against production S3.
        config=Config(s3={"addressing_style": "path"}),
    )


def ensure_bucket():
    """Idempotent: create the bucket if missing. The API gateway does the same
    at startup; whichever process starts first wins and the other is a no-op."""
    s3 = get_s3_client()
    try:
        s3.head_bucket(Bucket=S3_BUCKET)
        return
    except Exception:
        pass
    try:
        s3.create_bucket(Bucket=S3_BUCKET)
        print(f'Created S3 bucket "{S3_BUCKET}"')
    except Exception as exc:
        if "BucketAlready" in str(exc):
            return  # raced with the API gateway creating it
        print(f'Could not create/verify S3 bucket "{S3_BUCKET}": {exc}')


def tabular_delimiter(filename: str) -> str | None:
    lower = filename.lower()
    if lower.endswith(".tsv"):
        return "\t"
    if lower.endswith(".csv"):
        return ","
    return None


def probe_dataset(storage_key: str, original_filename: str, observer=None) -> dict:
    """
    Streams the object from S3/MinIO exactly once, computing size + sha256
    checksum always, and row/column counts for CSV/TSV files -- without ever
    materializing the whole file in memory. This is the deliberately
    CPU/IO-bound work kept OFF the upload request thread (see
    services/api/src/index.ts's upload route comment) and run here, inside
    the async 'ingest_dataset' job instead.

    Returns: {size_bytes, row_count, column_count, checksum_sha256}
    row_count/column_count are None for non-CSV files in this v1 pass --
    format-specific profiling (Excel, Parquet, JSON) is Phase 2's job, not
    ingestion's.
    """
    s3 = get_s3_client()
    obj = s3.get_object(Bucket=S3_BUCKET, Key=storage_key)
    body = obj["Body"]  # botocore StreamingBody, chunk-iterable

    delimiter = tabular_delimiter(original_filename)
    sha256 = hashlib.sha256()
    size_bytes = 0
    row_count = None
    column_count = None

    if delimiter is not None:
        def hashed_lines():
            # One pass over the bytes: every chunk is hashed for the
            # checksum AND split into decoded lines for csv.reader, rather
            # than hashing the stream once and re-reading it for parsing.
            nonlocal size_bytes
            pending = b""
            for chunk in body.iter_chunks(chunk_size=_CHUNK_SIZE):
                sha256.update(chunk)
                size_bytes += len(chunk)
                pending += chunk
                *complete_lines, pending = pending.split(b"\n")
                for raw_line in complete_lines:
                    yield raw_line.decode("utf-8", errors="replace")
            if pending:
                yield pending.decode("utf-8", errors="replace")

        row_count = 0
        for i, fields in enumerate(csv.reader(hashed_lines(), delimiter=delimiter)):
            if i == 0:
                column_count = len(fields)
                if observer is not None:
                    observer.set_header(fields)
            else:
                row_count += 1
                if observer is not None:
                    observer.add_row(fields)
    else:
        for chunk in body.iter_chunks(chunk_size=_CHUNK_SIZE):
            sha256.update(chunk)
            size_bytes += len(chunk)

    return {
        "size_bytes": size_bytes,
        "row_count": row_count,
        "column_count": column_count,
        "checksum_sha256": sha256.hexdigest(),
    }
