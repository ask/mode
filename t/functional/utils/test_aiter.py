from typing import AsyncIterable
from mode.utils.aiter import aenumerate, aiter, anext
import pytest


class AIT(AsyncIterable):

    async def __aiter__(self):
        for i in range(10):
            yield i


@pytest.mark.asyncio
async def test_aenumerate():
    it = (a async for a in aenumerate(aiter([1, 2, 3, 4, 5])))
    assert await anext(it) == (0, 1)
    assert await anext(it) == (1, 2)
    assert await anext(it) == (2, 3)
    assert await anext(it) == (3, 4)
    assert await anext(it) == (4, 5)
    with pytest.raises(StopAsyncIteration):
        await anext(it)
    sentinel = object()
    assert await anext(it, sentinel) is sentinel
    assert repr(aiter([1, 2, 3, 4]))


def test_aiter__not_an_iterator():
    with pytest.raises(TypeError):
        aiter(object())


@pytest.mark.asyncio
async def test_aiter__AsyncIterable():
    it = aiter(AIT())
    assert await anext(it) == 0
    assert await anext(it) == 1
    assert await anext(it) == 2
