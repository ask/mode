"""Proxy objects.

Proxies
=======

Proxy objects are lazy and pass all method calls and attribute accesses
to an underlying object.

There are mixins/roles for many of the generic classes, and
these can be combined to create proxies.

For example to create a proxy to a class that both implements
the mutable mapping interface and is an async context manager:

.. sourcecode:: python


    def create_real():
        print('CREATING X')
        return X()

    class XProxy(MutableMappingRole, AsyncContextManagerRole):
        ...

    x = XProxy(create_real)

Evaluation
==========

By default the callable passed to :class:`Proxy` will be evaluated
every time it is needed, so in the example above a new
X will be created every time you access the underlying object:

.. sourcecode:: pycon

    >>> x['foo'] = 'value'
    CREATING X

    >>> x['foo']
    CREATING X
    'value'

    >>> X['foo']
    CREATING X
    'value'

    >>> # evaluates twice, once for async with then for __getitem__:
    >>> async with x:
    ...    x['foo']
    CREATING X
    CREATING X
    'value'

If you want the creation of the object to be lazy (created
when first needed), you can pass the `cache=True` argument to :class:`Proxy`:

.. sourcecode:: pycon

    >>> x = XProxy(create_real, cache=True)

    >>> # Now only evaluates the first time it is needed.
    >>> x['foo'] = 'value'
    CREATING X

    >>> x['foo']
    'value'

    >>> X['foo']
    'value'

    >>> async with x:
    ...    x['foo']
    'value'
"""
import sys
import typing

from collections import deque
from functools import wraps
from types import GetSetDescriptorType, TracebackType
from typing import (
    AbstractSet,
    Any,
    AsyncIterable,
    AsyncIterator,
    Awaitable,
    Callable,
    ClassVar,
    ContextManager,
    Coroutine,
    Dict,
    Generator,
    Generic,
    Iterable,
    Iterator,
    List,
    Mapping,
    MutableMapping,
    MutableSequence,
    MutableSet,
    Optional,
    Sequence,
    Tuple,
    Type,
    TypeVar,
    Union,
    ValuesView,
    cast,
    no_type_check,
    overload,
)
from .utils.locals import LocalStack  # XXX compat

if typing.TYPE_CHECKING:  # pragma: no cover
    from typing import AsyncContextManager, AsyncGenerator
else:
    from .utils.typing import AsyncContextManager, AsyncGenerator  # noqa

__all__ = [
    'LocalStack',
    'Proxy',
    'AwaitableRole',
    'AwaitableProxy',
    'CoroutineRole',
    'CoroutineProxy',
    'AsyncIterableRole',
    'AsyncIterableProxy',
    'AsyncIteratorRole',
    'AsyncIteratorProxy',
    'AsyncGeneratorRole',
    'AsyncGeneratorProxy',
    'SequenceRole',
    'SequenceProxy',
    'MutableSequenceRole',
    'MutableSequenceProxy',
    'SetRole',
    'SetProxy',
    'MutableSetRole',
    'MutableSetProxy',
    'ContextManagerRole',
    'ContextManagerProxy',
    'AsyncContextManagerRole',
    'AsyncContextManagerProxy',
    'MappingRole',
    'MappingProxy',
    'MutableMappingRole',
    'MutableMappingProxy',
    'CallableRole',
    'CallableProxy',
    'maybe_evaluate',
]

PYPY = hasattr(sys, 'pypy_version_info')
SLOTS_ISSUE_PRESENT = sys.version_info < (3, 7)

T = TypeVar('T')
S = TypeVar('S')
T_co = TypeVar('T_co', covariant=True)
V_co = TypeVar('V_co', covariant=True)
VT_co = TypeVar('VT_co', covariant=True)
T_contra = TypeVar('T_contra', contravariant=True)

KT = TypeVar('KT')
VT = TypeVar('VT')


