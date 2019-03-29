"""Implements thread-local stack.

This is a reimplementation of the local stack as used by Celery, Flask
and other libraries to keep a thread-local stack of contexts.

- Uses three levels to support both threads and coroutines:

    ``threading.local -> ContextVar -> List``

- Supports typing:

    .. sourcecode:: python

        request_stack: LocalStack[Request] = LocalStack()
"""
import threading
import typing
from contextlib import AbstractContextManager
from contextvars import ContextVar
from types import TracebackType
from typing import Generic, List, Optional, Sequence, Type, TypeVar

T = TypeVar('T')
T_contra = TypeVar('T_contra', contravariant=True)


class PopAfterContext(AbstractContextManager):
    """Context manager that pops from stack when exiting."""

    def __init__(self, stack: 'LocalStack'):
        self.stack = stack

    def __enter__(self) -> 'PopAfterContext':
        return self

    def __exit__(self,
                 exc_type: Type[BaseException] = None,
                 exc_val: BaseException = None,
                 exc_tb: TracebackType = None) -> Optional[bool]:
        self.stack.pop()
        return None


class LocalStack(Generic[T]):
    """Thread-safe ContextVar that manages a stack."""

    if typing.TYPE_CHECKING:
        _local: threading.local[ContextVar[T]]

    def __init__(self) -> None:
        self._local = threading.local()

    def push(self, obj: T_contra) -> PopAfterContext:
        """Push a new item to the stack."""
        context = self._get_context()
        stack = context.get(None)
        if stack is None:
            stack = []
            context.set(stack)
        stack.append(obj)
        return PopAfterContext(self)

    def _get_context(self) -> ContextVar[T]:
        context = getattr(self._local, 'stack', None)
        if context is None:
            self._local.stack = context = ContextVar('_stack')
        return context

    def _get_stack(self) -> Optional[List[T]]:
        return self._get_context().get(None)

    def pop(self) -> T:
        """Remove the topmost item from the stack.

        Note:
            Will return the old value or `None` if the stack was already empty.
        """
        context = self._get_context()
        stack = context.get(None)
        if stack is None:
            return None

        if len(stack) == 1:
            context.set(None)
        return stack.pop()

    def __len__(self) -> int:
        stack = self._get_stack()
        return len(stack) if stack else 0

    @property
    def stack(self) -> Sequence[T]:
        # read-only version, do not modify
        return self._get_stack() or []

    @property
    def top(self) -> Optional[T]:
        """The topmost item on the stack.

        Note:
            If the stack is empty, :const:`None` is returned.
        """
        context = getattr(self._local, 'stack', None)
        if context is not None:
            stack = context.get(None)
            if stack is not None:
                return stack[-1]
        return None
