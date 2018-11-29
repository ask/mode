"""Async I/O Future utilities."""
import asyncio
from inspect import isawaitable
from typing import Any, Callable, Optional, Type

# These used to be here, now moved to .queues
from .queues import FlowControlEvent, FlowControlQueue  # noqa: F401

__all__ = [
    'done_future',
    'maybe_async',
    'stampede',
    'notify',
]


class StampedeWrapper:
    fut: asyncio.Future = None

    def __init__(self,
                 fun: Callable,
                 *args: Any,
                 loop: asyncio.AbstractEventLoop = None,
                 **kwargs: Any) -> None:
        self.fun = fun
        self.args = args
        self.kwargs = kwargs
        self.loop = loop

    async def __call__(self) -> Any:
        fut = self.fut
        if fut is None:
            fut = self.fut = asyncio.Future(loop=self.loop)
            try:
                result = await self.fun(*self.args, **self.kwargs)
                fut.set_result(result)
            except asyncio.CancelledError:
                fut.cancel()
                raise
            finally:
                self.fut = None
            return result
        else:
            if fut.done():
                return fut.result()
            return await fut


class stampede:
    """Descriptor for cached async operations providing stampede protection.

    See also thundering herd problem.

    Adding the decorator to an async callable method:

    Examples:
        Here's an example coroutine method connecting a network client:

        .. sourcecode:: python

            class Client:

                @stampede
                async def maybe_connect(self):
                    await self._connect()

                async def _connect(self):
                    return Connection()

        In the above example, if multiple coroutines call ``maybe_connect``
        at the same time, then only one of them will actually perform the
        operation. The rest of the coroutines will wait for the result,
        and return it once the first caller returns.
    """

    def __init__(self, fget: Callable, *, doc: str = None) -> None:
        self.__get = fget
        self.__doc__ = doc or fget.__doc__
        self.__name__ = fget.__name__
        self.__module__ = fget.__module__

    def __get__(self, obj: Any, type: Type = None) -> Any:
        if obj is None:
            return self
        try:
            w = obj.__dict__[self.__name__]
        except KeyError:
            w = obj.__dict__[self.__name__] = StampedeWrapper(self.__get, obj)
        return w


def done_future(result: Any = None, *,
                loop: asyncio.AbstractEventLoop = None) -> asyncio.Future:
    """Return :class:`asyncio.Future` that is already evaluated."""
    f = (loop or asyncio.get_event_loop()).create_future()
    f.set_result(result)
    return f


async def maybe_async(res: Any) -> Any:
    """Await future if argument is Awaitable.

    Examples:
        >>> await maybe_async(regular_function(arg))
        >>> await maybe_async(async_function(arg))
    """
    if isawaitable(res):
        return await res
    return res


def notify(fut: Optional[asyncio.Future], result: Any = None) -> None:
    # can be used to turn a Future into a lockless, single-consumer condition,
    # for multi-consumer use asyncio.Condition
    if fut is not None and not fut.done():
        fut.set_result(result)
