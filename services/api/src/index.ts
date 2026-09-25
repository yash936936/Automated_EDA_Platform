import express from "express";
import { edaCleanQueue, edaCleanEvents } from "./queue.js";
import { Pool } from "pg";
import "dotenv/config";

const app = express();
app.use(express.json());

const pool = new Pool({
  host: process.env.PGHOST || "127.0.0.1",
  port: Number(process.env.PGPORT) || 5432,
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
    res.status(500).json({ ok: false, error: String(err) });
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
app.listen(PORT, () => console.log(`API gateway listening on :${PORT}`));
