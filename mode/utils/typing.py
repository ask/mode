"""Backport of :mod:`typing` additions in Python 3.7."""
import abc
import collections
import typing
import _collections_abc
from typing import (
    Any,
    AsyncIterator,
    Dict,
    Generic,
    KT,
    MutableMapping,
    MutableSequence,
    T,
    T_co,
    T_contra,
    VT,
    V_co,
)

__all__ = [
    'AsyncContextManager',
    'AsyncGenerator',
    'ChainMap',
    'Counter',
    'Deque',
    'NoReturn',
]

if typing.TYPE_CHECKING:
    from typing import AsyncContextManager
else:
    try:
        from typing import AsyncContextManager  # noqa: F811
    except ImportError:
        @typing.no_type_check
        class AsyncContextManager(Generic[T_co]):  # noqa: F811
            """Asynchronous context manager."""

            __slots__ = ()

            async def __aenter__(self):
                return self

            @abc.abstractmethod
            async def __aexit__(self, exc_type, exc_value, traceback):
                return None

            @classmethod
            def __subclasshook__(cls, C):
                if cls is AsyncContextManager:
                    return _collections_abc._check_methods(
                        C, '__aenter__', '__aexit__')
                return NotImplemented


if typing.TYPE_CHECKING:
    from typing import AsyncGenerator
else:
    try:
        from typing import AsyncGenerator
    except ImportError:  # Python 3.6.0
        class AsyncGenerator(AsyncIterator[T_co],
                             Generic[T_co, T_contra, V_co],
                             extra=_collections_abc.AsyncGenerator):
            """Async Generator Type."""

            __slots__ = ()

            def __new__(cls, *args, **kwds):
                if typing._geqv(cls, AsyncGenerator):
                    raise TypeError(
                        'Type AsyncGenerator cannot be instantiated; '
                        'create a subclass instead')
                return typing._generic_new(
                    _collections_abc.AsyncGenerator, cls, *args, **kwds)


if typing.TYPE_CHECKING:
    from typing import ChainMap
else:
    try:
        from typing import ChainMap  # noqa: F811
    except ImportError:
        @typing.no_type_check
        class ChainMap(collections.ChainMap,  # noqa: F811
                       MutableMapping[KT, VT],
                       extra=collections.ChainMap):
            """Chain map type."""

            __slots__ = ()

            def __new__(cls, *args, **kwds):
                if typing._geqv(cls, ChainMap):
                    return collections.ChainMap(*args, **kwds)
                return typing._generic_new(
                    collections.ChainMap, cls, *args, **kwds)


if typing.TYPE_CHECKING:
    from typing import Counter
else:
    try:
        from typing import Counter  # noqa: F811
    except ImportError:
        @typing.no_type_check
        class Counter(collections.Counter,
                      Dict[T, int],
                      extra=collections.Counter):
            """Counter type."""

            __slots__ = ()

            def __new__(cls, *args, **kwds):
                if typing._geqv(cls, Counter):
                    return collections.Counter(*args, **kwds)
                return typing._generic_new(
                    collections.Counter, cls, *args, **kwds)


if typing.TYPE_CHECKING:
    from typing import Deque
else:
    try:
        from typing import Deque  # noqa: F811
    except ImportError:
        @typing.no_type_check
        class Deque(collections.deque,  # noqa: F811
                    MutableSequence[T],
                    extra=collections.deque):
            """Deque type."""

            __slots__ = ()

            def __new__(cls, *args, **kwds):
                if typing._geqv(cls, Deque):
                    return collections.deque(*args, **kwds)
                return typing._generic_new(
                    collections.deque, cls, *args, **kwds)


if typing.TYPE_CHECKING:
    from typing import NoReturn
else:
    try:
        from typing import NoReturn  # noqa: F811
    except ImportError:
        @typing.no_type_check
        class _NoReturn(typing._FinalTypingBase, _root=True):
            """Type for return type when function does not return."""

            __slots__ = ('__type__',)

            def __init__(self, tp: Any = None, **kwds: Any) -> None:
                self.__type__ = tp

            def __hash__(self) -> int:
                return hash((type(self).__name__, self.__type__))

        def __eq__(self, other) -> Any:
            if not isinstance(other, _NoReturn):
                return NotImplemented
            if self.__type__ is not None:
                return self.__type__ == other.__type__
            return self is other
        NoReturn = _NoReturn(_root=True)
