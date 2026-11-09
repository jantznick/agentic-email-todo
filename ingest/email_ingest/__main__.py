from __future__ import annotations

import logging
import signal
import sys

from dotenv import load_dotenv

from email_ingest.config import load_settings
from email_ingest.imap_client import run_poll_loop
from email_ingest.queue import JobQueue


def main() -> int:
    load_dotenv()
    settings = load_settings()

    logging.basicConfig(
        level=getattr(logging, settings.log_level, logging.INFO),
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
        stream=sys.stdout,
    )
    logger = logging.getLogger("email_ingest")

    stop = {"flag": False}

    def _handle_signal(signum: int, _frame) -> None:
        logger.info("Received signal %s; shutting down", signum)
        stop["flag"] = True

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    queue = JobQueue(settings.redis_url, settings.redis_queue_key)
    logger.info("Waiting for Redis at %s ...", settings.redis_url)
    while not stop["flag"]:
        try:
            if queue.ping():
                break
        except Exception as exc:
            logger.warning("Redis not ready (%s); retrying...", exc)
        import time

        time.sleep(2)

    if stop["flag"]:
        return 0

    logger.info(
        "email-ingest starting; allowlist=%s queue=%s",
        sorted(settings.allowlist_emails),
        settings.redis_queue_key,
    )
    run_poll_loop(settings, queue, should_stop=lambda: stop["flag"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
