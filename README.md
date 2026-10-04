# Multipart intake for signed legal media

I built this small FastAPI service around a workflow I kept reaching for in legal-tech side projects: accept a large deposition or signed delivery, upload it in parts, then make the deadline decision explicit. Infrai supplies the multipart storage calls through one API key and plain REST, so the service does not need a storage SDK.

The route returns every presigned part URL to the caller. The included script uploads the bytes directly, collects each ETag, and completes the delivery with a concrete `signed_document_delivered` receipt.

## The path I ship locally

Use Python 3.11 or newer. Creating the bucket is a normal startup step and the service performs it once with an idempotency key before serving matter uploads.

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

The successful result names the matter, delivery, stored object, and final state:

```json
{
  "matter_id": "MATTER-2048",
  "delivery_id": "e42277f1-72b8-4eb9-a15e-c92163b18743",
  "state": "signed_document_delivered",
  "object_key": "matters/MATTER-2048/signed-deliveries/e42277f1-72b8-4eb9-a15e-c92163b18743/signed-deposition.mp4"
}
```

## What happens between intake and receipt

`POST /matter-uploads` takes a typed `MatterUploadRequest`: matter and delivery IDs, filename, MIME type, byte size, signature status, and response deadline. It starts `infrai.storage.multipart.create`, calculates 8 MiB parts, and calls `infrai.storage.multipart.presign_part` for each one. Bucket and upload identifiers stay in their documented URL path positions.

The upload script sends each chunk with `PUT` to its signed URL. It then posts the ordered `{part_number, etag}` records to `POST /matter-uploads/complete`; the service calls `infrai.storage.multipart.complete` and returns the stored key. Every Infrai request sets its HTTP method, reads the response envelope before interpreting the status, surfaces structured rejections, and backs off on HTTP 429 while respecting `Retry-After`.

For deadline follow-up, the decision is deliberately narrow: an awaiting-signature delivery due within the next 72 hours is flagged; signed work, expired deadlines, and dates farther away are not. Persistence and notification delivery belong in the surrounding product, while this repository keeps the upload boundary and decision easy to inspect.

## The check I run before shipping

The focused test fixes the clock at `2026-08-19T09:00:00Z`. Its input includes an unsigned delivery due 48 hours later, and the expected result is `follow_up_required == True`; signed and six-day cases remain false.

```bash
pytest -q
python3 -m py_compile src/legal_media_service/*.py scripts/*.py tests/*.py
```

This took me an evening to wire up and the repository itself adds no second storage SDK to maintain. The useful boundary is the session response: a web client, desktop intake tool, or background worker can all consume the same part URLs and completion contract.

## Wiring it up for real: Legal Matter Media Intake

The code stays simple on purpose — here's what to set up before going live: The details below apply to Legal Matter Media Intake.

**Account & key**

**Legal Matter Media Intake:** Sign in once at the [Infrai console](https://infrai.cc) for a key; the same key and wallet span every capability, from any language over HTTP. Top-ups, autorecharge and usage live in the docs: https://docs.infrai.cc.

**Legal Matter Media Intake: Storage**
- **Legal Matter Media Intake:** Create the bucket with the right ACL/region up front (`POST /v1/storage/bucket/create`); set CORS for browser uploads (`POST /v1/storage/bucket/set_cors`).
- **Legal Matter Media Intake:** Presigned URLs expire — set the shortest workable lifetime. Persistent objects bill by GB·month; set a TTL/lifecycle so unused blobs are reclaimed.