def _default_cls_attr(
        name: str,
        type_: Type,
        cls_value: Any) -> Callable[[Type], GetSetDescriptorType]:
    # Proxy uses properties to forward the standard
    # class attributes __module__, __name__ and __doc__ to the real
    # object, but these needs to be a string when accessed from
    # the Proxy class directly.  This is a hack to make that work.
    # -- See Issue #1087.

    def __new__(cls: Type, getter: Callable) -> Any:
        instance = type_.__new__(cls, cls_value)
        instance.__getter = getter  # type: ignore
        return instance

    def __get__(self: Type, obj: Any, cls: Type = None) -> Any:
        return self.__getter(obj) if obj is not None else self

    return type(name, (type_,), {
        '__new__': __new__,
        '__get__': __get__,
    })


class Proxy(Generic[T]):
    """Proxy to another object."""

    __proxy_source__: ClassVar[Optional[Type[T]]] = None

    # Code initially stolen from werkzeug.local.Proxy.
    if not SLOTS_ISSUE_PRESENT and not PYPY:  # pragma: no cover
        __slots__ = (
            '__local',
            '__args',
            '__kwargs',
            '__finalizers',
            '__dict__',
        )

    def __init_subclass__(self, source: Type[T] = None) -> None:
        super().__init_subclass__()
        if source is not None:
            self._init_from_source(source)
        elif self.__proxy_source__ is not None:
            # __proxy_source__ must be used on Python < 3.7
            # to work around https://bugs.python.org/issue29581
            self._init_from_source(self.__proxy_source__)

    @classmethod
    def _init_from_source(cls, source: Type[T]) -> None:
        # source must have metaclass ABCMeta
        abstractmethods = getattr(source, '__abstractmethods__', None)
        if abstractmethods is None:
            raise TypeError('class is not using metaclass ABCMeta')
        for method_name in abstractmethods:
            setattr(cls, method_name,
                    cls._generate_proxy_method(source, method_name))

    @classmethod
    def _generate_proxy_method(
            cls, source: Type[T], method_name: str) -> Callable:

        @wraps(getattr(source, method_name))
        def _classmethod(self: Proxy[T], *args: Any, **kwargs: Any) -> Any:
            obj = self._get_current_object()
            return getattr(obj, method_name)(*args, **kwargs)
        _classmethod.__isabstractmethod__ = False  # type: ignore

        return _classmethod

    def __init__(self,
                 local: Callable[..., T],
                 args: Tuple = None,
                 kwargs: Dict = None,
                 name: str = None,
                 cache: bool = False,
                 __doc__: str = None) -> None:
        object.__setattr__(self, '_Proxy__local', local)
        object.__setattr__(self, '_Proxy__args', args or ())
        object.__setattr__(self, '_Proxy__kwargs', kwargs or {})
        object.__setattr__(self, '_Proxy__cached', cache)
        object.__setattr__(self, '_Proxy__finalizers', deque())
        if name is not None:
            object.__setattr__(self, '__custom_name__', name)
        if __doc__ is not None:
            object.__setattr__(self, '__doc__', __doc__)

    def _add_proxy_finalizer(self, fun: 'Proxy') -> None:
        finalizers = object.__getattribute__(self, '_Proxy__finalizers')
        finalizers.append(fun)

    def _call_proxy_finalizers(self) -> None:
        finalizers = object.__getattribute__(self, '_Proxy__finalizers')
        while finalizers:
            finalizer = finalizers.popleft()
            finalizer._get_current_object()  # evaluate

    @_default_cls_attr('name', str, __name__)
    @no_type_check
    def __name__(self) -> str:
        try:
            return self.__custom_name__
        except AttributeError:
            return self._get_current_object().__name__

    @_default_cls_attr('module', str, __name__)
    @no_type_check
    def __module__(self) -> str:
        return self._get_current_object().__module__

    @_default_cls_attr('doc', str, __doc__)
    @no_type_check
    def __doc__(self) -> Optional[str]:
        return cast(str, self._get_current_object().__doc__)

    def _get_class(self) -> Type[T]:
        return self._get_current_object().__class__

    @property
    def __class__(self) -> Any:
        return self._get_class()

    @__class__.setter  # noqa: F811
    def __class__(self, t: Type[T]) -> None:  # noqa: F811
        raise NotImplementedError()

    def _get_current_object(self) -> T:
        """Get current object.

        This is useful if you want the real
        object behind the proxy at a time for performance reasons or because
        you want to pass the object into a different context.
        """
        try:
            return cast(T, object.__getattribute__(self, '__cache'))
        except AttributeError:
            return self.__evaluate__()

    def __evaluate__(self,
                     _clean: Tuple[str, ...] = ('_Proxy__local',
                                                '_Proxy__args',
                                                '_Proxy__kwargs')) -> T:
        thing = self._evaluate_proxy()
        cached = object.__getattribute__(self, '_Proxy__cached')
        if cached:
            object.__setattr__(self, '__cache', thing)
            for attr in _clean:
                try:
                    object.__delattr__(self, attr)
                except AttributeError:  # pragma: no cover
                    # May mask errors so ignore
                    pass
        return thing

    def _evaluate_proxy(self) -> T:
        self._call_proxy_finalizers()
        loc = object.__getattribute__(self, '_Proxy__local')
        if not hasattr(loc, '__release_local__'):
            return cast(T, loc(*self.__args, **self.__kwargs))
        try:  # pragma: no cover
            # not sure what this is about
            return cast(T, getattr(loc, self.__name__))
        except AttributeError:  # pragma: no cover
            raise RuntimeError('no object bound to {0.__name__}'.format(self))

    def __evaluated__(self) -> bool:
        try:
            object.__getattribute__(self, '__cache')
        except AttributeError:
            return False
        return True

    def __maybe_evaluate__(self) -> T:
        return self._get_current_object()

    @property
    def __dict__(self) -> Dict[str, Any]:  # type: ignore
        try:
            return self._get_current_object().__dict__
        except RuntimeError:  # pragma: no cover
            raise AttributeError('__dict__')

    def __repr__(self) -> str:
        try:
            obj = self._get_current_object()
        except RuntimeError:  # pragma: no cover
            return '<{0} unbound>'.format(self.__class__.__name__)
        return repr(obj)

    def __bool__(self) -> bool:
        try:
            return bool(self._get_current_object())
        except RuntimeError:  # pragma: no cover
            return False
    __nonzero__ = __bool__  # Py2

    def __dir__(self) -> List[str]:
        try:
            return dir(self._get_current_object())
        except RuntimeError:  # pragma: no cover
            return []

    def __getattr__(self, name: str) -> Any:
        if name == '__members__':
            return dir(self._get_current_object())
        return getattr(self._get_current_object(), name)

    def __eq__(self, other: Any) -> Any:
        return self._get_current_object() == other

    def __ne__(self, other: Any) -> Any:
        return self._get_current_object() != other

    def __setattr__(self, name: str, value: Any) -> None:
        setattr(self._get_current_object(), name, value)

    def __delattr__(self, name: str) -> None:
        delattr(self._get_current_object(), name)

    def __str__(self) -> str:
        return str(self._get_current_object())

    def __hash__(self) -> int:
        return hash(self._get_current_object())

    def __reduce__(self) -> Tuple:
        return cast(Tuple, self._get_current_object().__reduce__())


