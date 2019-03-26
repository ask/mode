"""AsyncIO Timers."""
from itertools import count
from time import perf_counter
from typing import Callable, Iterator
from .utils.logging import get_logger
from .utils.times import Seconds, want_seconds

__all__ = ['timer_intervals']

MAX_DRIFT_PERCENT: float = 0.30
MAX_DRIFT_CEILING: float = 0.8

ClockArg = Callable[[], float]

logger = get_logger(__name__)


def timer_intervals(interval: Seconds,
                    max_drift_correction: float = 0.1,
                    name: str = '',
                    clock: ClockArg = perf_counter) -> Iterator[float]:
    """Generate timer sleep times.

    Example:
        >>> async def my_timer(interval=1.0):
        ...     # wait interval before running first time.
        ...     await asyncio.sleep(interval)
        ...     for sleep_time in timer_intervals(1.0, name='my_timer'):
        ...         # do something that takes a while.
        ...         await asyncio.sleep(sleep_time)
    """
    interval_s = want_seconds(interval)

    # Log when drift exceeds this number
    max_drift = min(interval_s * MAX_DRIFT_PERCENT, MAX_DRIFT_CEILING)

    min_interval_s = interval_s - max_drift_correction
    max_interval_s = interval_s + max_drift_correction

    # If the loop calls asyncio.sleep(interval)
    # it will always wake up a little bit late, and can eventually
    # drift, Using the algorithm below we will usually
    # wake up slightly early instead (usually around 0.001s),
    # and often actually end up being able to correct the drift
    # entirely around 20% of the time. Also add entropy
    # to timers.

    # first yield interval
    # usually callers will sleep before starting first timer
    epoch = clock()
    # time of last timer run, updated after each run.
    last_run_at = epoch - interval_s

    for i in count():
        now = clock()
        since_epoch = now - epoch
        time_spent = now - last_run_at
        drift = interval_s - time_spent
        drift_time = interval_s + drift

        if drift_time >= interval_s:
            sleep_time = min(drift_time, max_interval_s)
        else:
            sleep_time = max(drift_time, min_interval_s)

        if drift >= max_drift:
            logger.info(
                'Timer %s woke up too late, with a drift of %r', name, drift)
        else:
            logger.debug(
                'Timer %s woke up - iteration=%r '
                'time_spent=%r drift=%r sleep_time=%r since_epoch=%r',
                name, i, time_spent, drift, sleep_time, since_epoch)

        last_run_at = clock()
        yield sleep_time
