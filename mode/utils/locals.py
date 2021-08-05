"""Implements thread-local stack using :class:`ContextVar` (:pep:`567`).

This is a reimplementation of the local stack as used by Flask, Werkzeug,
Celery, and other libraries to keep a thread-local stack of objects.

- Supports typing:

    .. sourcecode:: python

        request_stack: LocalStack[Request] = LocalStack()
"""

from contextlib import contextmanager
from contextvars import ContextVar
from typing import Generator, Generic, List, Optional, Sequence, TypeVar

__all__ = ["LocalStack"]

# LocalStack is a generic type,
# so for a stack keeping track of web requests you may define:
#
#   requests: LocalStack[Request]
#
# If the stack is a ``List[T]``, then the type variable T denotes the
# type this stack contains.
T = TypeVar("T")


class LocalStack(Generic[T]):
    """LocalStack.

    Manage state per coroutine (also thread safe).

    Most famously used probably in Flask to keep track of the current
    request object.
    """

    _stack: ContextVar[Optional[List[T]]]

    def __init__(self) -> None:
        self._stack = ContextVar("_stack")

    # XXX mypy bug; when fixed type Generator, should be ContextManager.
    @contextmanager
    def push(self, obj: T) -> Generator[None, None, None]:
        """Push a new item to the stack."""
        self.push_without_automatic_cleanup(obj)
        try:
            yield
        finally:
            self.pop()

    def push_without_automatic_cleanup(self, obj: T) -> None:
        stack = self._stack.get(None)
        if stack is None:
            stack = []
            self._stack.set(stack)
        stack.append(obj)

    def pop(self) -> Optional[T]:
        """Remove the topmost item from the stack.

        Note:
            Will return the old value or `None` if the stack was already empty.
        """
        stack = self._stack.get(None)
        if stack is None:
            return None
        else:
            size = len(stack)
            if not size:
                self._stack.set(None)
                return None
            elif size == 1:
                item = stack[-1]
                self._stack.set(None)
            else:
                item = stack.pop()
            return item

    def __len__(self) -> int:
        stack = self._stack.get(None)
        return len(stack) if stack else 0

    @property
    def stack(self) -> Sequence[T]:
        # read-only version, do not modify
        return self._stack.get(None) or []

    @property
    def top(self) -> Optional[T]:
        """Return the topmost item on the stack.

        Does not remove it from the stack.

        Note:
            If the stack is empty, :const:`None` is returned.
        """
        stack = self._stack.get(None)
        return stack[-1] if stack else None
