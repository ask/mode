"""AsyncIO Timers."""
import asyncio
from itertools import count
from time import perf_counter
from typing import AsyncIterator, Awaitable, Callable, Iterator
from .utils.logging import get_logger
from .utils.times import Seconds, want_seconds

__all__ = ['Clock', 'itertimer']

MAX_DRIFT_PERCENT: float = 0.90
MAX_DRIFT_CEILING: float = 1.2

ClockArg = Callable[[], float]
SleepArg = Callable[[float], Awaitable[None]]

logger = get_logger(__name__)


async def itertimer(
        interval: Seconds,
        max_drift_correction: float = 0.1,
        name: str = '',
        clock: ClockArg = perf_counter,
        sleep: SleepArg = asyncio.sleep) -> AsyncIterator[float]:
    """Forever running timer, sleeping at intervals.

    Example:
        >>> async def my_timer(interval=1.0):
        ...     # wait interval before running first time.
        ...     await asyncio.sleep(interval)
        ...     async for time_slept in itertimer(1.0, name='my_timer'):
        ...         # do something that takes a while.
        ...         # You do not have to sleep here, as itertimer
        ...         # already sleeps for every iteration.
    """
    state = Clock(interval,
                  max_drift_correction=max_drift_correction,
                  name=name,
                  clock=clock)
    for _ in count():
        sleep_time = state.update()
        await sleep(sleep_time)
        state.on_sleep_end()
        yield sleep_time
    else:  # pragma: no cover
        pass  # never exits


class Clock:
    """Timer state."""

    interval: Seconds
    interval_s: float

    max_drift: float
    min_interval_s: float
    max_interval_s: float

    last_run_at: float
    sleep_end_at: float
    iteration: int

    def __init__(self, interval: Seconds, *,
                 max_drift_correction: float = 0.1,
                 name: str = '',
                 clock: ClockArg = perf_counter) -> None:
        self.interval = interval
        self.max_drift_correction = max_drift_correction
        self.name = name
        self.clock: ClockArg = clock
        interval_s = self.interval_s = want_seconds(interval)

        # Log when drift exceeds this number
        self.max_drift = min(interval_s * MAX_DRIFT_PERCENT, MAX_DRIFT_CEILING)

        if interval_s > self.max_drift_correction:
            self.min_interval_s = interval_s - self.max_drift_correction
            self.max_interval_s = interval_s + self.max_drift_correction
        else:
            self.min_interval_s = self.max_interval_s = interval_s

        # If the loop calls asyncio.sleep(interval)
        # it will always wake up a little bit late, and can eventually
        # drift, Using the algorithm below we will usually
        # wake up slightly early instead (usually around 0.001s),
        # and often actually end up being able to correct the drift
        # entirely around 20% of the time. Also add entropy
        # to timers.

        # first yield interval
        # usually callers will sleep before starting first timer
        self.epoch = self.clock()
        # time of last timer run, updated after each run.
        self.last_run_at = self.epoch - interval_s
        # time of last timer run, only including the time
        # spent sleeping, not the time running timer callbacks.
        self.sleep_end_at = self.epoch - interval_s

        self.iteration = 0

    def update(self) -> float:
        now = self.clock()
        interval_s = self.interval_s
        since_epoch = now - self.epoch
        time_spent = now - self.sleep_end_at
        if time_spent < 0.01:
            # protect against overflow with very small numbers.
            time_spent = interval_s
        callback_time = self.last_run_at - self.sleep_end_at
        drift = interval_s - time_spent
        abs_drift = abs(drift)
        drift_time = interval_s + drift

        if drift_time > interval_s:
            sleep_time = min(drift_time, self.max_interval_s)
        elif drift_time < interval_s:
            sleep_time = max(drift_time, self.min_interval_s)
        else:
            sleep_time = interval_s

        if interval_s >= 1.0 and abs_drift >= self.max_drift:
            if drift < 0:
                logger.info(
                    'Timer %s woke up too late, with a drift of +%r',
                    self.name, abs_drift)
            else:
                logger.info(
                    'Timer %s woke up too early, with a drift of -%r',
                    self.name, abs_drift)
        else:
            logger.debug(
                'Timer %s woke up - iteration=%r '
                'time_spent=%r drift=%r sleep_time=%r since_epoch=%r',
                self.name, self.iteration,
                time_spent, drift, sleep_time, since_epoch)

        if callback_time > interval_s:
            logger.warning(
                'Timer %s is overlapping (interval=%r runtime=%r)',
                self.name, self.interval, callback_time)

        self.iteration += 1
        self.last_run_at = now

        return sleep_time

    def on_sleep_end(self) -> None:
        self.sleep_end_at = self.clock()


def timer_intervals(  # XXX deprecated
        interval: Seconds,
        max_drift_correction: float = 0.1,
        name: str = '',
        clock: ClockArg = perf_counter) -> Iterator[float]:
    """Generate timer sleep times.

    Note: This function is deprecated, please use :func:`itertimer`
    instead (this function also sleeps and calculates sleep time correctly.)

    """
    state = Clock(interval,
                  max_drift_correction=max_drift_correction,
                  name=name,
                  clock=clock)
    for _ in count():
        sleep_time = state.update()
        yield sleep_time
        state.on_sleep_end()  # includes callback time.
    else:  # pragma: no cover
        pass  # never exits