class AwaitableRole(Awaitable[T]):
    """Role/Mixin for :class:`typing.Awaitable` proxy methods."""

    def _get_awaitable(self) -> Awaitable[T]:
        obj = self._get_current_object()  # type: ignore
        return cast(Awaitable[T], obj)

    def __await__(self) -> Generator[Any, None, T]:
        return self._get_awaitable().__await__()


class AwaitableProxy(Proxy[T], AwaitableRole[T]):
    """Proxy to :class:`typing.Awaitable` object."""


class CoroutineRole(Coroutine[T_co, T_contra, V_co]):
    """Role/Mixin for :class:`typing.Coroutine` proxy methods."""

    def _get_coroutine(self) -> Coroutine[T_co, T_contra, V_co]:
        obj = self._get_current_object()  # type: ignore
        return cast(Coroutine[T_co, T_contra, V_co], obj)

    def __await__(self) -> Generator[Any, None, V_co]:
        return self._get_coroutine().__await__()

    def send(self, value: T_contra) -> T_co:
        return self._get_coroutine().send(value)

    def throw(self,
              typ: Type[BaseException],
              val: Optional[BaseException] = None,
              tb: TracebackType = None) -> T_co:
        return self._get_coroutine().throw(typ, val, tb)

    def close(self) -> None:
        return self._get_coroutine().close()


