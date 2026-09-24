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
import uuid
from bullmq import Worker
from dotenv import load_dotenv
from agent_worker.db import get_conn

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


HANDLERS = {
    "echo": handle_echo,
    "playbook_run": handle_playbook_run,
    "playbook_run_resume": handle_playbook_run_resume,
}


async def process(job, token):
    handler = HANDLERS.get(job.name)
    if handler is None:
        raise ValueError(f"no handler for job type {job.name}")
    return handler(job.data)


async def main():
    worker = Worker("agent.eda_clean", process, {"connection": REDIS_URL})
    print("Python agent worker listening on queue agent.eda_clean ...")
    await asyncio.Event().wait()  # run forever


if __name__ == "__main__":
    asyncio.run(main())
