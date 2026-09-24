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

