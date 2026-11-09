from __future__ import annotations

import logging
import time
from typing import Callable

from imap_tools import AND, MailBox, MailMessageFlags

from email_ingest.allowlist import extract_from_address, is_allowlisted
from email_ingest.config import Settings
from email_ingest.parser import build_job_payload
from email_ingest.queue import JobQueue

logger = logging.getLogger(__name__)


def _ensure_folder(mailbox: MailBox, folder: str) -> None:
    existing = {f.name for f in mailbox.folder.list()}
    if folder not in existing:
        logger.info("Creating IMAP folder %r", folder)
        mailbox.folder.create(folder)


def process_message(
    mailbox: MailBox,
    msg,
    settings: Settings,
    queue: JobQueue,
) -> None:
    """Allowlist gate FIRST, then parse/enqueue or quarantine."""
    from_header = msg.from_ or ""
    from_addr = extract_from_address(from_header)
    uid = msg.uid

    if not is_allowlisted(from_header, settings.allowlist_emails):
        logger.warning(
            "Discarding non-allowlisted mail from=%r uid=%s subject=%r",
            from_addr,
            uid,
            msg.subject,
        )
        try:
            mailbox.move(uid, settings.imap_quarantine_folder)
        except Exception:
            logger.exception(
                "Failed to move uid=%s to quarantine; marking seen and deleting",
                uid,
            )
            mailbox.flag(uid, MailMessageFlags.SEEN, True)
            mailbox.delete(uid)
        return

    payload = build_job_payload(
        msg,
        attachment_text_max_chars=settings.attachment_text_max_chars,
    )
    queue.enqueue(payload)

    mailbox.flag(uid, MailMessageFlags.SEEN, True)
    mailbox.move(uid, settings.imap_processed_folder)
    logger.info(
        "Processed allowlisted mail from=%r uid=%s message_id=%s",
        from_addr,
        uid,
        payload.get("message_id"),
    )


def fetch_and_process(mailbox: MailBox, settings: Settings, queue: JobQueue) -> int:
    """Fetch unseen messages from the configured folder and process each."""
    mailbox.folder.set(settings.imap_folder)
    count = 0
    for msg in mailbox.fetch(AND(seen=False), mark_seen=False):
        try:
            process_message(mailbox, msg, settings, queue)
            count += 1
        except Exception:
            logger.exception(
                "Failed processing uid=%s subject=%r",
                getattr(msg, "uid", None),
                getattr(msg, "subject", None),
            )
    return count


def run_poll_loop(
    settings: Settings,
    queue: JobQueue,
    *,
    should_stop: Callable[[], bool] | None = None,
) -> None:
    """
    Connect via IMAP and poll for new mail.

    Uses a poll loop (IDLE optional enhancement). Mark/move after each message
    so restarts do not re-fire endlessly.
    """
    logger.info(
        "Connecting to IMAP %s:%s as %s folder=%s",
        settings.imap_host,
        settings.imap_port,
        settings.imap_user,
        settings.imap_folder,
    )

    while True:
        if should_stop and should_stop():
            logger.info("Stop requested; exiting poll loop")
            return

        try:
            with MailBox(settings.imap_host, settings.imap_port).login(
                settings.imap_user,
                settings.imap_pass,
                initial_folder=settings.imap_folder,
            ) as mailbox:
                _ensure_folder(mailbox, settings.imap_processed_folder)
                _ensure_folder(mailbox, settings.imap_quarantine_folder)
                mailbox.folder.set(settings.imap_folder)

                while True:
                    if should_stop and should_stop():
                        logger.info("Stop requested; exiting poll loop")
                        return

                    processed = fetch_and_process(mailbox, settings, queue)
                    if processed:
                        logger.info("Processed %d message(s) this cycle", processed)

                    # Prefer IDLE when the server supports it; fall back to sleep.
                    idle_ok = False
                    try:
                        idle = mailbox.idle
                        # imap-tools: IdleManager as context manager or .wait()
                        if hasattr(idle, "__enter__"):
                            with idle as idle_manager:
                                responses = idle_manager.wait(
                                    timeout=settings.imap_poll_interval
                                )
                        else:
                            responses = idle.wait(
                                timeout=settings.imap_poll_interval
                            )
                        idle_ok = True
                        if responses:
                            logger.debug("IDLE wakeup: %s", responses)
                    except Exception as idle_exc:
                        logger.debug(
                            "IDLE unavailable (%s); sleeping %ss",
                            idle_exc,
                            settings.imap_poll_interval,
                        )

                    if not idle_ok:
                        time.sleep(settings.imap_poll_interval)


        except Exception:
            logger.exception(
                "IMAP session error; reconnecting in %ss",
                settings.imap_poll_interval,
            )
            time.sleep(settings.imap_poll_interval)
