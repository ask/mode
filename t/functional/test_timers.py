import asyncio
import sys
from contextlib import asynccontextmanager
from functools import reduce
from itertools import chain
from typing import List, NamedTuple, Tuple
from unittest.mock import ANY, Mock, patch

if sys.version_info < (3, 8):
    from mock.mock import AsyncMock
else:
    from unittest.mock import AsyncMock

import pytest

from mode.timers import Timer
from mode.utils.aiter import aslice


@pytest.mark.asyncio
async def test_Timer_real_run():
    i = 0
    async for sleep_time in Timer(0.1, sleep=asyncio.sleep):
        assert sleep_time == pytest.approx(0.1, 2e-1)
        if i > 10:
            break
        i += 1


class Interval(NamedTuple):
    interval: float
    wakeup_time: float
    yield_time: float
    expected_new_interval: float


class test_Timer:

    # first clock value
    epoch = 9.0

    # the timer interval (how long we sleep between each iteration)
    interval = 1.0

    # how much we skew drifting intervals by.
    # early test will do (interval - skew)
    # late test will do (interval + skew)
    skew = 0.3

    # how long it takes to yield
    # Yield gives control back to the event loop, runs other tasks
    # and calls any callback associated with the timer, so this
    # time could be long in some cases.
    default_yield_s = 0.01

    @pytest.fixture()
    def clock(self):
        clock = Mock()
        clock.return_value = self.epoch
        return clock

    @pytest.fixture()
    def sleep(self):
        return AsyncMock()

    @pytest.fixture()
    def timer(self, *, clock, sleep) -> Timer:
        return Timer(
            self.interval,
            name="test",
            clock=clock,
            sleep=sleep,
        )

    @pytest.fixture()
    def first_interval(self):
        return self.new_interval()

    @pytest.mark.asyncio
    async def test_too_early(self, *, clock, timer, first_interval):
        interval = self.interval
        skew = self.skew
        intervals = [
            first_interval,  # 1st interval
            (None, None),  # 2nd interval
            (None, None),  # 3rd interval
            (interval - skew, None),  # 4th interval: sleep too short
            (None, interval + skew),  # 5th interval: overlaps
            (None, None),  # 6th interval
        ]
        async with self.assert_timer(timer, clock, intervals) as logger:
            logger.info.assert_called_once_with(
                "Timer %s woke up too early, with a drift "
                "of -%r runtime=%r sleeptime=%r",
                "test",
                ANY,
                ANY,
                ANY,
            )
            assert timer.drifting == 1
            assert timer.drifting_early == 1
            assert not timer.drifting_late

    @pytest.mark.asyncio
    async def test_too_late(self, *, clock, timer, first_interval):
        interval = self.interval
        skew = self.skew
        intervals = [
            first_interval,  # 1st interval
            (None, None),  # 2nd interval
            (None, None),  # 3rd interval
            (interval + skew, None),  # 4th interval: sleep too long
            (None, interval + skew),  # 5th interval: overlaps
            (None, None),  # 6th interval
        ]
        async with self.assert_timer(timer, clock, intervals) as logger:
            logger.info.assert_called_once_with(
                "Timer %s woke up too late, with a drift "
                "of +%r runtime=%r sleeptime=%r",
                "test",
                ANY,
                ANY,
                ANY,
            )
            assert timer.drifting == 1
            assert timer.drifting_late == 1
            assert not timer.drifting_early

    @asynccontextmanager
    async def assert_timer(self, timer, clock, interval_tuples):
        intervals = self.build_intervals(timer, *interval_tuples)
        print(intervals)
        clock_values = self.to_clock_values(*intervals)
        assert len(clock_values) == len(intervals) * 2
        clock.side_effect = clock_values

        with patch("mode.timers.logger") as logger:
            await self.assert_intervals(timer, intervals)
            yield logger

    def new_interval(
        self,
        interval: float = None,
        wakeup_time: float = None,
        yield_time: float = None,
        expected_new_interval: float = None,
    ) -> Interval:
        if interval is None:
            interval = self.interval
        if wakeup_time is None:
            wakeup_time = self.epoch + interval
        if yield_time is None:
            yield_time = wakeup_time + interval + self.default_yield_s
        if expected_new_interval is None:
            expected_new_interval = interval
        return Interval(
            interval,
            wakeup_time,
            yield_time,
            expected_new_interval,
        )

    def to_next_interval(
        self,
        timer: Timer,
        interval: Interval,
        sleep_time: float = None,
        yield_time: float = 0.1,
        expected_new_interval: float = None,
    ) -> Interval:
        if sleep_time is None:
            sleep_time = interval.interval + 0.001
        if yield_time is None:
            yield_time = self.default_yield_s
        next_wakeup_time = interval.yield_time + self.default_yield_s
        next_yield_time = next_wakeup_time + sleep_time
        time_spent_sleeping = interval.yield_time - interval.wakeup_time
        drift = interval.interval - time_spent_sleeping
        if expected_new_interval is None:
            expected_new_interval = timer.adjust_interval(drift)
        return Interval(
            interval=interval.interval,
            wakeup_time=next_wakeup_time,
            yield_time=next_yield_time,
            expected_new_interval=expected_new_interval,
        )

    def interval_to_clock_sequence(self, interval: Interval) -> List[float]:
        # Timer calls clock() twice per iteration,
        # so in an interval this provides the clock for wakeup time
        # and the yield time.
        return [interval.wakeup_time, interval.yield_time]

    def to_clock_values(self, *intervals: Interval) -> List[float]:
        return list(chain(*map(self.interval_to_clock_sequence, intervals)))

    def build_intervals(
        self, timer: Timer, first_interval: Interval, *values: Tuple[float, float]
    ) -> List[Interval]:
        """Build intervals from tuples of ``(sleep_time, yield_time)``.

        If a tuple is missing (is None), then default values
        will be taken from the previous interval.
        """

        intervals = [first_interval]

        def on_reduce(
            previous_interval: Interval, tup: Tuple[float, float]
        ) -> Interval:
            sleep_time, yield_time = tup
            next_interval = self.to_next_interval(
                timer,
                previous_interval,
                sleep_time=sleep_time,
                yield_time=yield_time,
            )
            intervals.append(next_interval)
            return next_interval

        reduce(on_reduce, values, first_interval)
        return intervals

    async def assert_intervals(self, timer: Timer, intervals: List[Interval]) -> None:
        assert await self.consume_timer(timer, limit=len(intervals)) == [
            interval.expected_new_interval for interval in intervals
        ]

    async def consume_timer(self, timer: Timer, limit: int) -> List[float]:
        return [sleep_time async for sleep_time in aslice(timer, 0, limit)]


class test_Timer_1s_half_second_skew(test_Timer):
    skew = 0.5


class test_Timer_30s_five_second_skew(test_Timer):
    interval = 30.0
    skew = 5.0


class test_Timer_30s_five_second_skew_late_epoch(test_Timer):
    epoch = 300000.0
    interval = 30.0
    skew = 5.0
