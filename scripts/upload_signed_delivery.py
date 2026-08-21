from __future__ import annotations

import argparse
import json
import mimetypes
from pathlib import Path
from urllib.request import Request, urlopen
from uuid import uuid4


def post_json(url: str, body: dict[str, object]) -> dict[str, object]:
    request = Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(request, timeout=30) as response:
        return json.load(response)


def main() -> None:
    parser = argparse.ArgumentParser(description="Upload one signed legal delivery in parts")
    parser.add_argument("file", type=Path)
    parser.add_argument("--matter", required=True)
    parser.add_argument("--service", default="http://127.0.0.1:8000")
    args = parser.parse_args()

    delivery_id = str(uuid4())
    content_type = mimetypes.guess_type(args.file.name)[0] or "application/octet-stream"
    session = post_json(
        f"{args.service}/matter-uploads",
        {
            "matter_id": args.matter,
            "delivery_id": delivery_id,
            "filename": args.file.name,
            "content_type": content_type,
            "size_bytes": args.file.stat().st_size,
            "signature_status": "signed",
            "response_due_at": "2030-01-15T17:00:00Z",
        },
    )

    completed_parts: list[dict[str, object]] = []
    with args.file.open("rb") as source:
        for part in session["parts"]:
            chunk = source.read(int(session["part_size_bytes"]))
            upload = Request(part["upload_url"], data=chunk, method="PUT")
            with urlopen(upload, timeout=120) as response:
                etag = response.headers["ETag"].strip('"')
            completed_parts.append({"part_number": part["part_number"], "etag": etag})

    receipt = post_json(
        f"{args.service}/matter-uploads/complete",
        {
            "matter_id": args.matter,
            "delivery_id": delivery_id,
            "upload_id": session["upload_id"],
            "parts": completed_parts,
        },
    )
    print(json.dumps(receipt, indent=2))


if __name__ == "__main__":
    main()
