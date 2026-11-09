from __future__ import annotations

import logging
import signal
import sys
import time

from dotenv import load_dotenv

from task_worker.config import load_settings
from task_worker.processor import JobProcessor


def main() -> int:
    load_dotenv()
    settings = load_settings()

    logging.basicConfig(
        level=getattr(logging, settings.log_level, logging.INFO),
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
        stream=sys.stdout,
    )
    logger = logging.getLogger("task_worker")

    stop = {"flag": False}

    def _handle_signal(signum: int, _frame) -> None:
        logger.info("Received signal %s; shutting down", signum)
        stop["flag"] = True

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    processor = JobProcessor(settings)
    logger.info("Waiting for Redis at %s ...", settings.redis_url)
    while not stop["flag"]:
        try:
            if processor.ping():
                break
        except Exception as exc:
            logger.warning("Redis not ready (%s); retrying...", exc)
        time.sleep(2)

    if stop["flag"]:
        return 0

    logger.info(
        "task-worker starting; provider=%s model=%s fallback=%r grooming=%r",
        settings.llm_provider,
        settings.openai_model,
        settings.vikunja_fallback_project,
        settings.vikunja_needs_grooming_label,
    )
    processor.run_forever(should_stop=lambda: stop["flag"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
