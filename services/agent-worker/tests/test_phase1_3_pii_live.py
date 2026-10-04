"""
Phase 1.3 live tests. Requires: docker compose up -d, migrations 000-004
applied, API + worker (rebuilt/restarted with 1.3) running.

    python -m pytest tests/test_phase1_3_pii_live.py -v
"""
import io
import os
import random
import time

import pytest
import requests
from dotenv import load_dotenv

from agent_worker.pii.scanner import verhoeff_check_digit

load_dotenv()
API = os.environ.get("API_BASE_URL", "http://localhost:4000")


def upload(name, data: bytes, mime="text/csv"):
    r = requests.post(f"{API}/api/datasets/upload", files={"file": (name, io.BytesIO(data), mime)}, timeout=60)
    assert r.status_code == 200, r.text
    return r.json()["datasetId"]


def wait_ready(dataset_id, timeout_s=60):
    """Polls fast and asserts the invariant: a dataset is never 'ready' while its
    PII scan is still 'pending' (both are written in one transaction)."""
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        d = requests.get(f"{API}/api/datasets/{dataset_id}", timeout=10).json()["dataset"]
        assert not (d["status"] == "ready" and d["pii_status"] == "pending"), "ready before PII scan finished"
        if d["status"] in ("ready", "failed"):
            return d
        time.sleep(0.05)
    raise AssertionError("dataset never finished ingesting")


def pii(dataset_id):
    r = requests.get(f"{API}/api/datasets/{dataset_id}/pii", timeout=10)
    assert r.status_code == 200, r.text
    return r.json(), r.text


def aadhaar(rng):
    body = str(rng.randint(2, 9)) + "".join(str(rng.randint(0, 9)) for _ in range(10))
    n = body + verhoeff_check_digit(body)
    return f"{n[:4]} {n[4:8]} {n[8:]}"


def test_clean_csv_produces_zero_findings():
    rng = random.Random(11)
    lines = ["order_id,customer,city,zip,amount,ts,created"]
    for _ in range(2000):
        lines.append(",".join([
            str(rng.randint(10**11, 10**12 - 1)), rng.choice(["Asha Rao", "John Smith", "Li Wei"]),
            rng.choice(["Delhi", "Austin", "Oslo"]), str(rng.randint(100000, 999999)),
            f"{rng.uniform(1, 999):.2f}", str(rng.randint(1_600_000_000, 1_800_000_000)), "2024-05-17",
        ]))
    d = wait_ready(upload("clean.csv", "\n".join(lines).encode()))
    assert d["status"] == "ready" and d["pii_status"] == "scanned" and d["pii_scanned_rows"] == 2000
    body, _ = pii(d["id"])
    assert body["piiStatus"] == "scanned" and body["findings"] == [], body["findings"]


def test_planted_pii_is_flagged_and_raw_values_never_exposed():
    rng = random.Random(5)
    planted = {"emails": [], "phones": [], "aadhaar": [], "pan": [], "ssn": []}
    lines = ["id,email,mobile,aadhaar_no,pan,gov_ref,notes"]
    for i in range(150):
        e = f"person{i}.test@example.com"
        ph = f"+91 {rng.randint(60000, 99999)} {rng.randint(10000, 99999)}"
        a = aadhaar(rng)
        pan = f"ABCPE{rng.randint(1000, 9999)}F"
        ssn = f"{rng.randint(100, 665)}-{rng.randint(10, 99)}-{rng.randint(1000, 9999)}"
        for k, v in zip(planted, (e, ph, a, pan, ssn)):
            planted[k].append(v)
        lines.append(f"{i},{e},{ph},{a},{pan},{ssn},fine")
    d = wait_ready(upload("planted.csv", "\n".join(lines).encode()))
    assert d["pii_status"] == "scanned"
    body, raw = pii(d["id"])
    got = {(f["column_name"], f["detector"]) for f in body["findings"]}
    for key in [("email", "email"), ("mobile", "phone_formatted"), ("aadhaar_no", "aadhaar"),
                ("pan", "pan"), ("gov_ref", "ssn")]:
        assert key in got, f"missing {key}; got {sorted(got)}"
    assert not any(f["column_name"] in ("id", "notes") for f in body["findings"])
    # Privacy: no planted value may appear anywhere in the API response.
    for values in planted.values():
        for v in values:
            assert v not in raw, f"raw PII leaked in /pii response: {v[:4]}..."


def test_non_csv_is_recorded_as_skipped_not_clean():
    d = wait_ready(upload("blob.bin", os.urandom(2048), "application/octet-stream"))
    assert d["pii_status"] == "skipped_unsupported" and d["pii_scanned_rows"] is None
    body, _ = pii(d["id"])
    assert body["piiStatus"] == "skipped_unsupported" and body["findings"] == []


@pytest.mark.skipif(not os.environ.get("KAGGLE_API_TOKEN"), reason="needs KAGGLE_API_TOKEN")
def test_kaggle_imported_dataset_is_also_scanned():
    ref = "uciml/iris"
    files = requests.get(f"{API}/api/discovery/files", params={"ref": ref}, timeout=90).json()
    name = next(f["name"] for f in files["files"] if f["tabular"])
    r = requests.post(f"{API}/api/discovery/import", json={"ref": ref, "fileName": name}, timeout=30).json()
    d = wait_ready(r["datasetId"], timeout_s=120)
    assert d["status"] == "ready" and d["pii_status"] == "scanned"
