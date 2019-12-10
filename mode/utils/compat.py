"""Compatibility utilities."""
from typing import AnyStr, IO

from .contexts import asyncnullcontext, nullcontext
from .futures import current_task
from .typing import AsyncContextManager, ChainMap, Counter, Deque, NoReturn


__all__ = [
    'AsyncContextManager',  # XXX moved to .typing
    'ChainMap',             # XXX moved to .typing
    'Counter',              # XXX moved to .typing
    'Deque',                # XXX moved to .typing
    'NoReturn',             # XXX moved to .typing
    'DummyContext',
    'OrderedDict',
    'want_bytes',
    'want_str',
    'isatty',
    'current_task',         # XXX moved to .futures
]

#: Dictionaries are ordered by default in Python 3.6
OrderedDict = dict


def want_bytes(s: AnyStr) -> bytes:
    """Convert string to bytes."""
    if isinstance(s, str):
        return s.encode()
    return s


def want_str(s: AnyStr) -> str:
    """Convert bytes to string."""
    if isinstance(s, bytes):
        return s.decode()
    return s


def isatty(fh: IO) -> bool:
    """Return True if fh has a controlling terminal.

    Notes:
        Use with e.g. :data:`sys.stdin`.
    """
    try:
        return fh.isatty()
    except AttributeError:
        return False


class DummyContext(nullcontext, asyncnullcontext):
    """Context for with-statement doing nothing."""
    # XXX deprecated, use nullcontext or asyncnullcontext
