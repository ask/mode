import pytest

from mode.utils.contexts import asyncnullcontext


@pytest.mark.asyncio
async def test_asyncnullcontext():
    ctx = asyncnullcontext(enter_result=30)
    async with ctx as value:
        assert value == 30
