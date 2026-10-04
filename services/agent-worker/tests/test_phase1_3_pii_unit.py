"""
Phase 1.3 PII scanner unit tests -- no Docker/Postgres needed (moto for S3).
Live wiring is covered by tests/test_phase1_3_pii_live.py.
"""
import csv
import hashlib
import io
import random

import boto3
import pytest
from moto import mock_aws

from agent_worker import storage
from agent_worker.pii.scanner import (
    FLAG_THRESHOLD, PiiNotScanned, PiiScanner, detect, require_pii_scanned,
    verhoeff_check_digit, verhoeff_valid,
)


def aadhaar(rng, formatted=False):
    body = str(rng.randint(2, 9)) + "".join(str(rng.randint(0, 9)) for _ in range(10))
    n = body + verhoeff_check_digit(body)
    return f"{n[:4]} {n[4:8]} {n[8:]}" if formatted else n


# ---------------- detectors ----------------
@pytest.mark.parametrize("value,expected", [
    ("jane.doe@example.com", "email"),
    ("Contact: bob+tag@sub.mail.co.uk please", "email"),
    ("+91 98765 43210", "phone_formatted"),
    ("+44 20 7946 0958", "phone_formatted"),
    ("(415) 555-2671", "phone_formatted"),
    ("415-555-2671", "phone_formatted"),
    ("98765 43210", "phone_formatted"),
    ("9876543210", "phone_bare"),
    ("+919876543210", "phone_formatted"),   # leading + is strong phone evidence
    ("09876543210", "phone_bare"),
    ("ABCPE1234F", "pan"),
    ("123-45-6789", "ssn"),
])
def test_positive_detections(value, expected):
    assert expected in detect(value)


@pytest.mark.parametrize("value", [
    "hello world", "2021-01-15", "2021-01-15T10:22:31Z", "12.50", "1,234,567", "SKU-99812-A",
    "logo@2x.png", "not an email @ all", "110001", "1234567890123", "1700000000",
    "000-12-3456", "666-12-3456", "900-12-3456", "123-00-4567", "123-45-0000",   # invalid SSN ranges
    "ABCZE1234F",            # PAN with invalid holder-type letter
    "1234 5678 9012",        # starts with 1: not a valid Aadhaar
    "2345 6789 0123",        # fails Verhoeff checksum
    "5551234", "100-200-3000",
])
def test_negative_detections(value):
    assert detect(value) == [], value


def test_verhoeff_roundtrip_and_tamper():
    rng = random.Random(1)
    for _ in range(50):
        a = aadhaar(rng)
        assert verhoeff_valid(a)
        tampered = a[:-1] + str((int(a[-1]) + 1) % 10)
        assert not verhoeff_valid(tampered)


# ---------------- scanner: planted vs clean ----------------
def run(rows, header, **kw):
    sc = PiiScanner(**kw)
    sc.set_header(header)
    for r in rows:
        sc.add_row(r)
    return sc


def test_planted_pii_is_flagged_per_column_and_type():
    rng = random.Random(7)
    header = ["id", "email", "mobile", "aadhaar_no", "pan", "gov_ref", "notes"]
    rows = []
    for i in range(200):
        rows.append([
            str(i), f"user{i}@example.com", f"+91 {rng.randint(60000, 99999)} {rng.randint(10000, 99999)}",
            aadhaar(rng, formatted=True), f"ABCPE{rng.randint(1000, 9999)}F",
            f"{rng.randint(100, 665)}-{rng.randint(10, 99)}-{rng.randint(1000, 9999)}", "ok",
        ])
    found = {(f.column_name, f.detector): f for f in run(rows, header).findings()}
    for key in [("email", "email"), ("mobile", "phone_formatted"), ("aadhaar_no", "aadhaar"),
                ("pan", "pan"), ("gov_ref", "ssn")]:
        assert key in found, f"missing {key}; got {sorted(found)}"
        assert found[key].match_rate == 1.0
    assert all(f.column_name not in ("id", "notes") for f in found.values())
    # Full-coverage columns of precise detectors should clear the Phase 3.2 auto-mask bar (0.90).
    assert found[("email", "email")].confidence >= 0.90
    assert found[("aadhaar_no", "aadhaar")].confidence >= 0.90
    assert found[("pan", "pan")].confidence >= 0.90
    # Formatted SSN with no header hint is weaker evidence -> flagged for human review, not auto-mask grade.
    assert FLAG_THRESHOLD <= found[("gov_ref", "ssn")].confidence < 0.90


def test_single_planted_hit_is_flagged_but_not_mask_grade():
    rows = [[f"note {i}"] for i in range(500)]
    rows[250] = ["reach me at someone@example.org tomorrow"]
    (f,) = run(rows, ["comments"]).findings()
    assert f.detector == "email" and f.match_count == 1
    assert FLAG_THRESHOLD <= f.confidence < 0.90


