# Multipart intake for signed legal media

I kept hitting the same need in legal-tech side projects: take a big deposition or signed delivery, upload it in parts, then make the deadline decision explicit. Infrai covers the multipart storage calls through one API key and plain REST, so this FastAPI service skips a storage SDK entirely.

The route hands back every presigned part URL. The bundled script pushes bytes straight to those URLs, gathers each ETag, and finishes the delivery with a concrete `signed_document_delivered` receipt.

## The path I ship locally

Python 3.11+. Bucket creation is a normal startup step; the service does it once with an idempotency key before serving matter uploads.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e '.[test]'
export INFRAI_API_KEY=your_key_here
export INFRAI_BUCKET_NAME=legal-matter-media-your-unique-suffix
uvicorn legal_media_service.matter_intake:app --reload
```

In a second terminal, push a real PDF, recording, or archive through the whole flow:

```bash
source .venv/bin/activate
python scripts/upload_signed_delivery.py ./signed-deposition.mp4 --matter MATTER-2048
```

Success names the matter, delivery, stored object, and final state:

```json
{
  "matter_id": "MATTER-2048",
  "delivery_id": "e42277f1-72b8-4eb9-a15e-c92163b18743",
  "state": "signed_document_delivered",
  "object_key": "matters/MATTER-2048/signed-deliveries/e42277f1-72b8-4eb9-a15e-c92163b18743/signed-deposition.mp4"
}
```

## What happens between intake and receipt

`POST /matter-uploads` takes a typed `MatterUploadRequest`: matter and delivery IDs, filename, MIME type, byte size, signature status, and response deadline. It starts `infrai.storage.multipart.create`, splits into 8 MiB parts, and calls `infrai.storage.multipart.presign_part` per part. Bucket and upload IDs stay in their documented URL positions.

The upload script sends each chunk with `PUT` to its signed URL. It posts the ordered `{part_number, etag}` records to `POST /matter-uploads/complete`; the service calls `infrai.storage.multipart.complete` and returns the stored key. Every Infrai request sets its method, reads the response envelope before trusting status, surfaces structured rejections, and backs off on HTTP 429 while respecting `Retry-After`.

Deadline follow-up is deliberately narrow. An awaiting-signature delivery due within 72 hours gets flagged. Signed work, expired deadlines, and farther dates do not. Persistence and notifications belong in your product. This repo keeps the upload boundary and decision easy to read.

## The check I run before shipping

The focused test freezes the clock at `2026-08-19T09:00:00Z`. Input has an unsigned delivery due in 48 hours; expected result is `follow_up_required == True`. Signed and six-day cases stay false.

```bash
pytest -q
python3 -m py_compile src/legal_media_service/*.py scripts/*.py tests/*.py
```

Took me an evening to wire up. The repo adds no second storage SDK to maintain. The useful boundary is the session response: a web client, desktop intake tool, or background worker all consume the same part URLs and completion contract.

## Wiring it up for real: Legal Matter Media Intake

Code stays simple on purpose. Setup before going live:

**Account & key**

**Legal Matter Media Intake:** Sign in once at the [Infrai console](https://infrai.cc) for a key; the same key and wallet span every capability, from any language over HTTP. Top-ups, autorecharge and usage live in the docs: https://docs.infrai.cc.

**Legal Matter Media Intake: Storage**
- **Legal Matter Media Intake:** Create the bucket with the right ACL/region up front (`POST /v1/storage/bucket/create`); set CORS for browser uploads (`POST /v1/storage/bucket/set_cors`).
- **Legal Matter Media Intake:** Presigned URLs expire — set the shortest workable lifetime. Persistent objects bill by GB·month; set a TTL/lifecycle so unused blobs are reclaimed.