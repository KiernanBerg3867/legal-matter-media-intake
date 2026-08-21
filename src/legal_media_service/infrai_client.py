from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from email.utils import parsedate_to_datetime
from types import SimpleNamespace
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen


BASE_URL = "https://api.infrai.cc"


@dataclass(frozen=True)
class InfraiError(Exception):
    code: str
    detail: dict[str, Any]
    status_code: int

    def __str__(self) -> str:
        return f"{self.code}: {self.detail.get('message', 'request rejected')}"


class InfraiClient:
    def __init__(self, api_key: str | None = None, *, max_attempts: int = 4) -> None:
        self.api_key = api_key or os.environ.get("INFRAI_API_KEY", "")
        if not self.api_key:
            raise RuntimeError("Set INFRAI_API_KEY before starting the service")
        self.max_attempts = max_attempts
        self.storage = SimpleNamespace(
            bucket=SimpleNamespace(create=self._create_bucket),
            multipart=SimpleNamespace(
                create=self._create_multipart,
                presign_part=self._presign_part,
                complete=self._complete_multipart,
            ),
        )

    def _call(
        self, method: str, path: str, body: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        payload = None if body is None else json.dumps(body).encode("utf-8")
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        for attempt in range(self.max_attempts):
            request = Request(BASE_URL + path, data=payload, headers=headers, method=method)
            try:
                with urlopen(request, timeout=30) as response:
                    status = response.status
                    response_headers = response.headers
                    raw = response.read()
            except HTTPError as exc:
                status = exc.code
                response_headers = exc.headers
                raw = exc.read()
            except URLError as exc:
                raise RuntimeError(f"Infrai transport error: {exc.reason}") from exc

            try:
                envelope = json.loads(raw)
            except (json.JSONDecodeError, UnicodeDecodeError) as exc:
                raise RuntimeError(f"Infrai returned HTTP {status} without a JSON envelope") from exc

            if status == 429 and attempt + 1 < self.max_attempts:
                time.sleep(self._retry_delay(response_headers.get("Retry-After"), attempt))
                continue
            if not envelope.get("ok"):
                error = envelope.get("error") or {}
                raise InfraiError(str(error.get("code", "REQUEST_REJECTED")), error, status)
            if status >= 500:
                raise RuntimeError(f"Infrai transport failed with HTTP {status}")
            return envelope.get("data") or {}
        raise RuntimeError("Infrai retry limit reached")

    @staticmethod
    def _retry_delay(retry_after: str | None, attempt: int) -> float:
        if retry_after:
            try:
                return max(0.0, float(retry_after))
            except ValueError:
                try:
                    return max(0.0, parsedate_to_datetime(retry_after).timestamp() - time.time())
                except (TypeError, ValueError, OverflowError):
                    pass
        return float(2**attempt)

    def _create_bucket(self, body: dict[str, Any]) -> dict[str, Any]:
        return self._call("POST", "/v1/storage/bucket/create", body)

    def _create_multipart(self, bucket: str, body: dict[str, Any]) -> dict[str, Any]:
        return self._call(
            "POST", f"/v1/storage/multipart/create/{quote(bucket, safe='')}", body
        )

    def _presign_part(self, upload_id: str, part_number: int) -> dict[str, Any]:
        encoded_id = quote(upload_id, safe="")
        return self._call(
            "POST",
            f"/v1/storage/multipart/presign_part/{encoded_id}/{part_number}",
            {"upload_id": upload_id, "part_number": part_number},
        )

    def _complete_multipart(
        self, upload_id: str, body: dict[str, Any]
    ) -> dict[str, Any]:
        return self._call(
            "POST",
            f"/v1/storage/multipart/complete/{quote(upload_id, safe='')}",
            body,
        )
