from __future__ import annotations

import os
from dataclasses import dataclass


def _require(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"Missing required env var: {name}")
    return value


def _bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    imap_host: str
    imap_port: int
    imap_user: str
    imap_pass: str
    imap_folder: str
    imap_processed_folder: str
    imap_quarantine_folder: str
    imap_poll_interval: int
    allowlist_emails: frozenset[str]
    redis_url: str
    redis_queue_key: str
    log_level: str
    attachment_text_max_chars: int


def load_settings() -> Settings:
    allowlist_raw = _require("ALLOWLIST_EMAILS")
    allowlist = frozenset(
        addr.strip().lower()
        for addr in allowlist_raw.split(",")
        if addr.strip()
    )
    if not allowlist:
        raise RuntimeError("ALLOWLIST_EMAILS must contain at least one address")

    return Settings(
        imap_host=_require("IMAP_HOST"),
        imap_port=int(os.getenv("IMAP_PORT", "993")),
        imap_user=_require("IMAP_USER"),
        imap_pass=_require("IMAP_PASS"),
        imap_folder=os.getenv("IMAP_FOLDER", "INBOX").strip() or "INBOX",
        imap_processed_folder=os.getenv("IMAP_PROCESSED_FOLDER", "Processed").strip()
        or "Processed",
        imap_quarantine_folder=os.getenv(
            "IMAP_QUARANTINE_FOLDER", "Quarantine"
        ).strip()
        or "Quarantine",
        imap_poll_interval=int(os.getenv("IMAP_POLL_INTERVAL", "60")),
        allowlist_emails=allowlist,
        redis_url=os.getenv("REDIS_URL", "redis://localhost:6379/0").strip(),
        redis_queue_key=os.getenv("REDIS_QUEUE_KEY", "email_todo:jobs").strip(),
        log_level=os.getenv("LOG_LEVEL", "INFO").strip().upper() or "INFO",
        attachment_text_max_chars=int(
            os.getenv("ATTACHMENT_TEXT_MAX_CHARS", "4000")
        ),
    )
