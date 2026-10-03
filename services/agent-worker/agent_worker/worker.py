"""
Phase 0 stub for Agent 2 (EDA/Clean) running on the same Redis-backed BullMQ
queue as the Node API gateway. Handles three job types:

- 'echo'              : Phase 0.1 round-trip test.
- 'playbook_run'      : Phase 0.3 test -- simulates a playbook that hits a
                         risky action, writes a pending_approvals row, and
                         *returns* (does not block/hold the worker) so the
                         run can sit in awaiting_approval at zero worker cost.
- 'playbook_run_resume': re-enqueued by the API after a human decision;
                         completes the (simulated) remainder of the run.
"""
import asyncio
import os
import sys
import uuid
from bullmq import Worker, Queue
from dotenv import load_dotenv
from agent_worker.db import get_conn
from agent_worker.storage import probe_dataset, ensure_bucket
from agent_worker.discovery import importer, kaggle_client
from agent_worker.discovery import search as discovery_search
from agent_worker.tracing import tracer, extract_context
from opentelemetry.propagate import inject
from opentelemetry.trace import SpanKind, Status, StatusCode

# Python block-buffers stdout when it isn't a terminal (i.e. any time it's
# redirected to a log file, as dev-up.sh/dev-up.ps1 and every debugging
# session in this repo have done) -- print() output can sit invisible in an
# internal buffer for a long time instead of reaching the file immediately.
# This has silently made worker.log look empty/stale during startup
# debugging more than once. Force line buffering unconditionally so log
# output is trustworthy the moment it's written, not whenever the buffer
# happens to flush.
sys.stdout.reconfigure(line_buffering=True)
sys.stderr.reconfigure(line_buffering=True)

load_dotenv()  # reads .env from CWD if present; no-op if the file doesn't exist

# Reads from the environment. Falls back to local defaults so the Phase 0
# sandbox setup keeps working unchanged with no .env file at all.
_host = os.environ.get("REDIS_HOST", "127.0.0.1")
_port = os.environ.get("REDIS_PORT", "6379")
_password = os.environ.get("REDIS_PASSWORD")
_scheme = "rediss" if os.environ.get("REDIS_TLS") == "true" else "redis"
_auth = f":{_password}@" if _password else ""
REDIS_URL = f"{_scheme}://{_auth}{_host}:{_port}"


def handle_echo(job_data):
    return {"echoed": job_data, "agent": "eda_clean_stub"}


def handle_playbook_run(job_data):
    run_id = job_data["runId"]
    step_id = "drop_column_risky_step"
    action_id = str(uuid.uuid4())

    conn = get_conn()
    try:
        with conn.cursor() as cur:
            # Make sure a cleaning_run row exists for this run_id in a minimal
            # way for the FK -- in real Phase 2 this row is created earlier
            # in the pipeline; here we upsert a placeholder for the test.
            cur.execute(
                "SELECT id FROM cleaning_runs WHERE id = %s", (run_id,)
            )
            if cur.fetchone() is None:
                raise RuntimeError(
                    f"cleaning_run {run_id} does not exist -- create it via "
                    f"the test harness before calling /start"
                )

            cur.execute(
                """
                INSERT INTO cleaning_actions
                    (action_id, cleaning_run_id, step_id, action_type, status, confidence, reasoning)
                VALUES (%s, %s, %s, %s, 'proposed', 0.55, 'low confidence drop_column proposal (Phase 0 stub)')
                """,
                (action_id, run_id, step_id, "drop_column"),
            )
            cur.execute(
                """
                INSERT INTO pending_approvals (cleaning_run_id, step_id, action_ids, status)
                VALUES (%s, %s, %s::uuid[], 'awaiting_approval')
                RETURNING id
                """,
                (run_id, step_id, [action_id]),
            )
            pending_id = cur.fetchone()[0]
            cur.execute(
                "UPDATE cleaning_runs SET status = 'awaiting_approval' WHERE id = %s",
                (run_id,),
            )
        conn.commit()
    finally:
        conn.close()

    # IMPORTANT: the job completes/exits here. No thread/worker slot is held
    # waiting on the human decision -- that's the whole point of the
    # pending_approvals pattern (Phase 0.3 passing criteria).
    return {"paused": True, "pendingApprovalId": pending_id, "actionId": action_id}


