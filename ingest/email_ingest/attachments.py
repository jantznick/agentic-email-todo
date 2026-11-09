from __future__ import annotations

import logging
from io import BytesIO
from typing import Any

logger = logging.getLogger(__name__)

TEXT_MIME_PREFIXES = ("text/",)
TEXT_EXTENSIONS = {
    ".txt",
    ".md",
    ".csv",
    ".json",
    ".xml",
    ".yaml",
    ".yml",
    ".log",
    ".html",
    ".htm",
}


def _decode_text(payload: bytes, max_chars: int) -> str:
    for encoding in ("utf-8", "latin-1"):
        try:
            text = payload.decode(encoding, errors="replace")
            return text[:max_chars]
        except Exception:
            continue
    return ""


def _extract_pdf_text(payload: bytes, max_chars: int) -> str:
    try:
        from pypdf import PdfReader
    except ImportError:
        logger.warning("pypdf not available; skipping PDF text extract")
        return ""

    try:
        reader = PdfReader(BytesIO(payload))
        chunks: list[str] = []
        total = 0
        for page in reader.pages:
            page_text = page.extract_text() or ""
            if not page_text:
                continue
            remaining = max_chars - total
            if remaining <= 0:
                break
            snippet = page_text[:remaining]
            chunks.append(snippet)
            total += len(snippet)
        return "\n".join(chunks)
    except Exception:
        logger.exception("Failed to extract PDF text")
        return ""


def summarize_attachments(
    attachments: list[Any],
    *,
    max_chars: int = 4000,
) -> list[dict[str, Any]]:
    """
    Build attachment summary stubs for the Redis job.

    Attachments are never uploaded to Vikunja — only filename, mime, size,
    and a cheap text extract (plain text / PDF) when available.
    """
    summaries: list[dict[str, Any]] = []
    for att in attachments:
        filename = getattr(att, "filename", None) or "unnamed"
        content_type = (
            getattr(att, "content_type", None)
            or getattr(att, "content_disposition", None)
            or "application/octet-stream"
        )
        payload: bytes = getattr(att, "payload", b"") or b""
        size = len(payload)
        text_extract = ""

        lower_name = filename.lower()
        is_text = content_type.startswith(TEXT_MIME_PREFIXES) or any(
            lower_name.endswith(ext) for ext in TEXT_EXTENSIONS
        )
        is_pdf = content_type == "application/pdf" or lower_name.endswith(".pdf")

        if is_text and payload:
            text_extract = _decode_text(payload, max_chars)
        elif is_pdf and payload:
            text_extract = _extract_pdf_text(payload, max_chars)

        summaries.append(
            {
                "filename": filename,
                "content_type": content_type,
                "size_bytes": size,
                "text_extract": text_extract,
            }
        )
    return summaries
