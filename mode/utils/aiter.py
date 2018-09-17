"""Async iterator lost and found missing methods: aiter, anext, etc."""
import collections.abc
import sys
from functools import singledispatch
from typing import (
    Any,
    AsyncIterable,
    AsyncIterator,
    Iterable,
    Iterator,
    List,
    Tuple,
)

__all__ = [
    'aenumerate',
    'aiter',
    'alist',
    'anext',
    'arange',
    'aslice',
    'chunks',
]


async def aenumerate(it: AsyncIterable[Any],
                     start: int = 0) -> AsyncIterator[Tuple[int, Any]]:
    """``async for`` version of ``enumerate``."""
    i = start
    async for item in it:
        yield i, item
        i += 1


class AsyncIterWrapper(AsyncIterator):
    """Wrap regular Iterator into an AsyncIterator."""

    def __init__(self, it: Iterator) -> None:
        self._it: Iterator = it

    def __aiter__(self) -> AsyncIterator:
        return self

    async def __anext__(self) -> Any:
        try:
            return next(self._it)
        except StopIteration as exc:
            raise StopAsyncIteration() from exc

    def __repr__(self) -> str:
        return f'<{type(self).__name__}: {self._it}>'


@singledispatch
def aiter(it: Any) -> AsyncIterator:
    """Create iterator from iterable.

    Notes:
        If the object is already an iterator, the iterator
        should return self when ``__aiter__`` is called.
    """
    raise TypeError(f'{it!r} object is not an iterable')


# XXX In Py3.7: register cannot take typing.AsyncIterator
@aiter.register(collections.abc.AsyncIterable)
def _aiter_async(it: AsyncIterable) -> AsyncIterator:
    return it.__aiter__()


# XXX In Py3.7: register cannot take typing.Iterable
@aiter.register(collections.abc.Iterable)
def _aiter_iter(it: Iterable) -> AsyncIterator:
    return AsyncIterWrapper(iter(it)).__aiter__()


async def anext(it: AsyncIterator, *default: Any) -> Any:
    """Get next value from async iterator, or `default` if empty.

    Raises
        :exc:`StopAsyncIteration`: if default is not defined and
            the async iterator is fully consumed.
    """
    if default:
        try:
            return await it.__anext__()
        except StopAsyncIteration:
            return default[0]
    return await it.__anext__()


class _ARangeIterator(AsyncIterator[int]):

    def __init__(self, parent: 'arange', it: Iterator[int]) -> None:
        self.parent = arange
        self.it = it

    def __aiter__(self) -> AsyncIterator[int]:
        return self

    async def __anext__(self) -> int:
        try:
            return next(self.it)
        except StopIteration:
            raise StopAsyncIteration()


class arange(AsyncIterable[int]):

    def __init__(self, *slice_args: int, **slice_kwargs: Any) -> None:
        s = slice(*slice_args, **slice_kwargs)
        self.start = s.start or 0
        self.stop = s.stop
        self.step = s.step or 1
        self._range = range(self.start, self.stop, self.step)

    def count(self, n: int) -> int:
        return self._range.count(n)

    def index(self, n: int) -> int:
        return self._range.index(n)

    def __contains__(self, n: int) -> bool:
        return n in self._range

    def __aiter__(self) -> AsyncIterator[int]:
        return _ARangeIterator(self, iter(self._range))


async def alist(ait):
    return [x async for x in ait]


async def aslice(ait, *slice_args):
    s = slice(*slice_args)
    start = s.start or 0
    stop = s.stop or sys.maxsize
    step = s.step or 1
    it = iter(range(start, stop, step))
    try:
        nexti = next(it)
        async for i, item in aenumerate(ait):
            if i == nexti:
                yield item
                nexti = next(it)
    except StopIteration:
        return


async def chunks(it: AsyncIterable, n: int) -> AsyncIterable[List]:
    """Split an async iterator into chunks with `n` elements each.

    Example:
        # n == 2
        >>> x = chunks(arange(10), 2)
        >>> [item async for item in x]
        [[0, 1], [2, 3], [4, 5], [6, 7], [8, 9], [10]]

        # n == 3
        >>> x = chunks(arange(10)), 3)
        >>> [item async for item in x]
        [[0, 1, 2], [3, 4, 5], [6, 7, 8], [9, 10]]
    """
    ait = aiter(it)
    async for item in ait:
        yield [item] + [x async for x in aslice(ait, n - 1)]
