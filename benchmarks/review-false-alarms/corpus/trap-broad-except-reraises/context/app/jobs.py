import logging
import time

log = logging.getLogger(__name__)


def run_job(job):
    started = time.monotonic()
    try:
        result = job.execute()
    except Exception:
        log.exception("job %s failed after %.1fs", job.id, time.monotonic() - started)
        raise
    log.info("job %s finished in %.1fs", job.id, time.monotonic() - started)
    return result
