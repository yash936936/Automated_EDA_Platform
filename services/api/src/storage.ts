import { S3Client } from "@aws-sdk/client-s3";
import "dotenv/config";

// Path-style addressing is required for MinIO (dev default); real AWS S3
// wants virtual-hosted-style, so production config should set
// S3_FORCE_PATH_STYLE=false alongside dropping S3_ENDPOINT. Same
// fallback-to-local-defaults pattern as queue.ts/index.ts so the sandbox
// keeps working with no .env at all.
const forcePathStyle = (process.env.S3_FORCE_PATH_STYLE ?? "true") === "true";

export const s3 = new S3Client({
  region: process.env.S3_REGION || "us-east-1",
  endpoint: process.env.S3_ENDPOINT || "http://127.0.0.1:9000",
  forcePathStyle,
  credentials: {
    accessKeyId: process.env.S3_ACCESS_KEY || "minioadmin",
    secretAccessKey: process.env.S3_SECRET_KEY || "minioadmin",
  },
});

export const S3_BUCKET = process.env.S3_BUCKET || "eda-platform-datasets";

console.log(
  `API object storage target: ${process.env.S3_ENDPOINT || "http://127.0.0.1:9000"} (bucket=${S3_BUCKET}, pathStyle=${forcePathStyle})`
);