def handle_playbook_run_resume(job_data):
    run_id = job_data["runId"]
    decision = job_data["decision"]
    final_status = "completed" if decision == "approved" else "completed_with_rejection"

    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE cleaning_runs SET status = %s WHERE id = %s",
                (final_status, run_id),
            )
        conn.commit()
    finally:
        conn.close()

    return {"resumed": True, "finalStatus": final_status}


def handle_ingest_dataset(job_data):
    """
    Phase 1.1: the deliberately-async half of the upload path. The API
    gateway already streamed the file into S3/MinIO and inserted a
    `datasets` row with status='ingesting' before this job even runs -- this
    handler does the CPU/IO-bound part (streaming the object back out to
    compute size/checksum/row-count) off the request thread, then flips the
    row to 'ready' (or 'failed' with a reason, never leaving it stuck at
    'ingesting' silently).
    """
    dataset_id = job_data["datasetId"]
    storage_key = job_data["storageKey"]
    original_filename = job_data.get("originalFilename", "")

    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM datasets WHERE id = %s", (dataset_id,))
            if cur.fetchone() is None:
                raise RuntimeError(f"dataset {dataset_id} not found (upload row missing)")

        try:
            metadata = probe_dataset(storage_key, original_filename)
        except Exception as exc:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE datasets SET status = 'failed', error_message = %s WHERE id = %s",
                    (str(exc), dataset_id),
                )
            conn.commit()
            raise

        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE datasets
                SET status = 'ready', size_bytes = %s, row_count = %s,
                    column_count = %s, checksum_sha256 = %s, ingested_at = now()
                WHERE id = %s
                """,
                (
                    metadata["size_bytes"],
                    metadata["row_count"],
                    metadata["column_count"],
                    metadata["checksum_sha256"],
                    dataset_id,
                ),
            )
        conn.commit()
    finally:
        conn.close()

    return {"datasetId": dataset_id, **metadata}


# --- Phase 1.2: Agent 1 (Dataset Discovery) --------------------------------
# Runs on its own queue ("agent.discovery") so its concurrency cap is
# independent of the EDA/clean queue, per the design doc.

def handle_kaggle_search(job_data):
    return discovery_search.search(job_data["query"])


def handle_kaggle_list_files(job_data):
    ref = job_data["ref"]
    importer.validate_ref(ref)
    files = kaggle_client.list_files(ref)
    for f in files:
        f["tabular"] = f["name"].lower().endswith(importer.TABULAR_EXT)
    return {"ref": ref, "files": files}


def _mark_failed(dataset_id, message):
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE datasets SET status = 'failed', error_message = %s WHERE id = %s",
                (message[:1000], dataset_id),
            )
        conn.commit()
    finally:
        conn.close()


def handle_kaggle_import(job_data):
    """Validate -> download that one file -> stream into object storage. The
    datasets row already exists (status='ingesting', inserted by the API);
    any failure here flips it to 'failed' with a reason instead of leaving it
    stuck. The follow-up 'ingest_dataset' job is enqueued by process_discovery."""
    dataset_id, ref, file_name = job_data["datasetId"], job_data["ref"], job_data["fileName"]
    storage_key = job_data["storageKey"]
    try:
        importer.validate_file(ref, file_name)
        size = importer.download_to_storage(ref, file_name, storage_key)
    except Exception as exc:
        _mark_failed(dataset_id, f"{type(exc).__name__}: {exc}")
        raise
    return {"datasetId": dataset_id, "storageKey": storage_key, "originalFilename": file_name, "sizeBytes": size}


DISCOVERY_HANDLERS = {
    "kaggle_search": handle_kaggle_search,
    "kaggle_list_files": handle_kaggle_list_files,
    "kaggle_import": handle_kaggle_import,
}

_ingest_queue = None  # set in main(); the shared EDA/clean queue that owns 'ingest_dataset'


async def process_discovery(job, token):
    handler = DISCOVERY_HANDLERS.get(job.name)
    if handler is None:
        raise ValueError(f"no discovery handler for job type {job.name}")
    parent_ctx = extract_context(job.data)
    with tracer.start_as_current_span(
        f"worker.process {job.name}",
        context=parent_ctx,
        kind=SpanKind.CONSUMER,
        attributes={"bullmq.job_id": str(job.id), "bullmq.job_name": job.name},
    ) as span:
        try:
            # Handlers do blocking network/disk I/O (Kaggle download can take
            # minutes). Run them in a thread so the worker's event loop keeps
            # renewing the BullMQ job lock instead of the job being flagged
            # stalled and re-run mid-download. (contextvars, so the trace
            # context, are copied into the thread by asyncio.to_thread.)
            result = await asyncio.to_thread(handler, job.data)
            if job.name == "kaggle_import":
                carrier = {}
                inject(carrier)
                try:
                    await _ingest_queue.add(
                        "ingest_dataset",
                        {
                            "datasetId": result["datasetId"],
                            "storageKey": result["storageKey"],
                            "originalFilename": result["originalFilename"],
                            "_traceCarrier": carrier,
                        },
                    )
                except Exception as exc:
                    await asyncio.to_thread(_mark_failed, result["datasetId"], f"could not enqueue ingestion: {exc}")
                    raise
            return result
        except Exception as exc:
            span.record_exception(exc)
            span.set_status(Status(StatusCode.ERROR, str(exc)))
            raise


HANDLERS = {
    "echo": handle_echo,
    "playbook_run": handle_playbook_run,
    "playbook_run_resume": handle_playbook_run_resume,
    "ingest_dataset": handle_ingest_dataset,
}


async def process(job, token):
    handler = HANDLERS.get(job.name)
    if handler is None:
        raise ValueError(f"no handler for job type {job.name}")
    parent_ctx = extract_context(job.data)
    with tracer.start_as_current_span(
        f"worker.process {job.name}",
        context=parent_ctx,
        kind=SpanKind.CONSUMER,
        attributes={"bullmq.job_id": str(job.id), "bullmq.job_name": job.name},
    ) as span:
        try:
            result = handler(job.data)
            return result
        except Exception as exc:
            span.record_exception(exc)
            span.set_status(Status(StatusCode.ERROR, str(exc)))
            raise


async def main():
    global _ingest_queue
    ensure_bucket()
    worker = Worker("agent.eda_clean", process, {"connection": REDIS_URL})
    _ingest_queue = Queue("agent.eda_clean", {"connection": REDIS_URL})
    discovery_worker = Worker(
        "agent.discovery",
        process_discovery,
        {"connection": REDIS_URL, "concurrency": int(os.environ.get("DISCOVERY_CONCURRENCY", "2"))},
    )
    # Print exactly which Redis this process resolved at startup (password
    # redacted) -- if you edit .env's REDIS_* values, any *already-running*
    # worker process keeps using whatever it loaded at its own startup
    # (python-dotenv only reads .env once). A stale worker on the old Redis
    # while a freshly-restarted API points at a new one means producer and
    # consumer sit on two different queues -- jobs enqueue fine, nothing ever
    # consumes them, and it looks identical to "the worker isn't running" at
    # the API/test level. Always check this line matches your current .env
    # before assuming a hang is a code bug.
    redacted = REDIS_URL.replace(f":{_password}@", ":***@") if _password else REDIS_URL
    print(f"Python agent worker listening on queues agent.eda_clean + agent.discovery (redis={redacted}) ...")
    await asyncio.Event().wait()  # run forever


if __name__ == "__main__":
    asyncio.run(main())
