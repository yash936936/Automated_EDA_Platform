"""
Phase 1.1 automated smoke suite -- file upload path. Requires:
  - docker compose up -d (redis + postgres + minio + createbuckets)
  - node dist/index.js running (API on :4000)
  - python -m agent_worker.worker running (consumer on agent.eda_clean)
  - migrations 000-002 already applied to the eda_platform DB

Run from services/agent-worker/:
    python -m pytest tests/test_phase1_1_upload.py -v

The 500MB stress-file test is opt-in (RUN_LARGE_UPLOAD_TEST=1) since it's
slow and disk/bandwidth-heavy -- not something to run on every CI push, but
it is what the phase's actual passing criteria asks for, so it isn't skipped
by default silently; it's skipped loudly with a reason.
"""
import io
import os
import time
import uuid

import psycopg2
import pytest
import requests
from dotenv import load_dotenv

load_dotenv()

API = os.environ.get("API_BASE_URL", "http://localhost:4000")
PG = dict(
    host=os.environ.get("PGHOST", "127.0.0.1"),
    port=os.environ.get("PGPORT", "5433"),
    dbname=os.environ.get("PGDATABASE", "eda_platform"),
    user=os.environ.get("PGUSER", "postgres"),
    password=os.environ.get("PGPASSWORD", "postgres"),
)


@pytest.fixture
def conn():
    c = psycopg2.connect(**PG)
    yield c
    c.close()


def _poll_dataset(dataset_id, timeout_s=30):
    deadline = time.time() + timeout_s
    last = None
    while time.time() < deadline:
        r = requests.get(f"{API}/api/datasets/{dataset_id}", timeout=10).json()
        assert r["ok"], r
        last = r["dataset"]
        if last["status"] in ("ready", "failed"):
            return last
        time.sleep(0.5)
    raise AssertionError(f"dataset {dataset_id} never left 'ingesting', last={last}")


def test_1_1_small_csv_upload_and_ingest():
    csv_bytes = b"a,b,c\n1,2,3\n4,5,6\n7,8,9\n"
    files = {"file": ("smoke_test.csv", io.BytesIO(csv_bytes), "text/csv")}

    r = requests.post(f"{API}/api/datasets/upload", files=files, timeout=30)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    dataset_id = body["datasetId"]

    # The upload response itself must not already carry final metadata --
    # that would mean it was computed synchronously on the request thread,
    # not handed to the queue.
    assert body["status"] == "ingesting"

    dataset = _poll_dataset(dataset_id)
    assert dataset["status"] == "ready", dataset.get("error_message")
    assert dataset["row_count"] == 3          # header excluded
    assert dataset["column_count"] == 3
    assert dataset["size_bytes"] == len(csv_bytes)
    assert dataset["checksum_sha256"] is not None


def test_1_1_non_csv_file_still_ingests():
    # Non-CSV files should still land as 'ready' with size+checksum even
    # though row/column counting is deliberately skipped for them (v1 scope).
    payload = os.urandom(4096)
    files = {"file": ("blob.bin", io.BytesIO(payload), "application/octet-stream")}

    r = requests.post(f"{API}/api/datasets/upload", files=files, timeout=30)
    assert r.status_code == 200, r.text
    dataset_id = r.json()["datasetId"]

    dataset = _poll_dataset(dataset_id)
    assert dataset["status"] == "ready"
    assert dataset["size_bytes"] == len(payload)
    assert dataset["row_count"] is None
    assert dataset["column_count"] is None


@pytest.mark.skipif(
    os.environ.get("RUN_LARGE_UPLOAD_TEST") != "1",
    reason="opt-in: generates/uploads a ~500MB file. Set RUN_LARGE_UPLOAD_TEST=1 to run.",
)
def test_1_1_large_file_does_not_block_event_loop():
    """
    Passing criteria (docs/phases.md 1.1): 'the large file doesn't block the
    request thread'. Verified here by firing a large upload and, WHILE it is
    still in flight, hitting a cheap unrelated endpoint and asserting it
    responds quickly -- if the upload were blocking Node's event loop, the
    concurrent request would stall behind it.
    """
    import tempfile
    import threading

    from requests_toolbelt import MultipartEncoder

    size = 500 * 1024 * 1024  # 500MB
    chunk = os.urandom(1024 * 1024)
    result = {}

    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".bin")
    try:
        for _ in range(size // len(chunk)):
            tmp.write(chunk)
        tmp.close()

        def do_upload():
            # MultipartEncoder streams from disk; plain requests(files=...)
            # would build the whole 500MB body in memory first.
            with open(tmp.name, "rb") as fh:
                enc = MultipartEncoder(
                    fields={"file": ("stress.bin", fh, "application/octet-stream")}
                )
                try:
                    result["response"] = requests.post(
                        f"{API}/api/datasets/upload",
                        data=enc,
                        headers={"Content-Type": enc.content_type},
                        timeout=600,
                    )
                except Exception as exc:
                    result["error"] = repr(exc)

        upload_thread = threading.Thread(target=do_upload)
        upload_thread.start()
        time.sleep(1.5)  # let the upload get underway

        t0 = time.time()
        ping = requests.get(f"{API}/api/datasets", timeout=5)
        concurrent_latency = time.time() - t0
        assert ping.status_code == 200
        assert concurrent_latency < 2.0, (
            f"a concurrent lightweight request took {concurrent_latency:.2f}s while a large "
            f"upload was in flight -- suggests the event loop is blocked, not just I/O-waiting"
        )

        upload_thread.join(timeout=600)
        assert "response" in result, f"upload failed: {result.get('error')}"
        body = result["response"].json()
        assert body["ok"] is True, body

        dataset = _poll_dataset(body["datasetId"], timeout_s=180)
        assert dataset["status"] == "ready", dataset.get("error_message")
        assert dataset["size_bytes"] == size
    finally:
        try:
            os.unlink(tmp.name)
        except OSError:
            pass
