from datetime import datetime, timedelta, timezone
from uuid import UUID

from legal_media_service.matter_intake import (
    DEFAULT_BUCKET,
    MatterUploadRequest,
    get_bucket_name,
    needs_deadline_follow_up,
)


NOW = datetime(2026, 8, 19, 9, 0, tzinfo=timezone.utc)


def request_with(status: str, due_at: datetime) -> MatterUploadRequest:
    return MatterUploadRequest(
        matter_id="MATTER-2048",
        delivery_id=UUID("e42277f1-72b8-4eb9-a15e-c92163b18743"),
        filename="signed-deposition.mp4",
        content_type="video/mp4",
        size_bytes=24_000_000,
        signature_status=status,
        response_due_at=due_at,
    )


def test_only_unsigned_delivery_near_deadline_needs_follow_up() -> None:
    awaiting = request_with("awaiting_signature", NOW + timedelta(hours=48))
    already_signed = request_with("signed", NOW + timedelta(hours=48))
    later = request_with("awaiting_signature", NOW + timedelta(days=6))

    assert needs_deadline_follow_up(awaiting, NOW) is True
    assert needs_deadline_follow_up(already_signed, NOW) is False
    assert needs_deadline_follow_up(later, NOW) is False


def test_bucket_name_can_be_overridden_for_unique_startup(monkeypatch) -> None:
    monkeypatch.delenv("INFRAI_BUCKET_NAME", raising=False)
    assert get_bucket_name() == DEFAULT_BUCKET

    monkeypatch.setenv("INFRAI_BUCKET_NAME", "legal-matter-media-unique")
    assert get_bucket_name() == "legal-matter-media-unique"