def test_clean_adversarial_dataset_has_zero_findings():
    rng = random.Random(42)
    header = ["order_id", "customer", "city", "zip", "amount", "order_ts", "created", "phone_ext", "sku", "tracking", "flag"]
    cities = ["Delhi", "Mumbai", "Austin", "Leeds", "Pune", "Oslo"]
    rows = []
    for i in range(5000):
        rows.append([
            str(rng.randint(10**11, 10**12 - 1)),                  # random 12-digit IDs (Verhoeff passes ~10%)
            rng.choice(["Asha Rao", "John Smith", "Li Wei", "Maria Garcia"]),
            rng.choice(cities), str(rng.randint(100000, 999999)),
            f"{rng.uniform(1, 9999):.2f}", str(rng.randint(1_600_000_000, 1_800_000_000)),
            f"20{rng.randint(10, 25)}-{rng.randint(1, 12):02d}-{rng.randint(1, 28):02d}",
            str(rng.randint(100, 9999)), f"SKU-{rng.randint(10000, 99999)}-{rng.choice('ABC')}",
            str(rng.randint(10**9, 10**10 - 1)),                    # random 10-digit numbers
            rng.choice(["Y", "N", ""]),
        ])
    assert run(rows, header).findings() == []


def test_header_hint_lowers_bar_for_bare_numbers_and_boosts_confidence():
    rng = random.Random(3)
    bare = [[str(rng.randint(6, 9)) + "".join(str(rng.randint(0, 9)) for _ in range(9))] for _ in range(100)]
    # 30% of values are bare mobiles: below the 0.5 rate floor without a hint...
    mixed = bare[:30] + [["n/a"] for _ in range(70)]
    assert run(mixed, ["ref"]).findings() == []
    hinted = run(mixed, ["phone_number"]).findings()
    assert len(hinted) == 1 and hinted[0].header_hint and hinted[0].detector == "phone_bare"


def test_header_hint_lifts_ssn_column_to_mask_grade():
    rows = [[f"{100 + i % 500}-{10 + i % 80}-{1000 + i}"] for i in range(100)]
    plain = run(rows, ["gov_ref"]).findings()[0].confidence
    hinted = run(rows, ["ssn"]).findings()[0].confidence
    assert plain < 0.90 <= hinted


def test_row_cap_is_recorded_not_hidden():
    rows = [["a@b.com"] for _ in range(50)]
    sc = run(rows, ["email"], max_rows=10)
    assert sc.rows_scanned == 10 and sc.rows_seen == 50 and sc.truncated is True
    assert sc.findings()[0].scanned_values == 10


def test_findings_never_contain_raw_values():
    rows = [[f"secret{i}@example.com"] for i in range(20)]
    blob = repr(run(rows, ["email"]).findings())
    assert "secret" not in blob and "@example.com" not in blob


def test_bom_and_ragged_rows_are_tolerated():
    sc = PiiScanner()
    sc.set_header(["\ufeffe-mail", "x"])
    sc.add_row(["a@b.com"])          # ragged: fewer cells than header
    sc.add_row(["c@d.org", "y", "extra"])
    (f,) = sc.findings()
    assert f.column_name == "e-mail" and f.header_hint is True


# ---------------- integration with the single ingest pass (moto S3) ----------------
@mock_aws
def test_probe_feeds_scanner_without_changing_metadata():
    c = boto3.client("s3", region_name="us-east-1")
    c.create_bucket(Bucket=storage.S3_BUCKET)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["id", "email"])
    for i in range(300):
        w.writerow([i, f"u{i}@example.com"])
    data = buf.getvalue().encode()
    c.put_object(Bucket=storage.S3_BUCKET, Key="k.csv", Body=data)
    storage.get_s3_client = lambda: boto3.client("s3", region_name="us-east-1")

    saved = storage._CHUNK_SIZE
    storage._CHUNK_SIZE = 64  # force rows to straddle chunk boundaries
    try:
        sc = PiiScanner()
        meta = storage.probe_dataset("k.csv", "k.csv", observer=sc)
    finally:
        storage._CHUNK_SIZE = saved
    assert meta["row_count"] == 300 and meta["size_bytes"] == len(data)
    assert meta["checksum_sha256"] == hashlib.sha256(data).hexdigest()
    assert sc.rows_scanned == 300
    assert [(f.column_name, f.detector) for f in sc.findings()] == [("email", "email")]


# ---------------- LLM guard ----------------
class FakeConn:
    def __init__(self, status):
        self.status = status

    def cursor(self):
        status = self.status

        class Cur:
            def __enter__(s): return s
            def __exit__(s, *a): return False
            def execute(s, q, p): pass
            def fetchone(s): return None if status is None else (status,)
        return Cur()


@pytest.mark.parametrize("status", ["pending", "skipped_unsupported", "legacy_unscanned", None])
def test_guard_blocks_anything_but_a_completed_scan(status):
    with pytest.raises(PiiNotScanned):
        require_pii_scanned(FakeConn(status), "d1")


def test_guard_allows_scanned():
    require_pii_scanned(FakeConn("scanned"), "d1")
