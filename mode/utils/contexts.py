"""Context manager utilities."""
import typing
from types import TracebackType
from typing import Any, Type

if typing.TYPE_CHECKING:
    from ._py37_contextlib import (
        AbstractAsyncContextManager,
        AsyncExitStack,
        ExitStack,
        asynccontextmanager,
        nullcontext,
    )
else:
    try:  # pragma: no cover
        from contextlib import (
            AbstractAsyncContextManager,
            AsyncExitStack,
            ExitStack,
            asynccontextmanager,
            nullcontext,
        )
    except ImportError:  # pragma: no cover
        from ._py37_contextlib import (
            AbstractAsyncContextManager,
            AsyncExitStack,
            ExitStack,
            asynccontextmanager,
            nullcontext,
        )

__all__ = [
    "AbstractAsyncContextManager",
    "AsyncExitStack",
    "ExitStack",
    "asynccontextmanager",
    "nullcontext",
    "asyncnullcontext",
]


# Sphinx complains that stdlib is badly formatted :P

AsyncExitStack.__doc__ = """
Async context manager for dynamic management of a stack of exit
callbacks.

Example:
    >>> async with AsyncExitStack() as stack:
    ...    connections = [await stack.enter_async_context(get_connection())
    ...                   for i in range(5)]
    ...    # All opened connections will automatically be released at the
    ...    # end of the async with statement, even if attempts to open a
    ...    # connection later in the list raise an exception.
"""
asynccontextmanager.__doc__ = "asynccontextmanager decorator."
nullcontext.__doc__ = "Context that does nothing."


class asyncnullcontext(AbstractAsyncContextManager):
    """Context for async-with statement doing nothing."""

    enter_result: Any

    def __init__(self, enter_result: Any = None) -> None:
        self.enter_result = enter_result

    async def __aenter__(self) -> Any:
        return self.enter_result

    async def __aexit__(
        self,
        exc_type: Type[BaseException] = None,
        exc_val: BaseException = None,
        exc_tb: TracebackType = None,
    ) -> None:
        ...
