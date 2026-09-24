// One-off connectivity check -- doesn't require redis-cli. Run from
// services/api (where ioredis is already installed via bullmq), after
// filling in .env.
import "dotenv/config";
import Redis from "ioredis";

const useTLS = process.env.REDIS_TLS === "true";
const redis = new Redis({
  host: process.env.REDIS_HOST,
  port: Number(process.env.REDIS_PORT),
  password: process.env.REDIS_PASSWORD || undefined,
  ...(useTLS ? { tls: {} } : {}),
});

redis
  .ping()
  .then((res) => {
    console.log("PING ->", res); // expect PONG
    process.exit(0);
  })
  .catch((err) => {
    console.error("Connection failed:", err.message);
    process.exit(1);
  });
