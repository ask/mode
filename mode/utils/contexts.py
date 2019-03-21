"""Context manager utilities."""
from types import TracebackType
from typing import Any, Optional, Type

try:
    from contextlib import AbstractAsyncContextManager
    from contextlib import AsyncExitStack, ExitStack
    from contextlib import asynccontextmanager
    from contextlib import nullcontext
except ImportError:
    from ._py37_contextlib import AbstractAsyncContextManager
    from ._py37_contextlib import AsyncExitStack, ExitStack
    from ._py37_contextlib import asynccontextmanager
    from ._py37_contextlib import nullcontext

__all__ = [
    'AbstractAsyncContextManager',
    'AsyncExitStack',
    'ExitStack',
    'asynccontextmanager',
    'nullcontext',
    'asyncnullcontext',
]


class asyncnullcontext(AbstractAsyncContextManager):
    """Context for async-with statement doing nothing."""

    enter_result: Any

    def __init__(self, enter_result: Any = None) -> None:
        self.enter_result = enter_result

    async def __aenter__(self) -> 'asyncnullcontext':
        return self.enter_result

    async def __aexit__(self,
                        exc_type: Type[BaseException] = None,
                        exc_val: BaseException = None,
                        exc_tb: TracebackType = None) -> Optional[bool]:
        ...
