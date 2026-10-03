"""Agent 1 import: validate a chosen Kaggle file, download just that file, and
stream it into the same object storage the upload path uses. The caller (the
worker) owns the datasets row and enqueues the shared 'ingest_dataset' job."""
import mimetypes
import os
import re
import tempfile
from pathlib import PurePosixPath

from agent_worker import storage
from . import kaggle_client

TABULAR_EXT = (".csv", ".tsv")
REF_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")


class ImportRejected(ValueError):
    """User-facing reason an import can't proceed (bad ref, wrong type, too big)."""


def max_import_bytes() -> int:
    return int(float(os.environ.get("KAGGLE_MAX_IMPORT_MB", "1024")) * 1024 * 1024)


def validate_ref(ref: str) -> None:
    if not isinstance(ref, str) or not REF_RE.match(ref):
        raise ImportRejected(f"invalid Kaggle dataset ref {ref!r}; expected 'owner/dataset-name'")


def validate_file(ref: str, file_name: str, max_bytes: int | None = None) -> dict:
    """The file must exactly match an entry in Kaggle's own listing (so a
    client can't make us fetch arbitrary names), be tabular, and be under the cap."""
    validate_ref(ref)
    max_bytes = max_bytes if max_bytes is not None else max_import_bytes()
    if not file_name.lower().endswith(TABULAR_EXT):
        raise ImportRejected(f"{file_name!r} is not a CSV/TSV file (v1 imports tabular text files only)")
    match = next((f for f in kaggle_client.list_files(ref) if f["name"] == file_name), None)
    if match is None:
        raise ImportRejected(f"{file_name!r} not found in dataset {ref}")
    if match["sizeBytes"] > max_bytes:
        raise ImportRejected(
            f"{file_name!r} is {match['sizeBytes'] / 1e6:.0f} MB, over the {max_bytes / 1e6:.0f} MB import cap "
            "(raise KAGGLE_MAX_IMPORT_MB if intended)"
        )
    return match


def storage_basename(file_name: str) -> str:
    return PurePosixPath(file_name).name


def download_to_storage(ref: str, file_name: str, storage_key: str, *, max_bytes: int | None = None, s3=None) -> int:
    max_bytes = max_bytes if max_bytes is not None else max_import_bytes()
    s3 = s3 or storage.get_s3_client()
    with tempfile.TemporaryDirectory(prefix="kaggle_import_") as tmp:
        path = kaggle_client.download_file(ref, file_name, tmp, max_bytes=max_bytes)
        size = path.stat().st_size
        if size > max_bytes:
            raise ImportRejected(f"downloaded file is {size} bytes, over the import cap")
        ctype = mimetypes.guess_type(path.name)[0] or "text/csv"
        # upload_file streams from disk with managed multipart; no whole-file RAM copy.
        s3.upload_file(str(path), storage.S3_BUCKET, storage_key, ExtraArgs={"ContentType": ctype})
    return size
