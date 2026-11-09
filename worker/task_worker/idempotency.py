from __future__ import annotations

import logging

import redis

logger = logging.getLogger(__name__)


class IdempotencyStore:
    """Track processed Message-IDs in a Redis set so retries are skipped."""

    def __init__(self, redis_url: str, key: str) -> None:
        self._client = redis.Redis.from_url(redis_url, decode_responses=True)
        self._key = key

    def ping(self) -> bool:
        return bool(self._client.ping())

    def already_processed(self, message_id: str) -> bool:
        return bool(self._client.sismember(self._key, message_id))

    def mark_processed(self, message_id: str) -> None:
        self._client.sadd(self._key, message_id)
        logger.debug("Marked message_id=%s processed", message_id)
