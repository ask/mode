"""AsyncIO Timers."""
import asyncio
from itertools import count
from time import perf_counter
from typing import AsyncIterator, Awaitable, Callable, Iterator

from .utils.logging import get_logger
from .utils.times import Seconds, want_seconds

__all__ = ["Timer"]

MAX_DRIFT_PERCENT: float = 0.30
MAX_DRIFT_CEILING: float = 1.2

ClockArg = Callable[[], float]
SleepArg = Callable[[float], Awaitable[None]]

logger = get_logger(__name__)


class Timer:
    """Timer state."""

    interval: Seconds
    interval_s: float

    max_drift: float
    min_interval_s: float
    max_interval_s: float

    last_wakeup_at: float
    last_yield_at: float
    iteration: int

    def __init__(
        self,
        interval: Seconds,
        *,
        max_drift_correction: float = 0.1,
        name: str = "",
        clock: ClockArg = perf_counter,
        sleep: SleepArg = asyncio.sleep
    ) -> None:
        self.interval = interval
        self.max_drift_correction = max_drift_correction
        self.name = name
        self.clock: ClockArg = clock
        self.sleep: SleepArg = sleep
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
        self.last_wakeup_at = self.epoch
        # time of last timer run, only including the time
        # spent sleeping, not the time running timer callbacks.
        self.last_yield_at = self.epoch

        self.iteration = 0
        self.drifting = 0
        self.drifting_early = 0
        self.drifting_late = 0
        self.overlaps = 0

    async def __aiter__(self) -> AsyncIterator[float]:
        for _ in count():
            sleep_time = self.tick()
            await self.sleep(sleep_time)
            self.on_before_yield()
            yield sleep_time
        else:  # pragma: no cover
            pass  # never exits

    def adjust_interval(self, drift: float) -> float:
        interval_s = self.interval_s
        interval_with_drift = interval_s + drift
        if interval_with_drift > interval_s:
            return min(interval_with_drift, self.max_interval_s)
        elif interval_with_drift < interval_s:
            return max(interval_with_drift, self.min_interval_s)
        else:
            return interval_s

    def tick(self) -> float:
        interval_s = self.interval_s
        now = self.clock()
        if self.last_yield_at == self.epoch:
            self.last_wakeup_at = now
            return interval_s
        since_epoch = now - self.epoch
        time_spent_sleeping = self.last_yield_at - self.last_wakeup_at
        time_spent_yielding = now - self.last_wakeup_at - time_spent_sleeping
        drift = interval_s - time_spent_sleeping

        new_interval = self.adjust_interval(drift)

        if interval_s >= 1.0 and abs(drift) >= self.max_drift:
            self.drifting += 1
            if drift < 0:
                self.drifting_late += 1
                logger.info(
                    "Timer %s woke up too late, with a drift of +%r "
                    "runtime=%r sleeptime=%r",
                    self.name,
                    abs(drift),
                    time_spent_yielding,
                    time_spent_sleeping,
                )
            else:
                self.drifting_early += 1
                logger.info(
                    "Timer %s woke up too early, with a drift of -%r "
                    "runtime=%r sleeptime=%r",
                    self.name,
                    abs(drift),
                    time_spent_yielding,
                    time_spent_sleeping,
                )
        else:
            logger.debug(
                "Timer %s woke up - iteration=%r "
                "time_spent_sleeping=%r drift=%r "
                "new_interval=%r since_epoch=%r",
                self.name,
                self.iteration,
                time_spent_sleeping,
                drift,
                new_interval,
                since_epoch,
            )

        if time_spent_yielding > interval_s:
            self.overlaps += 1
            logger.warning(
                "Timer %s is overlapping (interval=%r runtime=%r)",
                self.name,
                self.interval,
                time_spent_yielding,
            )

        self.iteration += 1
        self.last_wakeup_at = now

        return new_interval

    def on_before_yield(self) -> None:
        self.last_yield_at = self.clock()


def timer_intervals(  # XXX deprecated
    interval: Seconds,
    max_drift_correction: float = 0.1,
    name: str = "",
    clock: ClockArg = perf_counter,
) -> Iterator[float]:
    """Generate timer sleep times.

    Note: This function is deprecated, please use :func:`itertimer`
    instead (this function also sleeps and calculates sleep time correctly.)

    """
    state = Timer(
        interval, max_drift_correction=max_drift_correction, name=name, clock=clock
    )
    for _ in count():
        sleep_time = state.tick()
        state.on_before_yield()  # includes callback time.
        yield sleep_time
    else:  # pragma: no cover
        pass  # never exits
