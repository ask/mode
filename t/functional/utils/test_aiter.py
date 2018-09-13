from typing import AsyncIterable
from mode.utils.aiter import (
    aenumerate,
    aiter,
    alist,
    anext,
    arange,
    aslice,
    chunks,
)
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


@pytest.mark.asyncio
async def test_arange():
    assert [x async for x in arange(10)] == list(range(10))
    assert [x async for x in arange(2, 10)] == list(range(2, 10))
    assert [x async for x in arange(0, 100, 10)] == list(range(0, 100, 10))

    assert 3 in arange(10)
    assert 3 not in arange(2)

    assert arange(10).count(1) == 1
    assert arange(10).index(3) == 3


@pytest.mark.asyncio
async def test_aslice():
    assert await alist(aslice(arange(100), 10)) == list(range(10))
    assert await alist(aslice(arange(100), 10, 20)) == list(range(10, 20))


@pytest.mark.asyncio
@pytest.mark.parametrize('range_n,n,expected', [
    (11, 2, [[0, 1], [2, 3], [4, 5], [6, 7], [8, 9], [10]]),
    (11, 3, [[0, 1, 2], [3, 4, 5], [6, 7, 8], [9, 10]]),
    (10, 2, [[0, 1], [2, 3], [4, 5], [6, 7], [8, 9]]),
])
async def test_chunks(range_n, n, expected):
    _chunks = []
    async for chunk in chunks(aiter(arange(range_n)), n):
        _chunks.append(chunk)
    assert _chunks == expected

    assert [c async for c in chunks(arange(range_n), n)] == expected


def test_aiter__not_an_iterator():
    with pytest.raises(TypeError):
        aiter(object())


@pytest.mark.asyncio
async def test_aiter__AsyncIterable():
    it = aiter(AIT())
    assert await anext(it) == 0
    assert await anext(it) == 1
    assert await anext(it) == 2
