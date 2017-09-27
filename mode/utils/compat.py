"""Compatibility utilities."""
from types import TracebackType
from typing import (
    Any, AsyncContextManager, ContextManager, Optional, Type,
)

__all__ = ['DummyContext']


class DummyContext(ContextManager, AsyncContextManager):
    """Context for with-statement doing nothing."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        ...

    async def __aenter__(self) -> 'DummyContext':
        return self

    async def __aexit__(self,
                        exc_type: Type[BaseException] = None,
                        exc_val: BaseException = None,
                        exc_tb: TracebackType = None) -> Optional[bool]:
        ...

    def __enter__(self) -> 'DummyContext':
        return self

    def __exit__(self,
                 exc_type: Type[BaseException] = None,
                 exc_val: BaseException = None,
                 exc_tb: TracebackType = None) -> Optional[bool]:
        ...
