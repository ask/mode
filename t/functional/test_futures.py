import asyncio
import pytest
from mode.utils.futures import StampedeWrapper
from mode.utils.mocks import Mock


@pytest.mark.asyncio
async def test_StampedeWrapper_concurrent():
    t = Mock()

    async def wrapped():
        await asyncio.sleep(0.5)
        return t()

    x = StampedeWrapper(wrapped)

    async def caller():
        return await x()

    assert all(
        ret is t.return_value
        for ret in await asyncio.gather(*[caller() for i in range(10)]))

    t.assert_called_once_with()


@pytest.mark.asyncio
async def test_StampedeWrapper_sequential():
    t = Mock()

    async def wrapped():
        return t()

    x = StampedeWrapper(wrapped)

    for _ in range(10):
        assert await x() is t.return_value

    assert t.call_count == 10