class CoroutineProxy(Proxy[Coroutine[T_co, T_contra, V_co]],
                     CoroutineRole[T_co, T_contra, V_co]):
    """Proxy to :class:`typing.Coroutine` object."""


class AsyncIterableRole(AsyncIterable[T_co]):
    """Role/Mixin for :class:`typing.AsyncIterable` proxy methods."""

    def _get_iterable(self) -> AsyncIterable[T_co]:
        obj = self._get_current_object()  # type: ignore
        return cast(AsyncIterable[T_co], obj)

    def __aiter__(self) -> AsyncIterator[T_co]:
        return self._get_iterable().__aiter__()


class AsyncIterableProxy(Proxy[AsyncIterable[T_co]],
                         AsyncIterableRole[T_co]):
    """Proxy to :class:`typing.AsyncIterable` object."""


class AsyncIteratorRole(AsyncIterator[T_co]):
    """Role/Mixin for :class:`typing.AsyncIterator` proxy methods."""

    def _get_iterator(self) -> AsyncIterator[T_co]:
        obj = self._get_current_object()  # type: ignore
        return cast(AsyncIterator[T_co], obj)

    def __aiter__(self) -> AsyncIterator[T_co]:
        return self._get_iterator().__aiter__()

    def __anext__(self) -> Awaitable[T_co]:
        return self._get_iterator().__anext__()


class AsyncIteratorProxy(Proxy[AsyncIterator[T_co]],
                         AsyncIteratorRole[T_co]):
    """Proxy to :class:`typing.AsyncIterator` object."""


class AsyncGeneratorRole(AsyncGenerator[T_co, T_contra]):
    """Role/Mixin for :class:`typing.AsyncGenerator` proxy methods."""

    def _get_generator(self) -> AsyncGenerator[T_co, T_contra]:
        obj = self._get_current_object()  # type: ignore
        return cast(AsyncGenerator[T_co, T_contra], obj)

    def __anext__(self) -> Awaitable[T_co]:
        return self._get_generator().__anext__()

    def asend(self, value: T_contra) -> Awaitable[T_co]:
        return self._get_generator().asend(value)

    def athrow(self,
               typ: Type[BaseException],
               val: Optional[BaseException] = None,
               tb: TracebackType = None) -> Awaitable[T_co]:
        return self._get_generator().athrow(typ, val, tb)

    def aclose(self) -> Awaitable[None]:
        return self._get_generator().aclose()

    def __aiter__(self) -> AsyncGenerator[T_co, T_contra]:
        return self._get_generator().__aiter__()


class AsyncGeneratorProxy(Proxy[AsyncGenerator[T_co, T_contra]],
                          AsyncGeneratorRole[T_co, T_contra]):
    """Proxy to :class:`typing.AsyncGenerator` object."""


