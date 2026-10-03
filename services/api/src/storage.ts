import { S3Client, HeadBucketCommand, CreateBucketCommand } from "@aws-sdk/client-s3";
import "dotenv/config";

// Path-style addressing is required for MinIO (dev default); real AWS S3
// wants virtual-hosted-style, so production config should set
// S3_FORCE_PATH_STYLE=false alongside dropping S3_ENDPOINT. Same
// fallback-to-local-defaults pattern as queue.ts/index.ts so the sandbox
// keeps working with no .env at all.
const forcePathStyle = (process.env.S3_FORCE_PATH_STYLE ?? "true") === "true";

export const s3 = new S3Client({
  region: process.env.S3_REGION || "us-east-1",
  endpoint: process.env.S3_ENDPOINT || "http://127.0.0.1:8333",
  forcePathStyle,
  credentials: {
    accessKeyId: process.env.S3_ACCESS_KEY || "devkey",
    secretAccessKey: process.env.S3_SECRET_KEY || "devsecret",
  },
});

export const S3_BUCKET = process.env.S3_BUCKET || "eda-platform-datasets";

console.log(
  `API object storage target: ${process.env.S3_ENDPOINT || "http://127.0.0.1:8333"} (bucket=${S3_BUCKET}, pathStyle=${forcePathStyle})`
);

// No separate `mc`-style bucket-creation container (see D-014 -- one less
// dependency on a third-party image). Whichever of the API gateway / agent
// worker starts first creates the bucket; the other's attempt below just
// hits the "already exists" branch and moves on.
export async function ensureBucket(): Promise<void> {
  try {
    await s3.send(new HeadBucketCommand({ Bucket: S3_BUCKET }));
    return;
  } catch {
    // Bucket doesn't exist (or HeadBucket isn't supported the same way by
    // every S3-compatible server) -- fall through and try to create it.
  }
  try {
    await s3.send(new CreateBucketCommand({ Bucket: S3_BUCKET }));
    console.log(`Created S3 bucket "${S3_BUCKET}"`);
  } catch (err: any) {
    const name = String(err?.name ?? err);
    if (/BucketAlready/i.test(name)) {
      // Race with the Python worker creating it at the same moment -- fine.
      return;
    }
    console.error(
      `Could not create/verify S3 bucket "${S3_BUCKET}" at ${process.env.S3_ENDPOINT || "http://127.0.0.1:8333"}: ${err?.message ?? err}\n` +
      `Uploads will fail until this bucket exists. Check that the seaweedfs container is up (docker compose ps).`
    );
  }
}
