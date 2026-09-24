import { Queue, QueueEvents } from "bullmq";

export const connection = { host: "127.0.0.1", port: 6379 };

// One queue per agent, per the design doc's "separate concurrency caps per
// agent" requirement (Phase 0.3). Only 'eda_clean' is wired up in Phase 0 --
// the others are stubs for later phases.
export const edaCleanQueue = new Queue("agent.eda_clean", { connection });
export const edaCleanEvents = new QueueEvents("agent.eda_clean", { connection });
