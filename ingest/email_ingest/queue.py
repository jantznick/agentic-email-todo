from __future__ import annotations

import json
import logging
from typing import Any

import redis

logger = logging.getLogger(__name__)


class JobQueue:
    def __init__(self, redis_url: str, queue_key: str) -> None:
        self._client = redis.Redis.from_url(redis_url, decode_responses=True)
        self._queue_key = queue_key

    def ping(self) -> bool:
        return bool(self._client.ping())

    def enqueue(self, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False)
        self._client.lpush(self._queue_key, body)
        logger.info(
            "Enqueued job message_id=%s subject=%r",
            payload.get("message_id"),
            payload.get("subject"),
        )