class SequenceRole(Sequence[T_co]):
    """Role/Mixin for :class:`typing.Sequence` proxy methods."""

    def _get_sequence(self) -> Sequence[T_co]:
        obj = self._get_current_object()  # type: ignore
        return cast(Sequence[T_co], obj)

    @overload
    def __getitem__(self, i: int) -> T_co:
        ...

    @overload  # noqa: F811
    def __getitem__(self, s: slice) -> MutableSequence[T_co]:  # noqa: F811
        ...

    def __getitem__(self, s: Any) -> Any:  # noqa: F811
        return self._get_sequence().__getitem__(s)

    def index(self, x: Any, *args: Any, **kwargs: Any) -> int:
        return self._get_sequence().index(x, *args, **kwargs)

    def count(self, x: Any) -> int:
        return self._get_sequence().count(x)

    def __contains__(self, x: Any) -> bool:
        return self._get_sequence().__contains__(x)

    def __iter__(self) -> Iterator[T_co]:
        return self._get_sequence().__iter__()

    def __reversed__(self) -> Iterator[T_co]:
        return self._get_sequence().__reversed__()

    def __len__(self) -> int:
        return self._get_sequence().__len__()


class SequenceProxy(Proxy[Sequence[T_co]],
                    SequenceRole[T_co]):
    """Proxy to :class:`typing.Sequence` object."""


class MutableSequenceRole(SequenceRole[T], MutableSequence[T]):
    """Role/Mixin for :class:`typing.MutableSequence` proxy methods."""

    def _get_sequence(self) -> MutableSequence[T]:
        obj = self._get_current_object()  # type: ignore
        return cast(MutableSequence[T], obj)

    def insert(self, index: int, object: T) -> None:
        self._get_sequence().insert(index, object)

    @overload
    def __setitem__(self, i: int, o: T) -> None:
        ...

    @overload  # noqa: F811
    def __setitem__(self, s: slice, o: Iterable[T]) -> None:  # noqa: F811
        ...

    def __setitem__(self, index_or_slice: Any, o: Any) -> None:  # noqa: F811
        self._get_sequence().__setitem__(index_or_slice, o)

    @overload
    def __delitem__(self, i: int) -> None:
        ...

    @overload  # noqa: F811
    def __delitem__(self, i: slice) -> None:  # noqa: F811
        ...

    def __delitem__(self, i: Any) -> None:  # noqa: F811
        self._get_sequence().__delitem__(i)

    def append(self, obj: T) -> None:
        self._get_sequence().append(obj)

    def extend(self, iterable: Iterable[T]) -> None:
        self._get_sequence().extend(iterable)

    def reverse(self) -> None:
        self._get_sequence().reverse()

    def pop(self, *args: Any) -> Any:
        return self._get_sequence().pop(*args)

    def remove(self, object: T) -> None:
        self._get_sequence().remove(object)

    def __iadd__(self, x: Iterable[T]) -> MutableSequence[T]:
        return self._get_sequence().__iadd__(x)


class MutableSequenceProxy(Proxy[MutableSequence[T_co]],
                           MutableSequenceRole[T_co]):
    """Proxy to :class:`typing.MutableSequence` object."""


class SetRole(AbstractSet[T_co]):
    """Role/Mixin for :class:`typing.AbstractSet` proxy methods."""

    def _get_set(self) -> AbstractSet[T_co]:
        obj = self._get_current_object()  # type: ignore
        return cast(AbstractSet[T_co], obj)

    def __le__(self, s: AbstractSet[Any]) -> bool:
        return self._get_set().__le__(s)

    def __lt__(self, s: AbstractSet[Any]) -> bool:
        return self._get_set().__lt__(s)

    def __gt__(self, s: AbstractSet[Any]) -> bool:
        return self._get_set().__gt__(s)

    def __ge__(self, s: AbstractSet[Any]) -> bool:
        return self._get_set().__ge__(s)

    def __and__(self, s: AbstractSet[Any]) -> AbstractSet[T_co]:
        return self._get_set().__and__(s)

    def __or__(self, s: AbstractSet[T]) -> AbstractSet[Union[T_co, T]]:
        return self._get_set().__or__(s)

    def __sub__(self, s: AbstractSet[Any]) -> AbstractSet[T_co]:
        return self._get_set().__sub__(s)

    def __xor__(self, s: AbstractSet[T]) -> AbstractSet[Union[T_co, T]]:
        return self._get_set().__xor__(s)

    def isdisjoint(self, s: Iterable[Any]) -> bool:
        return self._get_set().isdisjoint(s)

    def __contains__(self, x: Any) -> bool:
        return self._get_set().__contains__(x)

    def __iter__(self) -> Iterator[T_co]:
        return self._get_set().__iter__()

    def __len__(self) -> int:
        return self._get_set().__len__()


