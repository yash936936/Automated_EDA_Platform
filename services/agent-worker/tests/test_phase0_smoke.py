"""
Phase 0 automated smoke suite -- replaces the one-off manual curl/psql
verification from 2026-09-24. Requires:
  - docker compose up -d (redis + postgres)
  - node dist/index.js running (API on :4000)
  - python -m agent_worker.worker running (consumer on agent.eda_clean)
  - migrations already applied to the eda_platform DB

Run from services/agent-worker/:
    python -m pytest tests/test_phase0_smoke.py -v
"""
import os
import time
import uuid
import requests
import psycopg2
import pytest

API = os.environ.get("API_BASE_URL", "http://localhost:4000")
PG = dict(
    host=os.environ.get("PGHOST", "127.0.0.1"),
    port=os.environ.get("PGPORT", "5433"),
    dbname=os.environ.get("PGDATABASE", "eda_platform"),
    user=os.environ.get("PGUSER", "postgres"),
    password=os.environ.get("PGPASSWORD", "postgres"),
)


@pytest.fixture(scope="module")
def conn():
    c = psycopg2.connect(**PG)
    yield c
    c.close()


@pytest.fixture()
def seeded_run(conn):
    """0.2/0.3 need a real cleaning_run row (FK-enforced) to hang a
    pending_approvals row off of -- seed the minimal chain: dataset ->
    playbook -> cleaning_run. Uses a unique playbook_id every run so
    reruns never collide with a leftover row from a previous failure."""
    with conn.cursor() as cur:
        dataset_id = str(uuid.uuid4())
        cur.execute(
            "INSERT INTO datasets (id, name, source, storage_path) VALUES (%s, %s, %s, %s)",
            (dataset_id, "phase0-smoke-dataset", "upload", "s3://smoke/test.csv"),
        )
        playbook_id = str(uuid.uuid4())
        cur.execute(
            "INSERT INTO playbooks (id, playbook_id, domain, version, definition) "
            "VALUES (%s, %s, %s, %s, %s)",
            (playbook_id, f"smoke.test.{uuid.uuid4()}", "generic", 1, "{}"),
        )
        run_id = str(uuid.uuid4())
        cur.execute(
            "INSERT INTO cleaning_runs (id, dataset_id, playbook_id, review_mode, status) "
            "VALUES (%s, %s, %s, 'batch', 'running')",
            (run_id, dataset_id, playbook_id),
        )
    conn.commit()
    return run_id


# --- 0.1: trivial round trip -------------------------------------------
def test_0_1_round_trip():
    r = requests.post(f"{API}/api/ping-agent", timeout=20)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    assert body["result"]["agent"] == "eda_clean_stub"


# --- 0.2: schema + FK enforcement ---------------------------------------
def test_0_2_schema_and_fk(conn):
    tables = [
        "datasets", "playbooks", "cleaning_runs", "dataset_versions",
        "cleaning_actions", "pending_approvals", "downstream_artifacts",
    ]
    with conn.cursor() as cur:
        for t in tables:
            cur.execute(
                "SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_name = %s)",
                (t,),
            )
            assert cur.fetchone()[0], f"table {t} missing"

        # FK enforcement: a cleaning_run referencing a non-existent dataset
        # must be rejected, not silently accepted.
        with pytest.raises(psycopg2.errors.ForeignKeyViolation):
            cur.execute(
                "INSERT INTO cleaning_runs (dataset_id, playbook_id) VALUES (%s, %s)",
                (str(uuid.uuid4()), str(uuid.uuid4())),
            )
    conn.rollback()  # clean up the failed statement's aborted transaction


# --- 0.3: pause/resume, zero worker held while awaiting_approval --------
def test_0_3_pause_and_resume(conn, seeded_run):
    run_id = seeded_run

    start = requests.post(f"{API}/api/runs/{run_id}/start", timeout=20)
    assert start.status_code == 200, start.text

    # Poll for the pending approval -- the job should have exited by now,
    # not be blocking a worker slot.
    pending = None
    for _ in range(20):
        resp = requests.get(f"{API}/api/runs/{run_id}/pending-approval", timeout=10).json()
        if resp["pending"]:
            pending = resp["pending"]
            break
        time.sleep(0.5)
    assert pending is not None, "job never wrote a pending_approvals row"
    assert pending["status"] == "awaiting_approval"

    with conn.cursor() as cur:
        cur.execute("SELECT status FROM cleaning_runs WHERE id = %s", (run_id,))
        assert cur.fetchone()[0] == "awaiting_approval"

    resolve = requests.post(
        f"{API}/api/approvals/{pending['id']}/resolve",
        json={"decision": "approved"},
        timeout=20,
    )
    assert resolve.status_code == 200, resolve.text

    for _ in range(20):
        with conn.cursor() as cur:
            cur.execute("SELECT status FROM cleaning_runs WHERE id = %s", (run_id,))
            status = cur.fetchone()[0]
        if status == "completed":
            break
        time.sleep(0.5)
    assert status == "completed", f"run never completed, stuck at {status}"


# --- 0.4: provider-agnostic interface (fake provider, no key required) --
def test_0_4_llm_interface_contract():
    from agent_worker.llm.factory import get_provider
    os.environ["LLM_PROVIDER"] = "fake"
    p1 = get_provider("discovery")
    p2 = get_provider("eda_clean")
    r1 = p1.complete("test", agent_key="discovery")
    r2 = p2.complete("test", agent_key="eda_clean")
    assert r1.agent_key_used == "discovery"
    assert r2.agent_key_used == "eda_clean"
    # swapping provider is a config change only -- no call-site change needed
    os.environ["LLM_PROVIDER"] = "gemini" if os.environ.get("GEMINI_API_KEY_EDA_CLEAN") else "fake"


@pytest.mark.skipif(
    not os.environ.get("GEMINI_API_KEY_EDA_CLEAN"),
    reason="no real Gemini key set for eda_clean",
)
def test_0_4_live_gemini_call():
    from agent_worker.llm.factory import get_provider
    os.environ["LLM_PROVIDER"] = "gemini"
    p = get_provider("eda_clean")
    result = p.complete("Reply with exactly one word: OK", agent_key="eda_clean")
    assert result.provider == "gemini"
    assert len(result.text.strip()) > 0