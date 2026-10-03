"""
Phase 1.2 unit tests -- no Docker, Redis, Postgres, Kaggle account or Gemini
key needed. Kaggle is stubbed at the kaggle_client boundary, S3 is moto.
These prove the logic; tests/test_phase1_2_live.py proves the wiring.
"""
import io
import json
import zipfile

import boto3
import pytest
from moto import mock_aws

from agent_worker import storage
from agent_worker.discovery import importer, kaggle_client, search
from agent_worker.discovery.kaggle_client import KaggleError


def ds(ref, downloads=0):
    return {"ref": ref, "title": ref, "subtitle": "", "sizeBytes": 1, "downloads": downloads,
            "votes": 0, "usability": 0.0, "license": "CC0", "lastUpdated": "", "url": ""}


class DictCache:
    def __init__(self):
        self.d = {}

    def get(self, key):
        return self.d.get(key)

    def set(self, key, payload):
        self.d[key] = payload


class StubProvider:
    def __init__(self, text=None, exc=None):
        self.text, self.exc = text, exc

    def complete(self, prompt, *, agent_key):
        assert agent_key == "discovery"
        if self.exc:
            raise self.exc
        return type("R", (), {"text": self.text})()


# ---- query expansion: the LLM may never fail the search ----
def test_expand_parses_fenced_json_and_dedupes():
    p = StubProvider('```json\n["Housing Prices India", "india real estate", "india property listings", "x"]\n```')
    out, status = search.expand_query("housing prices india", provider=p)
    assert status == "llm"
    assert out == ["india real estate", "india property listings"]  # original deduped, capped at 2, too-short dropped


@pytest.mark.parametrize("provider,expected", [
    (StubProvider("sorry, can't do that"), "fallback_unparseable"),
    (StubProvider("[]"), "fallback_unparseable"),
    (StubProvider(exc=RuntimeError("quota")), "fallback_error"),
])
def test_expand_falls_back_never_raises(provider, expected):
    out, status = search.expand_query("churn", provider=provider)
    assert out == [] and status == expected


# ---- search: fusion + cache ----
def test_search_fuses_dedupes_and_caches(monkeypatch):
    calls = []

    def fake_search(q, **kw):
        calls.append(q)
        return {"a b": [ds("o/x", 5), ds("o/y", 1)], "c d": [ds("o/y", 1), ds("o/z", 9)]}[search.normalize_query(q)]

    monkeypatch.setattr(kaggle_client, "search_datasets", fake_search)
    cache = DictCache()
    expand = lambda q: (["c d"], "llm")

    first = search.search("A  B", cache=cache, expand_fn=expand)
    assert first["cacheHit"] is False
    refs = [r["ref"] for r in first["results"]]
    assert refs[0] == "o/y"  # appears in both lists -> highest fused score
    assert sorted(refs) == ["o/x", "o/y", "o/z"]
    assert calls == ["A  B", "c d"]

    n = len(calls)
    second = search.search("a b", cache=cache, expand_fn=expand)  # normalized key
    assert second["cacheHit"] is True and len(calls) == n  # no new Kaggle/LLM calls


def test_search_primary_failure_raises_but_expansion_failure_is_skipped(monkeypatch):
    def fake_search(q, **kw):
        if q == "bad":
            raise KaggleError("boom")
        return [ds("o/x")]

    monkeypatch.setattr(kaggle_client, "search_datasets", fake_search)
    ok = search.search("good", cache=DictCache(), expand_fn=lambda q: (["bad"], "llm"))
    assert [r["ref"] for r in ok["results"]] == ["o/x"]
    with pytest.raises(KaggleError):
        search.search("bad", cache=DictCache(), expand_fn=lambda q: ([], "llm"))


def test_non_llm_results_get_short_ttl(monkeypatch):
    monkeypatch.setattr(kaggle_client, "search_datasets", lambda q, **kw: [ds("o/x")])
    out = search.search("q1", cache=DictCache(), expand_fn=lambda q: ([], "fallback_error"))
    assert out["ttlHours"] == search.FALLBACK_TTL_HOURS