class SetProxy(Proxy[AbstractSet[T_co]],
               SetRole[T_co]):
    """Proxy to :class:`typing.AbstractSet` object."""


class MutableSetRole(SetRole[T], MutableSet[T]):
    """Role/Mixin for :class:`typing.MutableSet` proxy methods."""

    def _get_set(self) -> MutableSet[T]:
        obj = self._get_current_object()  # type: ignore
        return cast(MutableSet[T], obj)

    def add(self, x: T) -> None:
        self._get_set().add(x)

    def discard(self, x: T) -> None:
        self._get_set().discard(x)

    def clear(self) -> None:
        self._get_set().clear()

    def pop(self) -> T:
        return self._get_set().pop()

    def remove(self, element: T) -> None:
        self._get_set().remove(element)

    def __ior__(self, s: AbstractSet[S]) -> MutableSet[Union[T, S]]:
        return self._get_set().__ior__(s)

    def __iand__(self, s: AbstractSet[Any]) -> MutableSet[T]:
        return self._get_set().__iand__(s)

    def __ixor__(self, s: AbstractSet[S]) -> MutableSet[Union[T, S]]:
        return self._get_set().__ixor__(s)

    def __isub__(self, s: AbstractSet[Any]) -> MutableSet[T]:
        return self._get_set().__isub__(s)


class MutableSetProxy(Proxy[MutableSet[T_co]],
                      MutableSetRole[T_co]):
    """Proxy to :class:`typing.MutableSet` object."""


class ContextManagerRole(ContextManager[T]):
    """Role/Mixin for :class:`typing.ContextManager` proxy methods."""

    def _get_context(self) -> ContextManager[T]:
        obj = self._get_current_object()  # type: ignore
        return cast(ContextManager[T], obj)

    def __enter__(self) -> Any:
        return self._get_context().__enter__()

    def __exit__(self, *exc_info: Any) -> Any:
        return self._get_context().__exit__(*exc_info)


class ContextManagerProxy(Proxy[ContextManager[T]],
                          ContextManagerRole[T]):
    """Proxy to :class:`typing.ContextManager` object."""


class AsyncContextManagerRole(AsyncContextManager[T_co]):
    """Role/Mixin for :class:`typing.AsyncContextManager` proxy methods."""

    def __aenter__(self) -> Awaitable[T_co]:
        obj = self._get_current_object()  # type: ignore
        return cast(Awaitable[T_co], obj.__aenter__())

    def __aexit__(
            self,
            exc_type: Optional[Type[BaseException]],
            exc_value: Optional[BaseException],
            traceback: Optional[TracebackType]) -> Awaitable[Optional[bool]]:
        obj = self._get_current_object()  # type: ignore
        val = obj.__aexit__(exc_type, exc_value, traceback)
        return cast(Awaitable[Optional[bool]], val)


class AsyncContextManagerProxy(Proxy[AsyncContextManager[T_co]],
                               AsyncContextManagerRole[T_co]):
    """Proxy to :class:`typing.AsyncContextManager` object."""


