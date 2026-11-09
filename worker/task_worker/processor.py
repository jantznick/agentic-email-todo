from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

import redis

from task_worker.ack import send_ack_email
from task_worker.config import Settings
from task_worker.idempotency import IdempotencyStore
from task_worker.llm import LLMClient
from task_worker.vikunja import VikunjaClient

logger = logging.getLogger(__name__)


class JobProcessor:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._redis = redis.Redis.from_url(settings.redis_url, decode_responses=True)
        self._idempotency = IdempotencyStore(
            settings.redis_url, settings.redis_processed_key
        )
        self._llm = LLMClient(settings)
        self._vikunja = VikunjaClient(settings)

    def ping(self) -> bool:
        return bool(self._redis.ping())

    def process_job(self, job: dict[str, Any]) -> None:
        message_id = str(job.get("message_id") or "").strip()
        if not message_id:
            logger.error("Job missing message_id; dropping: %s", job)
            return

        if self._idempotency.already_processed(message_id):
            logger.info("Skipping already-processed message_id=%s", message_id)
            return

        # Worker assumes queued jobs are already allowlisted by ingest.
        extracted = self._llm.extract_task(job)
        created = self._vikunja.create_task_from_extraction(
            extracted,
            source_message_id=message_id,
            source_from=str(job.get("from_header") or job.get("from") or ""),
            source_subject=str(job.get("subject") or ""),
        )

        # Mark before SMTP so ack failures never create duplicate tasks on retry.
        self._idempotency.mark_processed(message_id)

        to_address = str(job.get("from") or "").strip()
        if to_address:
            try:
                asyncio.run(
                    send_ack_email(
                        self._settings,
                        to_address=to_address,
                        original_subject=str(job.get("subject") or ""),
                        original_message_id=message_id,
                        created=created,
                    )
                )
            except Exception:
                logger.exception(
                    "SMTP ack failed for message_id=%s task_id=%s "
                    "(task was still created)",
                    message_id,
                    created.id,
                )
        else:
            logger.warning(
                "No from address on job message_id=%s; skipping SMTP ack",
                message_id,
            )

        logger.info(
            "Done message_id=%s task_id=%s url=%s",
            message_id,
            created.id,
            created.url,
        )

    def run_forever(self, *, should_stop=None) -> None:
        queue_key = self._settings.redis_queue_key
        logger.info("Worker listening on Redis list %s", queue_key)
        while True:
            if should_stop and should_stop():
                logger.info("Stop requested; exiting worker loop")
                return
            item = self._redis.brpop(queue_key, timeout=5)
            if not item:
                continue
            _, raw = item
            try:
                job = json.loads(raw)
            except json.JSONDecodeError:
                logger.exception("Invalid JSON job payload: %r", raw[:500])
                continue
            try:
                self.process_job(job)
            except Exception:
                logger.exception(
                    "Failed processing job message_id=%s; requeueing",
                    job.get("message_id"),
                )
                # Requeue once at the head so transient API blips can retry.
                # Idempotency prevents duplicate Vikunja tasks after partial success
                # only if mark_processed already ran; if create succeeded but mark
                # failed, a duplicate is possible — acceptable for v1 with logs.
                try:
                    self._redis.lpush(queue_key, raw)
                except Exception:
                    logger.exception("Failed to requeue job")
                import time

                time.sleep(5)