# ---- importer validation ----
FILES = [{"name": "data.csv", "sizeBytes": 100}, {"name": "big.csv", "sizeBytes": 10**10},
         {"name": "model.pkl", "sizeBytes": 5}]


@pytest.fixture
def listing(monkeypatch):
    monkeypatch.setattr(kaggle_client, "list_files", lambda ref: FILES)


@pytest.mark.parametrize("ref", ["nope", "a/b/c", "a/b c", "../x/y", ""])
def test_bad_refs_rejected(ref):
    with pytest.raises(importer.ImportRejected):
        importer.validate_ref(ref)


def test_validate_file_rules(listing):
    assert importer.validate_file("o/d", "data.csv")["sizeBytes"] == 100
    for name, why in [("model.pkl", "not a CSV"), ("missing.csv", "not found"), ("big.csv", "import cap")]:
        with pytest.raises(importer.ImportRejected, match=why):
            importer.validate_file("o/d", name)


# ---- download -> object storage (moto) ----
def _setup_bucket():
    c = boto3.client("s3", region_name="us-east-1")
    c.create_bucket(Bucket=storage.S3_BUCKET)
    return c


@mock_aws
def test_download_to_storage_direct_file(monkeypatch):
    c = _setup_bucket()

    def fake_dl(ref, file_name, dest, **kw):
        from pathlib import Path
        p = Path(dest) / file_name
        p.write_bytes(b"a,b\n1,2\n")
        return p

    monkeypatch.setattr(kaggle_client, "download_file", fake_dl)
    size = importer.download_to_storage("o/d", "data.csv", "uploads/x/data.csv", s3=c)
    assert size == 8
    assert c.get_object(Bucket=storage.S3_BUCKET, Key="uploads/x/data.csv")["Body"].read() == b"a,b\n1,2\n"


def test_zip_download_is_extracted_safely(tmp_path, monkeypatch):
    class FakeApi:
        def dataset_download_file(self, ref, file_name, path, force, quiet):
            buf = io.BytesIO()
            with zipfile.ZipFile(buf, "w") as zf:
                zf.writestr("../evil.txt", "nope")          # zip-slip attempt
                zf.writestr("sub/data.csv", "a,b\n1,2\n")
            (tmp_path / "data.csv.zip").write_bytes(buf.getvalue())

    monkeypatch.setattr(kaggle_client, "_api", lambda: FakeApi())
    out = kaggle_client.download_file("o/d", "sub/data.csv", str(tmp_path))
    assert out == tmp_path / "data.csv" and out.read_bytes() == b"a,b\n1,2\n"
    assert not (tmp_path.parent / "evil.txt").exists()
    assert not (tmp_path / "data.csv.zip").exists()


def test_zip_over_cap_rejected(tmp_path, monkeypatch):
    class FakeApi:
        def dataset_download_file(self, ref, file_name, path, force, quiet):
            buf = io.BytesIO()
            with zipfile.ZipFile(buf, "w") as zf:
                zf.writestr("data.csv", "x" * 5000)
            (tmp_path / "data.csv.zip").write_bytes(buf.getvalue())

    monkeypatch.setattr(kaggle_client, "_api", lambda: FakeApi())
    with pytest.raises(KaggleError, match="over the import cap"):
        kaggle_client.download_file("o/d", "data.csv", str(tmp_path), max_bytes=100)


def test_missing_credentials_become_clean_kaggle_error(monkeypatch):
    monkeypatch.setattr(kaggle_client, "_api_singleton", None)
    monkeypatch.delenv("KAGGLE_API_TOKEN", raising=False)
    monkeypatch.setenv("HOME", "/nonexistent")
    monkeypatch.setenv("USERPROFILE", "/nonexistent")
    with pytest.raises(KaggleError, match="KAGGLE_API_TOKEN"):
        kaggle_client.search_datasets("anything")
