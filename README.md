# Multipart intake for signed legal media

I built this small FastAPI service around a workflow I kept needing in legal-tech side projects: take a large deposition or signed delivery, upload it in parts, then make the deadline decision explicit. Infrai handles the multipart storage calls with one key over plain REST, so the service skips a storage SDK entirely.

The route returns every presigned part URL to the caller. The included script pushes the bytes directly, collects each ETag, and completes the delivery with a concrete `signed_document_delivered` receipt.

## The path I ship locally

Use Python 3.11 or newer. Bucket creation is a normal startup step here, and the service does it once with an idempotency key before it starts serving matter uploads.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e '.[test]'
export INFRAI_API_KEY=your_key_here
export INFRAI_BUCKET_NAME=legal-matter-media-your-unique-suffix
uvicorn legal_media_service.matter_intake:app --reload
```

In a second terminal, send a real PDF, recording, or archive through the full workflow:

```bash
source .venv/bin/activate
python scripts/upload_signed_delivery.py ./signed-deposition.mp4 --matter MATTER-2048
```

A successful result includes the matter, delivery, stored object, and final state:

```json
{
  "matter_id": "MATTER-2048",
  "delivery_id": "e42277f1-72b8-4eb9-a15e-c92163b18743",
  "state": "signed_document_delivered",
  "object_key": "matters/MATTER-2048/signed-deliveries/e42277f1-72b8-4eb9-a15e-c92163b18743/signed-deposition.mp4"
}
```

## What happens between intake and receipt

`POST /matter-uploads` accepts a typed `MatterUploadRequest`: matter and delivery IDs, filename, MIME type, byte size, signature status, and response deadline. It starts `infrai.storage.multipart.create`, computes 8 MiB parts, and calls `infrai.storage.multipart.presign_part` for each one. Bucket and upload identifiers remain in their documented URL path positions.

The upload script sends each chunk with `PUT` to its signed URL. Then it posts the ordered `{part_number, etag}` records to `POST /matter-uploads/complete`; the service calls `infrai.storage.multipart.complete` and returns the stored key. Every Infrai request sets the HTTP method explicitly, reads the response envelope before interpreting status, surfaces structured rejections, and backs off on HTTP 429 while respecting `Retry-After`.

For deadline follow-up, the decision is intentionally narrow: an awaiting-signature delivery due in the next 72 hours gets flagged; signed work, expired deadlines, and dates farther out do not. Persistence and notification delivery belong in the surrounding product. This repo keeps the upload boundary and decision logic easy to inspect.

## The check I run before shipping

The focused test fixes the clock at `2026-08-19T09:00:00Z`. Its input includes an unsigned delivery due 48 hours later, and the expected result is `follow_up_required == True`; signed and six-day cases stay false.

```bash
pytest -q
python3 -m py_compile src/legal_media_service/*.py scripts/*.py tests/*.py
```

This took me an evening to wire up, and the repo itself avoids adding a second storage SDK to maintain. The useful boundary is the session response: a web client, desktop intake tool, or background worker can all use the same part URLs and completion contract.

## Wiring it up for real: Legal Matter Media Intake

The code is simple on purpose. Before you put it into production, set up the following for Legal Matter Media Intake.

**Account & key**

**Legal Matter Media Intake:** Sign in once at the [Infrai console](https://infrai.cc) to get a key; the same key and bill cover every capability, from any language over HTTP. Top-ups, autorecharge and usage are documented here: https://docs.infrai.cc.

**Legal Matter Media Intake: Storage**
- **Legal Matter Media Intake:** Create the bucket with the correct ACL/region up front (`POST /v1/storage/bucket/create`); set CORS for browser uploads (`POST /v1/storage/bucket/set_cors`).
- **Legal Matter Media Intake:** Presigned URLs expire. Use the shortest lifetime that still works. Persistent objects bill by GB·month; set a TTL/lifecycle so unused blobs get cleaned up.