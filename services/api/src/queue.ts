import { Queue, QueueEvents } from "bullmq";
import "dotenv/config";
import { context, propagation } from "@opentelemetry/api";

// Reads from .env (see .env.example). Falls back to local defaults so the
// Phase 0 sandbox setup keeps working with no .env file present at all.
const useTLS = process.env.REDIS_TLS === "true";

export const connection = {
  host: process.env.REDIS_HOST || "127.0.0.1",
  port: Number(process.env.REDIS_PORT) || 6379,
  ...(process.env.REDIS_PASSWORD ? { password: process.env.REDIS_PASSWORD } : {}),
  ...(useTLS ? { tls: {} } : {}),
};

// One queue per agent, per the design doc's "separate concurrency caps per
// agent" requirement (Phase 0.3). Only 'eda_clean' is wired up in Phase 0 --
// the others are stubs for later phases.
export const edaCleanQueue = new Queue("agent.eda_clean", { connection });
export const edaCleanEvents = new QueueEvents("agent.eda_clean", { connection });

// Always print exactly which Redis this process resolved at startup. If you
// edit .env's REDIS_* values, any *already-running* API/worker process keeps
// using whatever it loaded at its own startup -- restarting one side but not
// the other silently puts producer and consumer on two different queues
// (jobs enqueue fine, nothing ever consumes them). This line, and the
// matching one the Python worker prints, are the fastest way to catch that:
// if they don't show the same host/port, that's the whole bug.
console.log(`API Redis target: ${connection.host}:${connection.port}${useTLS ? " (tls)" : ""}`);

// BullMQ requires maxmemory-policy=noeviction and only warns (doesn't fail)
// when it isn't set. docker-compose.yml's `redis-server --maxmemory-policy
// noeviction` command should already guarantee this, but if that warning
// shows up anyway it almost always means this app is actually talking to a
// *different* Redis than the one in docker-compose (e.g. a native/WSL Redis
// also on 6379, or a stale container from before --force-recreate). Enforce
// it here too so the app is correct even in that case, and log clearly if
// it can't be set (e.g. a managed Redis that disallows CONFIG SET).
edaCleanQueue.client
  .then((redisClient: any) =>
    redisClient.config("SET", "maxmemory-policy", "noeviction")
  )
  .catch((err) =>
    console.warn(
      `Could not enforce maxmemory-policy=noeviction on Redis (${connection.host}:${connection.port}): ${err.message}\n` +
      `If you keep seeing the "Eviction policy is volatile-lru" warning, check whether ` +
      `something other than the docker-compose redis container is listening on that host/port.`
    )
  );

// Trace context does not cross the Redis/BullMQ boundary on its own -- the
// Python worker runs in a separate process with no shared memory, so the
// only way to link "API enqueued this job" and "worker processed this job"
// into a single trace is to carry the W3C traceparent explicitly inside the
// job payload itself, the same way it'd ride along in an HTTP header. Every
// call site should use this instead of edaCleanQueue.add directly, so no job
// type accidentally loses its trace context.
export async function addTracedJob(name: string, data: Record<string, unknown>) {
  const carrier: Record<string, string> = {};
  propagation.inject(context.active(), carrier);
  return edaCleanQueue.add(name, { ...data, _traceCarrier: carrier });
}

