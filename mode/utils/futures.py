"""Async I/O Future utilities."""
import asyncio
from inspect import isawaitable
from typing import Any, Callable, Optional, Set, Type

# These used to be here, now moved to .queues
from .queues import FlowControlEvent, FlowControlQueue  # noqa: F401
from .typing import NoReturn

try:  # pragma: no cover
    from asyncio import all_tasks  # type: ignore
except ImportError:  # pragma: no cover

    def all_tasks(loop: asyncio.AbstractEventLoop) -> Set[asyncio.Task]:  # noqa
        return asyncio.Task.all_tasks(loop=loop)


try:  # pragma: no cover
    from asyncio import current_task  # type: ignore
except ImportError:  # pragma: no cover
    current_task = asyncio.Task.current_task

__all__ = [
    "all_tasks",
    "current_task",
    "done_future",
    "maybe_async",
    "maybe_cancel",
    "maybe_set_exception",
    "maybe_set_result",
    "stampede",
    "notify",
]


class StampedeWrapper:
    fut: Optional[asyncio.Future] = None

    def __init__(
        self,
        fun: Callable,
        *args: Any,
        loop: asyncio.AbstractEventLoop = None,
        **kwargs: Any
    ) -> None:
        self.fun = fun
        self.args = args
        self.kwargs = kwargs
        self.loop = loop

    async def __call__(self) -> Any:
        await asyncio.sleep(0)
        fut = self.fut
        if fut is None:
            fut = asyncio.Future(loop=self.loop)
            self.fut = fut
            try:
                result = await self.fun(*self.args, **self.kwargs)
                fut.set_result(result)
                await asyncio.sleep(0)
            except asyncio.CancelledError:
                fut.cancel()
                raise
            finally:
                await asyncio.sleep(0)
                self.fut = None
            return result
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
        self.__wrapped__ = fget

    def __call__(self, *args: Any, **kwargs: Any) -> NoReturn:
        # here to support inspect.signature
        raise NotImplementedError()

    def __get__(self, obj: Any, type: Type = None) -> Any:
        if obj is None:
            return self
        try:
            w = obj.__dict__[self.__name__]
        except KeyError:
            w = obj.__dict__[self.__name__] = StampedeWrapper(self.__get, obj)
        return w


def done_future(
    result: Any = None, *, loop: asyncio.AbstractEventLoop = None
) -> asyncio.Future:
    """Return :class:`asyncio.Future` that is already evaluated."""
    f = (loop or asyncio.get_event_loop_policy().get_event_loop()).create_future()
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


def maybe_cancel(fut: Optional[asyncio.Future]) -> bool:
    """Cancel future if it is cancellable."""
    if fut is not None and not fut.done():
        return fut.cancel()
    return False


def maybe_set_exception(fut: Optional[asyncio.Future], exc: BaseException) -> bool:
    """Set future exception if not already done."""
    if fut is not None and not fut.done():
        fut.set_exception(exc)
        return True
    return False


def maybe_set_result(fut: Optional[asyncio.Future], result: Any) -> bool:
    """Set future result if not already done."""
    if fut is not None and not fut.done():
        fut.set_result(result)
        return True
    return False


def notify(fut: Optional[asyncio.Future], result: Any = None) -> None:
    """Set :class:`asyncio.Future` result if future exists and is not done."""
    # can be used to turn a Future into a lockless, single-consumer condition,
    # for multi-consumer use asyncio.Condition
    if fut is not None and not fut.done():
        fut.set_result(result)
