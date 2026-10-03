import "./tracing.js"; // must be first: registers the tracer/context-manager before any span is created
import express from "express";
import { edaCleanEvents, addTracedJob, discoveryQueue, discoveryEvents } from "./queue.js";
import { Pool, types } from "pg";
import "dotenv/config";
import { SpanStatusCode } from "@opentelemetry/api";
import { tracer } from "./tracing.js";
import Busboy from "busboy";
import { randomUUID } from "crypto";
import { Upload } from "@aws-sdk/lib-storage";
import { s3, S3_BUCKET, ensureBucket } from "./storage.js";

const app = express();
app.use(express.json());
// Dev-only test harness for exercising /api/datasets/upload by hand (drag
// and drop) without a real frontend -- the frontend framework itself is
// still an open decision (not settled anywhere in docs/trd.md), so this is
// deliberately vanilla HTML/JS, not a stand-in for that decision.
app.use(express.static("public"));

// node-postgres returns BIGINT (OID 20) as a string by default to avoid
// precision loss past 2^53. datasets.size_bytes / row_count are far below
// that, and API consumers shouldn't have to parse numeric strings.
types.setTypeParser(20, (v) => Number(v));

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
  await tracer.startActiveSpan("POST /api/ping-agent", async (span) => {
    try {
      const job = await addTracedJob("echo", { hello: "from-node-api", ts: Date.now() });
      span.setAttribute("bullmq.job_id", String(job.id));
      try {
        const result = await job.waitUntilFinished(edaCleanEvents, 15_000);
        res.json({ ok: true, jobId: job.id, result });
      } catch (err: any) {
        span.recordException(err);
        span.setStatus({ code: SpanStatusCode.ERROR, message: String(err) });
        res.status(504).json({ ok: false, error: String(err) });
      }
    } finally {
      span.end();
    }
  });
});

// --- 0.3: approval-gate mechanics --------------------------------------
// Kicks off a fake "playbook run" job that the Python worker will pause
// partway through by writing to pending_approvals and exiting (no worker
// held). This endpoint just enqueues; polling/resume are separate endpoints.
app.post("/api/runs/:runId/start", async (req, res) => {
  await tracer.startActiveSpan("POST /api/runs/:runId/start", async (span) => {
    const { runId } = req.params;
    span.setAttribute("eda.run_id", runId);
    try {
      const job = await addTracedJob("playbook_run", { runId });
      span.setAttribute("bullmq.job_id", String(job.id));
      res.json({ ok: true, jobId: job.id });
    } finally {
      span.end();
    }
  });
});

app.get("/api/runs/:runId/pending-approval", async (req, res) => {
  await tracer.startActiveSpan("GET /api/runs/:runId/pending-approval", async (span) => {
    try {
      const { runId } = req.params;
      span.setAttribute("eda.run_id", runId);
      const { rows } = await pool.query(
        "SELECT * FROM pending_approvals WHERE cleaning_run_id = $1 AND status = 'awaiting_approval' ORDER BY created_at DESC LIMIT 1",
        [runId]
      );
      res.json({ ok: true, pending: rows[0] ?? null });
    } catch (err: any) {
      console.error("pending-approval query failed:", err);
      span.recordException(err);
      span.setStatus({ code: SpanStatusCode.ERROR, message: String(err) });
      // Keep the response shape stable even on failure so callers never hit a
      // KeyError/undefined on `pending` -- always present, just null on error.
      res.status(500).json({ ok: false, error: String(err), pending: null });
    } finally {
      span.end();
    }
  });
});

app.post("/api/approvals/:id/resolve", async (req, res) => {
  await tracer.startActiveSpan("POST /api/approvals/:id/resolve", async (span) => {
    try {
      const { id } = req.params;
      const { decision } = req.body; // 'approved' | 'rejected'
      span.setAttribute("eda.approval_id", id);
      span.setAttribute("eda.decision", decision);
      const { rows } = await pool.query(
        "UPDATE pending_approvals SET status = 'resolved', resolved_at = now() WHERE id = $1 RETURNING *",
        [id]
      );
      const approval = rows[0];
      if (!approval) {
        res.status(404).json({ ok: false, error: "not found" });
        return;
      }

      await pool.query(
        "UPDATE cleaning_actions SET status = $1, decided_at = now() WHERE action_id = ANY($2)",
        [decision === "approved" ? "approved" : "rejected", approval.action_ids]
      );

      // Re-enqueue the job from where it left off.
      const job = await addTracedJob("playbook_run_resume", {
        runId: approval.cleaning_run_id,
        resumeAfterStep: approval.step_id,
        decision,
      });
      span.setAttribute("bullmq.job_id", String(job.id));
      res.json({ ok: true, resumedJobId: job.id });
    } finally {
      span.end();
    }
  });
});