class MappingRole(Mapping[KT, VT_co]):
    """Role/Mixin for :class:`typing.Mapping` proxy methods."""

    def _get_mapping(self) -> Mapping[KT, VT_co]:
        obj = self._get_current_object()  # type: ignore
        return cast(Mapping[KT, VT_co], obj)

    def __getitem__(self, key: KT) -> VT_co:
        return self._get_mapping().__getitem__(key)

    @overload
    def get(self, k: KT) -> Optional[VT_co]:
        ...

    @overload  # noqa: F811
    def get(self, k: KT,  # noqa: F811
            default: Union[VT_co, T]) -> Union[VT_co, T]:
        ...

    def get(self, *args: Any, **kwargs: Any) -> Any:  # noqa: F811
        return self._get_mapping().get(*args, **kwargs)

    def items(self) -> AbstractSet[Tuple[KT, VT_co]]:
        return self._get_mapping().items()

    def keys(self) -> AbstractSet[KT]:
        return self._get_mapping().keys()

    def values(self) -> ValuesView[VT_co]:
        return self._get_mapping().values()

    def __contains__(self, o: Any) -> bool:
        return self._get_mapping().__contains__(o)

    def __iter__(self) -> Iterator[KT]:
        return self._get_mapping().__iter__()

    def __len__(self) -> int:
        return self._get_mapping().__len__()


class MappingProxy(Proxy[Mapping[KT, VT_co]],
                   MappingRole[KT, VT_co]):
    """Proxy to :class:`typing.Mapping` object."""


class MutableMappingRole(MappingRole[KT, VT], MutableMapping[KT, VT]):
    """Role/Mixin for :class:`typing.MutableMapping` proxy methods."""

    def _get_mapping(self) -> MutableMapping[KT, VT]:
        obj = self._get_current_object()  # type: ignore
        return cast(MutableMapping[KT, VT], obj)

    def __setitem__(self, key: KT, value: VT) -> None:
        self._get_mapping().__setitem__(key, value)

    def __delitem__(self, key: KT) -> None:
        self._get_mapping().__delitem__(key)

    def clear(self) -> None:
        self._get_mapping().clear()

    @overload
    def pop(self, k: KT) -> VT:
        ...

    @overload  # noqa: F811
    def pop(self, k: KT,  # noqa: F811
            default: Union[VT, T] = ...) -> Union[VT, T]:
        ...

    def pop(self, *args: Any, **kwargs: Any) -> Any:  # noqa: F811
        return self._get_mapping().pop(*args, **kwargs)

    def popitem(self) -> Tuple[KT, VT]:
        return self._get_mapping().popitem()

    def setdefault(self, k: KT, *args: Any) -> VT:
        return self._get_mapping().setdefault(k, *args)

    @overload
    def update(self, __m: Mapping[KT, VT], **kwargs: VT) -> None:
        ...

    @overload  # noqa: F811
    def update(self, __m: Iterable[Tuple[KT, VT]],  # noqa: F811
               **kwargs: VT) -> None:
        ...

    @overload  # noqa: F811
    def update(self, **kwargs: VT) -> None:  # noqa: F811
        ...

    def update(self, *args: Any, **kwargs: Any) -> None:  # noqa: F811
        self._get_mapping().update(*args, **kwargs)


class MutableMappingProxy(Proxy[MutableMapping[KT, VT]],
                          MutableMappingRole[KT, VT]):
    """Proxy to :class:`typing.MutableMapping` object."""


class CallableRole:
    """Role/Mixin for :class:`typing.Callable` proxy methods."""

    def _get_callable(self) -> Callable:
        obj = self._get_current_object()  # type: ignore
        return cast(Callable, obj)

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        return self._get_callable()(*args, **kwargs)


class CallableProxy(Proxy[Callable], CallableRole):
    """Proxy to :class:`typing.Callable` object."""


def maybe_evaluate(obj: Any) -> Any:
    """Attempt to evaluate promise, even if obj is not a promise."""
    try:
        return obj.__maybe_evaluate__()
    except AttributeError:
        return obj
