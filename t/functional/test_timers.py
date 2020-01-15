import asyncio
import pytest
from mode.timers import itertimer
from mode.utils.mocks import AsyncMock, Mock, patch


@pytest.mark.asyncio
async def test_itertimer():
    i = 0
    async for sleep_time in itertimer(0.1, sleep=asyncio.sleep):
        assert sleep_time == pytest.approx(0.1, 2e-1)
        if i > 10:
            break
        i += 1


@pytest.mark.asyncio
async def test_itertimer__too_late():
    clock = Mock()
    clock_values = [
        9.0, 9.0, 10.0, 10.0, 11.0, 11.0, 12.0, 12.0, 13.0, 16.0,
        17.0, 17.0, 18.0, 18.0, 19.0, 19.0, 20.0, 20.0, 20.0]

    yield_values = clock_values
    clock.side_effect = yield_values
    with patch('mode.timers.logger') as logger:
        i = 0
        async for sleep_time in itertimer(1.0,
                                          clock=clock,
                                          sleep=AsyncMock()):
            assert sleep_time == (0.9 if i == 4 else 1.0)
            if i >= 8:
                break
            i += 1
        logger.info.assert_called_once()


@pytest.mark.asyncio
async def test_itertimer__too_early():
    clock = Mock()
    clock.return_value = 9.0
    clock_values = iter([
        10.0, 11.0, 12.0, 13.0, 13.1, 14.1, 15.0, 16.0, 17.0])
    #                          ^- too fast
    with patch('mode.timers.logger') as logger:
        i = 0
        sleep = AsyncMock()
        async for sleep_time in itertimer(1.0, clock=clock, sleep=sleep):
            clock.return_value = next(clock_values)
            assert sleep_time == (1.1 if i == 5 else 1.0)
            if i >= 6:
                break
            i += 1
        logger.info.assert_called_once()
