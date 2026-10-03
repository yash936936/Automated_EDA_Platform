"""
Phase 1.2 live tests. Requires the full stack (docker compose up -d, API,
worker) with migrations 000-003 applied. Kaggle-dependent tests also need
KAGGLE_API_TOKEN in .env and are skipped (loudly) without it.

    python -m pytest tests/test_phase1_2_live.py -v
"""
import os
import time

import pytest
import requests
from dotenv import load_dotenv

load_dotenv()
API = os.environ.get("API_BASE_URL", "http://localhost:4000")
needs_kaggle = pytest.mark.skipif(
    not os.environ.get("KAGGLE_API_TOKEN"),
    reason="KAGGLE_API_TOKEN not set in .env -- Kaggle-backed tests skipped",
)


def _poll(dataset_id, timeout_s=180):
    deadline, last = time.time() + timeout_s, None
    while time.time() < deadline:
        last = requests.get(f"{API}/api/datasets/{dataset_id}", timeout=10).json()["dataset"]
        if last["status"] in ("ready", "failed"):
            return last
        time.sleep(1)
    raise AssertionError(f"dataset {dataset_id} stuck in 'ingesting', last={last}")


def test_import_input_validation_needs_no_kaggle():
    bad = [
        {"ref": "nope", "fileName": "a.csv"},
        {"ref": "o/d", "fileName": "model.pkl"},
        {"ref": "o/d", "fileName": "../etc/passwd.csv"},
        {"ref": "o/d", "fileName": "/abs.csv"},
    ]
    for body in bad:
        r = requests.post(f"{API}/api/discovery/import", json=body, timeout=10)
        assert r.status_code == 400, (body, r.text)
    assert requests.get(f"{API}/api/discovery/search?q=a", timeout=10).status_code == 400
    assert requests.get(f"{API}/api/discovery/files?ref=bad", timeout=10).status_code == 400


@needs_kaggle
def test_search_returns_results_and_repeat_hits_cache():
    q = f"customer churn telecom"
    t0 = time.time()
    first = requests.get(f"{API}/api/discovery/search", params={"q": q}, timeout=90).json()
    t_first = time.time() - t0
    assert first["ok"], first
    assert first["results"], "no results for a very common query"
    assert {"ref", "title", "license", "downloads"} <= set(first["results"][0])

    t0 = time.time()
    second = requests.get(f"{API}/api/discovery/search", params={"q": q.upper() + "  "}, timeout=90).json()
    t_second = time.time() - t0
    assert second["cacheHit"] is True, "second identical query did not hit the cache"
    assert [r["ref"] for r in second["results"]] == [r["ref"] for r in first["results"]]
    print(f"\nfirst={t_first:.2f}s (cacheHit={first['cacheHit']}, expansion={first['expansion']}) second={t_second:.2f}s")


@needs_kaggle
def test_import_small_public_dataset_end_to_end():
    ref = "uciml/iris"  # tiny, long-standing public dataset
    files = requests.get(f"{API}/api/discovery/files", params={"ref": ref}, timeout=90).json()
    assert files["ok"], files
    tabular = [f for f in files["files"] if f["tabular"]]
    assert tabular, files
    name = next((f["name"] for f in tabular if f["name"].lower() == "iris.csv"), tabular[0]["name"])

    r = requests.post(f"{API}/api/discovery/import", json={"ref": ref, "fileName": name}, timeout=30)
    assert r.status_code in (200, 202), r.text
    dataset_id = r.json()["datasetId"]

    d = _poll(dataset_id)
    assert d["status"] == "ready", d.get("error_message")
    assert d["source"] == "kaggle" and d["source_ref"] == ref
    assert d["row_count"] > 0 and d["column_count"] > 1 and d["checksum_sha256"]

    again = requests.post(f"{API}/api/discovery/import", json={"ref": ref, "fileName": name}, timeout=30).json()
    assert again["deduped"] is True and again["datasetId"] == dataset_id


@needs_kaggle
def test_import_nonexistent_file_fails_cleanly_not_stuck():
    r = requests.post(f"{API}/api/discovery/import",
                      json={"ref": "uciml/iris", "fileName": "definitely_not_here.csv"}, timeout=30)
    assert r.status_code == 202, r.text
    d = _poll(r.json()["datasetId"], timeout_s=60)
    assert d["status"] == "failed" and "not found" in (d["error_message"] or "")