// --- 1.1: file upload path ---------------------------------------------
// Streams the multipart file straight into S3/MinIO (bounded-memory
// multipart PUT via @aws-sdk/lib-storage's Upload, never buffering the
// whole file in RAM or on local disk) and inserts a `datasets` row with
// status='ingesting'. Anything heavier than moving bytes -- size, row/column
// counts, checksum -- is explicitly NOT computed here: it's handed to the
// Python worker via the job queue (see agent_worker.worker.handle_ingest_dataset)
// so a large file's CPU-bound parsing work never runs on the request thread.
// Streaming the bytes themselves during the request is unavoidable (the
// upload *is* the request body) but is I/O-bound async work, not a blocking
// call -- it doesn't hold the Node event loop the way synchronous parsing would.
app.post("/api/datasets/upload", async (req, res) => {
  await tracer.startActiveSpan("POST /api/datasets/upload", async (span) => {
    const datasetId = randomUUID();
    let sawFile = false;
    let uploadDone: Promise<unknown> | null = null;
    let originalFilename = "";
    let mimeType = "";
    let storageKey = "";
    let responded = false;

    const fail = (status: number, error: string, err?: unknown) => {
      if (err) {
        span.recordException(err as Error);
        span.setStatus({ code: SpanStatusCode.ERROR, message: error });
      }
      if (!responded && !res.headersSent) {
        responded = true;
        res.status(status).json({ ok: false, error });
      }
      span.end();
    };

    const bb = Busboy({ headers: req.headers, limits: { files: 1 } });

    bb.on("file", (_field, fileStream, info) => {
      sawFile = true;
      originalFilename = info.filename;
      mimeType = info.mimeType || "application/octet-stream";
      storageKey = `uploads/${datasetId}/${info.filename}`;
      span.setAttribute("eda.dataset_id", datasetId);
      span.setAttribute("eda.storage_key", storageKey);

      const upload = new Upload({
        client: s3,
        params: { Bucket: S3_BUCKET, Key: storageKey, Body: fileStream, ContentType: mimeType },
        // 8MB parts -- keeps memory bounded regardless of total file size
        // (a 500MB file streams as ~63 parts, never sitting in RAM whole).
        partSize: 8 * 1024 * 1024,
        queueSize: 4,
      });
      uploadDone = upload.done();
    });

    bb.on("error", (err) => fail(400, `upload stream error: ${String(err)}`, err));

    bb.on("finish", async () => {
      try {
        if (!sawFile || !uploadDone) {
          fail(400, "no file field found in multipart body");
          return;
        }
        await uploadDone; // I/O-bound wait on the S3 PUT, not a blocking call

        await pool.query(
          `INSERT INTO datasets (id, name, source, storage_path, status, original_filename, mime_type)
           VALUES ($1, $2, 'upload', $3, 'ingesting', $4, $5)`,
          [datasetId, originalFilename, storageKey, originalFilename, mimeType]
        );

        const job = await addTracedJob("ingest_dataset", { datasetId, storageKey, originalFilename });
        span.setAttribute("bullmq.job_id", String(job.id));
        responded = true;
        res.json({ ok: true, datasetId, jobId: job.id, status: "ingesting" });
      } catch (err: any) {
        fail(500, String(err?.message ?? err), err);
        return;
      } finally {
        span.end();
      }
    });

    req.on("aborted", () => fail(499, "client aborted upload"));
    req.pipe(bb);
  });
});

app.get("/api/datasets/:id", async (req, res) => {
  const { rows } = await pool.query("SELECT * FROM datasets WHERE id = $1", [req.params.id]);
  if (!rows[0]) {
    res.status(404).json({ ok: false, error: "not found" });
    return;
  }
  res.json({ ok: true, dataset: rows[0] });
});

app.get("/api/datasets", async (_req, res) => {
  const { rows } = await pool.query("SELECT * FROM datasets ORDER BY created_at DESC LIMIT 50");
  res.json({ ok: true, datasets: rows });
});

