import asyncio
import pytest
from mode.timers import timer_intervals
from mode.utils.mocks import Mock, patch


@pytest.mark.asyncio
async def test_timer_intervals():
    i = 0
    for sleep_time in timer_intervals(0.1):
        assert sleep_time == pytest.approx(0.1, 2e-1)
        await asyncio.sleep(sleep_time)
        if i > 10:
            break
        i += 1


@pytest.mark.asyncio
async def test_timer_intervals__too_late():
    clock = Mock()
    clock.return_value = 9.0
    clock_values = iter([
        10.0, 11.0, 12.0, 13.0, 16.0, 17.0, 18.0, 19.0, 20.0])
    #                          ^- skips
    with patch('mode.timers.logger') as logger:
        i = 0
        for sleep_time in timer_intervals(1.0, clock=clock):
            clock.return_value = next(clock_values)
            assert sleep_time == (0.9 if i == 5 else 1.0)
            if i >= 8:
                break
            i += 1
        logger.info.assert_called_once()


@pytest.mark.asyncio
async def test_timer_intervals__too_early():
    clock = Mock()
    clock.return_value = 9.0
    clock_values = iter([
        10.0, 11.0, 12.0, 13.0, 13.1, 14.1, 15.0, 16.0, 17.0])
    #                          ^- too fast
    with patch('mode.timers.logger') as logger:
        i = 0
        for sleep_time in timer_intervals(1.0, clock=clock):
            clock.return_value = next(clock_values)
            assert sleep_time == (1.1 if i == 5 else 1.0)
            if i >= 6:
                break
            i += 1
        logger.info.assert_called_once()
