import { Queue, QueueEvents } from "bullmq";
import "dotenv/config";

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