// --- 1.2: Kaggle discovery (Agent 1) ------------------------------------
// Search/list are quick metadata calls: dispatched to the Python discovery
// worker via its queue and awaited (D-011). Import is NOT awaited -- it can
// download up to KAGGLE_MAX_IMPORT_MB -- so it returns 202 and the client
// polls GET /api/datasets/:id, same ingesting -> ready|failed flow as upload.
const KAGGLE_REF_RE = /^[A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+$/;
const TABULAR_RE = /\.(csv|tsv)$/i;

async function runDiscoveryJob(name: string, data: Record<string, unknown>, timeoutMs: number) {
  const job = await addTracedJob(name, data, discoveryQueue);
  return job.waitUntilFinished(discoveryEvents, timeoutMs);
}

app.get("/api/discovery/search", async (req, res) => {
  const q = String(req.query.q ?? "").trim();
  if (q.length < 2 || q.length > 200) {
    res.status(400).json({ ok: false, error: "q must be 2-200 characters" });
    return;
  }
  try {
    const result = await runDiscoveryJob("kaggle_search", { query: q }, 60_000);
    res.json({ ok: true, ...result });
  } catch (err: any) {
    res.status(502).json({ ok: false, error: String(err?.message ?? err) });
  }
});

app.get("/api/discovery/files", async (req, res) => {
  const ref = String(req.query.ref ?? "");
  if (!KAGGLE_REF_RE.test(ref)) {
    res.status(400).json({ ok: false, error: "ref must look like owner/dataset-name" });
    return;
  }
  try {
    const result = await runDiscoveryJob("kaggle_list_files", { ref }, 60_000);
    res.json({ ok: true, ...result });
  } catch (err: any) {
    res.status(502).json({ ok: false, error: String(err?.message ?? err) });
  }
});

app.post("/api/discovery/import", async (req, res) => {
  const ref = String(req.body?.ref ?? "");
  const fileName = String(req.body?.fileName ?? "");
  if (!KAGGLE_REF_RE.test(ref)) {
    res.status(400).json({ ok: false, error: "ref must look like owner/dataset-name" });
    return;
  }
  if (!fileName || fileName.length > 255 || fileName.includes("..") || fileName.startsWith("/") || !TABULAR_RE.test(fileName)) {
    res.status(400).json({ ok: false, error: "fileName must be a CSV/TSV file listed by /api/discovery/files" });
    return;
  }
  const existing = async () =>
    (await pool.query(
      `SELECT id, status FROM datasets
       WHERE source = 'kaggle' AND source_ref = $1 AND original_filename = $2 AND status <> 'failed' LIMIT 1`,
      [ref, fileName]
    )).rows[0];

  const prior = await existing();
  if (prior) {
    res.json({ ok: true, datasetId: prior.id, status: prior.status, deduped: true });
    return;
  }

  const datasetId = randomUUID();
  const base = fileName.split("/").pop() as string;
  const storageKey = `uploads/${datasetId}/${base}`;
  try {
    await pool.query(
      `INSERT INTO datasets (id, name, source, source_ref, storage_path, status, original_filename)
       VALUES ($1, $2, 'kaggle', $3, $4, 'ingesting', $5)`,
      [datasetId, `${ref}/${fileName}`, ref, storageKey, fileName]
    );
  } catch (err: any) {
    if (err?.code === "23505") {
      // lost a double-click race on the unique index -- return the winner
      const winner = await existing();
      if (winner) {
        res.json({ ok: true, datasetId: winner.id, status: winner.status, deduped: true });
        return;
      }
    }
    res.status(500).json({ ok: false, error: String(err?.message ?? err) });
    return;
  }
  try {
    const job = await addTracedJob("kaggle_import", { datasetId, ref, fileName, storageKey }, discoveryQueue);
    res.status(202).json({ ok: true, datasetId, jobId: job.id, status: "ingesting" });
  } catch (err: any) {
    await pool.query("UPDATE datasets SET status = 'failed', error_message = $2 WHERE id = $1", [
      datasetId,
      `could not enqueue import: ${err?.message ?? err}`,
    ]);
    res.status(500).json({ ok: false, error: String(err?.message ?? err) });
  }
});

const PORT = 4000;
app.listen(PORT, async () => {
  console.log(`API gateway listening on :${PORT}`);
  await ensureBucket();
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
