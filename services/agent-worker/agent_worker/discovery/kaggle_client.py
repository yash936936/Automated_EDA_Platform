"""
Thin, mockable wrapper around the Kaggle SDK (kaggle>=2, auth via the
KAGGLE_API_TOKEN env var). Everything Kaggle-specific lives here so the rest
of Agent 1 (and the tests) never touch the SDK directly.

The SDK is imported lazily and authenticated explicitly: importing it with no
credentials can print instructions and even sys.exit() in some versions, which
must never take down the whole worker process at import time.
"""
import shutil
import zipfile
from pathlib import Path


class KaggleError(RuntimeError):
    pass


_api_singleton = None


def _api():
    global _api_singleton
    if _api_singleton is not None:
        return _api_singleton
    try:
        from kaggle.api.kaggle_api_extended import KaggleApi

        api = KaggleApi()
        api.authenticate()
    except (Exception, SystemExit) as exc:  # SystemExit: SDK may exit on missing creds
        raise KaggleError(
            "Kaggle authentication failed. Set KAGGLE_API_TOKEN in .env "
            "(generate one at https://www.kaggle.com/settings/api) and restart the worker."
        ) from exc
    _api_singleton = api
    return api


def _norm(d) -> dict:
    return {
        "ref": str(getattr(d, "ref", "") or ""),
        "title": str(getattr(d, "title", "") or ""),
        "subtitle": str(getattr(d, "subtitle", "") or ""),
        "sizeBytes": int(getattr(d, "total_bytes", 0) or 0),
        "downloads": int(getattr(d, "download_count", 0) or 0),
        "votes": int(getattr(d, "vote_count", 0) or 0),
        "usability": float(getattr(d, "usability_rating", 0) or 0),
        "license": str(getattr(d, "license_name", "") or ""),
        "lastUpdated": str(getattr(d, "last_updated", "") or ""),
        "url": str(getattr(d, "url", "") or ""),
    }


def search_datasets(query: str, *, file_type: str = "csv", page: int = 1) -> list[dict]:
    try:
        items = _api().dataset_list(search=query, file_type=file_type, page=page) or []
    except KaggleError:
        raise
    except Exception as exc:
        raise KaggleError(f"Kaggle search failed: {exc}") from exc
    return [_norm(d) for d in items if d is not None and getattr(d, "ref", None)]


def list_files(ref: str, *, max_pages: int = 5) -> list[dict]:
    api = _api()
    files, token = [], None
    try:
        for _ in range(max_pages):
            resp = api.dataset_list_files(ref, page_token=token, page_size=100)
            files += [
                {"name": str(f.name), "sizeBytes": int(f.total_bytes or 0)}
                for f in (getattr(resp, "files", None) or [])
            ]
            token = getattr(resp, "next_page_token", None)
            if not token:
                break
    except Exception as exc:
        raise KaggleError(f"Kaggle file listing failed for {ref}: {exc}") from exc
    return files


def download_file(ref: str, file_name: str, dest_dir: str, *, max_bytes: int | None = None) -> Path:
    """Download ONE file (not the whole dataset zip). Depending on SDK/server
    behavior the result lands as the file itself or as '<file>.zip'; both are
    handled, and the zip case extracts only the expected member."""
    dest = Path(dest_dir)
    base = Path(file_name).name
    try:
        _api().dataset_download_file(ref, file_name, path=str(dest), force=True, quiet=True)
    except KaggleError:
        raise
    except Exception as exc:
        raise KaggleError(f"Kaggle download failed for {ref}/{file_name}: {exc}") from exc

    direct = dest / base
    if direct.is_file():
        return direct
    zipped = dest / (base + ".zip")
    if zipped.is_file():
        with zipfile.ZipFile(zipped) as zf:
            member = next((i for i in zf.infolist() if Path(i.filename).name == base), None)
            if member is None:
                raise KaggleError(f"{zipped.name} did not contain {base}")
            if max_bytes is not None and member.file_size > max_bytes:
                raise KaggleError(f"{base} expands to {member.file_size} bytes, over the import cap")
            # Write to a fixed path built from the basename (no zip-slip).
            with zf.open(member) as src, open(direct, "wb") as out:
                shutil.copyfileobj(src, out)
        zipped.unlink()
        return direct
    raise KaggleError(f"download of {ref}/{file_name} produced no usable file in {dest}")
