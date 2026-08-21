from __future__ import annotations

from datetime import datetime, timezone
from functools import lru_cache
import os
from typing import Annotated, Literal
from uuid import UUID

from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel, Field

from .infrai_client import InfraiClient, InfraiError


DEFAULT_BUCKET = "legal-matter-media"
PART_SIZE_BYTES = 8 * 1024 * 1024


def get_bucket_name() -> str:
    return os.environ.get("INFRAI_BUCKET_NAME", DEFAULT_BUCKET)


class MatterUploadRequest(BaseModel):
    matter_id: Annotated[str, Field(min_length=1, max_length=80, pattern=r"^[A-Za-z0-9_-]+$")]
    delivery_id: UUID
    filename: Annotated[str, Field(min_length=1, max_length=180)]
    content_type: Annotated[str, Field(min_length=1, max_length=120)]
    size_bytes: Annotated[int, Field(gt=0, le=5 * 1024 * 1024 * 1024)]
    signature_status: Literal["awaiting_signature", "signed"]
    response_due_at: datetime


class UploadPart(BaseModel):
    part_number: int
    upload_url: str


class MatterUploadSession(BaseModel):
    matter_id: str
    delivery_id: UUID
    object_key: str
    upload_id: str
    part_size_bytes: int
    parts: list[UploadPart]
    follow_up_required: bool


class CompletedPart(BaseModel):
    part_number: Annotated[int, Field(ge=1)]
    etag: Annotated[str, Field(min_length=1)]


class CompleteDeliveryRequest(BaseModel):
    matter_id: Annotated[str, Field(min_length=1, max_length=80, pattern=r"^[A-Za-z0-9_-]+$")]
    delivery_id: UUID
    upload_id: Annotated[str, Field(min_length=1)]
    parts: Annotated[list[CompletedPart], Field(min_length=1)]


class DeliveryReceipt(BaseModel):
    matter_id: str
    delivery_id: UUID
    state: Literal["signed_document_delivered"]
    object_key: str


def needs_deadline_follow_up(request: MatterUploadRequest, now: datetime) -> bool:
    due = request.response_due_at
    if due.tzinfo is None:
        due = due.replace(tzinfo=timezone.utc)
    return request.signature_status == "awaiting_signature" and 0 <= (due - now).total_seconds() <= 72 * 3600


@lru_cache
def get_infrai() -> InfraiClient:
    return InfraiClient()


def _map_infrai_error(error: InfraiError) -> HTTPException:
    status = error.status_code if 400 <= error.status_code < 500 else 502
    return HTTPException(status_code=status, detail={"code": error.code, "message": str(error)})


app = FastAPI(title="Legal matter media intake")


@app.on_event("startup")
def prepare_storage() -> None:
    infrai = get_infrai()
    bucket = get_bucket_name()
    try:
        infrai.storage.bucket.create(
            {"name": bucket, "idempotency_key": f"legal-matter-media-bucket-v1-{bucket}"}
        )
    except InfraiError as error:
        raise _map_infrai_error(error) from error


@app.post("/matter-uploads", response_model=MatterUploadSession)
def start_matter_upload(
    request: MatterUploadRequest, infrai: InfraiClient = Depends(get_infrai)
) -> MatterUploadSession:
    safe_name = request.filename.replace("/", "_").replace("\\", "_")
    object_key = f"matters/{request.matter_id}/signed-deliveries/{request.delivery_id}/{safe_name}"
    operation_key = f"delivery-{request.delivery_id}"
    try:
        created = infrai.storage.multipart.create(
            get_bucket_name(),
            {
                "key": object_key,
                "content_type": request.content_type,
                "idempotency_key": operation_key,
            },
        )
        upload_id = str(created["upload_id"])
        count = (request.size_bytes + PART_SIZE_BYTES - 1) // PART_SIZE_BYTES
        parts = [
            UploadPart(
                part_number=number,
                upload_url=str(infrai.storage.multipart.presign_part(upload_id, number)["url"]),
            )
            for number in range(1, count + 1)
        ]
    except InfraiError as error:
        raise _map_infrai_error(error) from error

    now = datetime.now(timezone.utc)
    return MatterUploadSession(
        matter_id=request.matter_id,
        delivery_id=request.delivery_id,
        object_key=object_key,
        upload_id=upload_id,
        part_size_bytes=PART_SIZE_BYTES,
        parts=parts,
        follow_up_required=needs_deadline_follow_up(request, now),
    )


@app.post("/matter-uploads/complete", response_model=DeliveryReceipt)
def complete_signed_delivery(
    request: CompleteDeliveryRequest, infrai: InfraiClient = Depends(get_infrai)
) -> DeliveryReceipt:
    ordered_parts = sorted(request.parts, key=lambda part: part.part_number)
    try:
        completed = infrai.storage.multipart.complete(
            request.upload_id,
            {
                "parts": [part.model_dump() for part in ordered_parts],
                "idempotency_key": f"complete-{request.delivery_id}",
            },
        )
    except InfraiError as error:
        raise _map_infrai_error(error) from error
    return DeliveryReceipt(
        matter_id=request.matter_id,
        delivery_id=request.delivery_id,
        state="signed_document_delivered",
        object_key=str(completed["key"]),
    )
