"""Stage timings without request, provider or exception payloads."""
from contextlib import contextmanager
import logging
import time

log = logging.getLogger(__name__)


@contextmanager
def stage_timing(stage, *, request_key, user_id):
    started = time.monotonic()
    error_type = None
    try:
        yield
    except BaseException as exc:
        # Include cancellation, but never exception text or chained payloads.
        error_type = type(exc).__name__
        raise
    finally:
        log.info("Copilot stage=%s duration_ms=%s request_key=%s user_id=%s outcome=%s error_type=%s",
                 stage, int((time.monotonic() - started) * 1000), request_key, user_id,
                 "failed" if error_type else "success", error_type)
