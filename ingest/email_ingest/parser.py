from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from email_ingest.allowlist import extract_from_address
from email_ingest.attachments import summarize_attachments


def _as_iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.isoformat()


def build_job_payload(
    msg: Any,
    *,
    attachment_text_max_chars: int,
) -> dict[str, Any]:
    """
    Normalize an imap-tools MailMessage into the Redis job schema.

    Schema:
      {
        "schema_version": 1,
        "message_id": str,
        "from": str,           # bare email
        "from_header": str,    # raw From header
        "to": [str, ...],
        "cc": [str, ...],
        "subject": str,
        "date": str | null,    # ISO-8601
        "text_body": str,
        "html_body": str,
        "attachments": [
          {
            "filename": str,
            "content_type": str,
            "size_bytes": int,
            "text_extract": str
          }
        ],
        "imap_uid": str | int | null,
        "enqueued_at": str     # ISO-8601 UTC
      }
    """
    from_header = msg.from_ or ""
    to_addrs = list(msg.to or [])
    cc_addrs = list(getattr(msg, "cc", None) or [])

    text_body = (msg.text or "").strip()
    html_body = (msg.html or "").strip()

    attachments = summarize_attachments(
        list(msg.attachments or []),
        max_chars=attachment_text_max_chars,
    )

    message_id = (msg.headers.get("message-id") or [""])[0].strip()
    if not message_id:
        # Fallback synthetic id so worker idempotency still works
        uid = getattr(msg, "uid", None)
        message_id = f"synthetic-{uid or 'unknown'}-{msg.date or 'nodate'}"

    return {
        "schema_version": 1,
        "message_id": message_id,
        "from": extract_from_address(from_header),
        "from_header": from_header,
        "to": to_addrs,
        "cc": cc_addrs,
        "subject": msg.subject or "",
        "date": _as_iso(msg.date),
        "text_body": text_body,
        "html_body": html_body,
        "attachments": attachments,
        "imap_uid": getattr(msg, "uid", None),
        "enqueued_at": datetime.now(timezone.utc).isoformat(),
    }
