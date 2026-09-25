import express from "express";
import { edaCleanQueue, edaCleanEvents } from "./queue.js";
import { Pool } from "pg";
import "dotenv/config";

const app = express();
app.use(express.json());

const pool = new Pool({
  host: process.env.PGHOST || "127.0.0.1",
  port: Number(process.env.PGPORT) || 5433,
  user: process.env.PGUSER || "postgres",
  password: process.env.PGPASSWORD || "postgres",
  database: process.env.PGDATABASE || "eda_platform",
});

// --- 0.1: trivial round trip -----------------------------------------
// frontend (curl, here) -> API gateway -> Python agent worker stub -> response
app.post("/api/ping-agent", async (_req, res) => {
  const job = await edaCleanQueue.add("echo", { hello: "from-node-api", ts: Date.now() });
  try {
    const result = await job.waitUntilFinished(edaCleanEvents, 15_000);
    res.json({ ok: true, jobId: job.id, result });
  } catch (err: any) {
    res.status(504).json({ ok: false, error: String(err) });
  }
});

// --- 0.3: approval-gate mechanics --------------------------------------
// Kicks off a fake "playbook run" job that the Python worker will pause
// partway through by writing to pending_approvals and exiting (no worker
// held). This endpoint just enqueues; polling/resume are separate endpoints.
app.post("/api/runs/:runId/start", async (req, res) => {
  const { runId } = req.params;
  const job = await edaCleanQueue.add("playbook_run", { runId });
  res.json({ ok: true, jobId: job.id });
});

app.get("/api/runs/:runId/pending-approval", async (req, res) => {
  try {
    const { runId } = req.params;
    const { rows } = await pool.query(
      "SELECT * FROM pending_approvals WHERE cleaning_run_id = $1 AND status = 'awaiting_approval' ORDER BY created_at DESC LIMIT 1",
      [runId]
    );
    res.json({ ok: true, pending: rows[0] ?? null });
  } catch (err: any) {
    console.error("pending-approval query failed:", err);
    // Keep the response shape stable even on failure so callers never hit a
    // KeyError/undefined on `pending` -- always present, just null on error.
    res.status(500).json({ ok: false, error: String(err), pending: null });
  }
});

app.post("/api/approvals/:id/resolve", async (req, res) => {
  const { id } = req.params;
  const { decision } = req.body; // 'approved' | 'rejected'
  const { rows } = await pool.query(
    "UPDATE pending_approvals SET status = 'resolved', resolved_at = now() WHERE id = $1 RETURNING *",
    [id]
  );
  const approval = rows[0];
  if (!approval) return res.status(404).json({ ok: false, error: "not found" });

  await pool.query(
    "UPDATE cleaning_actions SET status = $1, decided_at = now() WHERE action_id = ANY($2)",
    [decision === "approved" ? "approved" : "rejected", approval.action_ids]
  );

  // Re-enqueue the job from where it left off.
  const job = await edaCleanQueue.add("playbook_run_resume", {
    runId: approval.cleaning_run_id,
    resumeAfterStep: approval.step_id,
    decision,
  });
  res.json({ ok: true, resumedJobId: job.id });
});

const PORT = 4000;
app.listen(PORT, async () => {
  console.log(`API gateway listening on :${PORT}`);
  // Fail loud at boot, not on the first request that happens to touch
  // Postgres -- a bad PGPORT/PGPASSWORD should be obvious immediately.
  try {
    const { rows } = await pool.query("SHOW server_version");
    const version = rows[0]?.server_version ?? "unknown";
    console.log(`Postgres OK (${pool.options.host}:${pool.options.port}/${pool.options.database}), server_version=${version}`);
    // docker-compose.yml runs postgres:16 -- if something else answers on
    // this host/port (most commonly a native Postgres install also bound to
    // the same port), the version won't match even though the connection
    // itself succeeds. This has bitten real setups: a native PG17 with its
    // own same-named database silently answering instead of the container.
    if (!version.startsWith("16")) {
      console.warn(
        `WARNING: connected Postgres reports version ${version}, but docker-compose.yml runs postgres:16. ` +
        `This usually means something other than the docker-compose container is listening on ` +
        `${pool.options.host}:${pool.options.port} -- most commonly a native/local Postgres install also ` +
        `bound to that port. Run 'docker ps' to confirm the container is up, and on Windows ` +
        `'netstat -ano | findstr :${pool.options.port}' to see which process actually owns the port.`
      );
    }
  } catch (err: any) {
    const authHint = /password authentication failed/i.test(err.message)
      ? `\nThis is often NOT a wrong-password problem -- it usually means ${pool.options.host}:${pool.options.port} ` +
        `is being served by a *different* Postgres than docker-compose's (most commonly a native/local install ` +
        `also bound to that port, possibly with its own same-named database). Run 'docker ps' to confirm the ` +
        `container is up, and on Windows 'netstat -ano | findstr :${pool.options.port}' to see which process ` +
        `actually owns the port before assuming the password itself is wrong.`
      : "";
    console.error(
      `Postgres connection failed at startup (${pool.options.host}:${pool.options.port}/${pool.options.database}): ${err.message}\n` +
      `If you're using docker-compose.yml as-is, Postgres is published on host port 5433 (not 5432) -- ` +
      `make sure PGPORT=5433 is set (see .env.example) or that no other Postgres is listening on 5432.` +
      authHint
    );
  }
});
