"""Implements thread-local stack using :class:`ContextVar` (:pep:`567`).

This is a reimplementation of the local stack as used by Flask, Werkzeug,
Celery, and other libraries to keep a thread-local stack of objects.

- Supports typing:

    .. sourcecode:: python

        request_stack: LocalStack[Request] = LocalStack()
"""
from contextlib import contextmanager
from contextvars import ContextVar
from types import GetSetDescriptorType
from typing import (
    Any,
    Callable,
    ContextManager,
    Dict,
    Generator,
    Generic,
    Iterator,
    List,
    Mapping,
    MutableMapping,
    Optional,
    Sequence,
    Tuple,
    Type,
    TypeVar,
    cast,
    no_type_check,
)

# LocalStack is a generic type,
# so for a stack keeping track of web requests you may define:
#
#   requests: LocalStack[Request]
#
# If the stack is a ``List[T]``, then the type variable T denotes the
# type this stack contains.
T = TypeVar('T')

KT = TypeVar('KT')
VT = TypeVar('VT')


class LocalStack(Generic[T]):
    """LocalStack.

    Manage state per coroutine (also thread safe).

    Most famously used probably in Flask to keep track of the current
    request object.
    """

    _stack: ContextVar[Optional[List[T]]]

    def __init__(self) -> None:
        self._stack = ContextVar('_stack')

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

    # Code stolen from werkzeug.local.Proxy.
    __slots__ = ('__local', '__args', '__kwargs', '__dict__')

    def __init__(self,
                 local: Callable[..., T],
                 args: Tuple = None,
                 kwargs: Dict = None,
                 name: str = None,
                 __doc__: str = None) -> None:
        object.__setattr__(self, '_Proxy__local', local)
        object.__setattr__(self, '_Proxy__args', args or ())
        object.__setattr__(self, '_Proxy__kwargs', kwargs or {})
        if name is not None:
            object.__setattr__(self, '__custom_name__', name)
        if __doc__ is not None:
            object.__setattr__(self, '__doc__', __doc__)

    @_default_cls_attr('name', str, __name__)
    @no_type_check
    def __name__(self) -> str:
        try:
            return self.__custom_name__
        except AttributeError:
            return self._get_current_object().__name__

    @_default_cls_attr('qualname', str, __name__)
    @no_type_check
    def __qualname__(self) -> str:
        try:
            return cast(str, self.__custom_name__)
        except AttributeError:
            obj = self._get_current_object()
            return cast(str, obj.__qualname__)

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

    @__class__.setter
    def __class__(self, t: Type[T]) -> None:
        raise NotImplementedError()

    def _get_current_object(self) -> T:
        """Get current object.

        This is useful if you want the real
        object behind the proxy at a time for performance reasons or because
        you want to pass the object into a different context.
        """
        return self._evaluate_proxy()

    def _evaluate_proxy(self) -> T:
        loc = object.__getattribute__(self, '_Proxy__local')
        if not hasattr(loc, '__release_local__'):
            return cast(T, loc(*self.__args, **self.__kwargs))
        try:  # pragma: no cover
            # not sure what this is about
            return cast(T, getattr(loc, self.__name__))
        except AttributeError:  # pragma: no cover
            raise RuntimeError('no object bound to {0.__name__}'.format(self))

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

    def __setattr__(self, name: str, value: Any) -> None:
        setattr(self._get_current_object(), name, value)

    def __delattr__(self, name: str) -> None:
        delattr(self._get_current_object(), name)

    def __str__(self) -> str:
        return str(self._get_current_object())

    def __hash__(self) -> int:
        return hash(self._get_current_object())

    def __reduce__(self) -> Tuple:
        return self._get_current_object().__reduce__()


class ContextManagerRole(ContextManager):

    def __enter__(self) -> Any:
        obj = self._get_current_object()  # type: ignore
        return obj.__enter__()

    def __exit__(self, *exc_info: Any) -> Any:
        obj = self._get_current_object()  # type: ignore
        return obj.__exit__(*exc_info)

class MutableMappingRole(MutableMapping[KT, VT]):

    def __getitem__(self, key: KT) -> VT:
        mapping = cast(Mapping, self._get_current_object())  # type: ignore
        return cast(VT, mapping[key])

    def __setitem__(self, key: KT, value: VT) -> None:
        mapping = self._get_current_object()  # type: ignore
        mapping[key] = value

    def __delitem__(self, key: KT) -> None:
        mapping = self._get_current_object()  # type: ignore
        del mapping[key]

    def __iter__(self) -> Iterator[KT]:
        mapping = cast(Mapping, self._get_current_object())  # type: ignore
        return iter(mapping)

    def __len__(self) -> int:
        mapping = cast(Mapping, self._get_current_object())  # type: ignore
        return len(mapping)


class CallableRole:

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        obj = self._get_current_object()  # type: ignore
        return obj(*args, **kwargs)


class MutableMappingProxy(Proxy[MutableMapping[KT, VT]],
                          MutableMappingRole[KT, VT]):
    ...


class PromiseProxy(Proxy[T]):
    """Proxy that evaluates object once.

    :class:`Proxy` will evaluate the object each time, while the
    promise will only evaluate it once.
    """

    __slots__ = ('__weakref__',)

    def _get_current_object(self) -> T:
        try:
            return cast(T, object.__getattribute__(self, '__thing'))
        except AttributeError:
            return self.__evaluate__()

    def __evaluated__(self) -> bool:
        try:
            object.__getattribute__(self, '__thing')
        except AttributeError:
            return False
        return True

    def __maybe_evaluate__(self) -> T:
        return self._get_current_object()

    def __evaluate__(self,
                     _clean: Tuple[str, ...] = ('_Proxy__local',
                                                '_Proxy__args',
                                                '_Proxy__kwargs')) -> T:
        try:
            thing = Proxy._get_current_object(self)
        except Exception:
            raise
        else:
            object.__setattr__(self, '__thing', thing)
            for attr in _clean:
                try:
                    object.__delattr__(self, attr)
                except AttributeError:  # pragma: no cover
                    # May mask errors so ignore
                    pass
            return thing


def maybe_evaluate(obj: Any) -> Any:
    """Attempt to evaluate promise, even if obj is not a promise."""
    try:
        return obj.__maybe_evaluate__()
    except AttributeError:
        return obj
