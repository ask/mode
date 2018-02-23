"""Custom data structures."""
import abc
import collections
import threading
from collections import OrderedDict, UserDict, UserList
from typing import (
    Any, ContextManager, Dict, ItemsView, Iterable, Iterator, KeysView,
    Mapping, MutableMapping, MutableSet, Tuple, TypeVar, ValuesView, cast,
)

from .compat import DummyContext

try:
    from django.utils.functional import LazyObject, LazySettings
except ImportError:
    class LazyObject: ...  # noqa
    class LazySettings: ...  # noqa

__all__ = [
    'FastUserDict',
    'FastUserSet',
    'FastUserList',
    'LRUCache',
    'ManagedUserDict',
    'ManagedUserSet',
    'AttributeDict',
    'AttributeDictMixin',
    'DictAttribute',
    'force_mapping',
]

KT = TypeVar('KT')
VT = TypeVar('VT')


class FastUserDict(UserDict):
    """Proxy to dict.

    Like :class:`collection.UserDict` but reimplements some methods
    for better performance when the underlying dictionary is a real dict.
    """

    data: MutableMapping

    # Mypy forces us to redefine these, for some reason:

    def __getitem__(self, key: Any) -> Any:
        if not hasattr(self, '__missing__'):
            return self.data[key]
        if key in self.data:
            return self.data[key]
        return self.__missing__(key)  # type: ignore

    def __setitem__(self, key: Any, value: Any) -> None:
        self.data[key] = value

    def __delitem__(self, key: Any) -> None:
        del self.data[key]

    def __len__(self) -> int:
        return len(self.data)

    def __iter__(self) -> Iterator:
        return iter(self.data)

    # Rest is fast versions of generic slow MutableMapping methods.

    def __contains__(self, key: Any) -> bool:
        return key in self.data

    def update(self, *args: Any, **kwargs: Any) -> None:
        self.data.update(*args, **kwargs)

    def clear(self) -> None:
        self.data.clear()

    def items(self) -> ItemsView:
        return cast(ItemsView, self.data.items())

    def keys(self) -> KeysView:
        return cast(KeysView, self.data.keys())

    def values(self) -> ValuesView:
        return self.data.values()


class FastUserSet(MutableSet):
    """Proxy to set."""

    data: MutableMapping[Any, bool]

    def __contains__(self, key: Any) -> bool:
        return key in self.data

    def __iter__(self) -> Iterator:
        return iter(self.data)

    def __len__(self) -> int:
        return len(self.data)

    def add(self, key: Any) -> None:
        self.data[key] = True

    def discard(self, key: Any) -> None:
        self.data.pop(key, None)

    # Rest is fast versions of generic slow MutableSet methods.

    def clear(self) -> None:
        self.data.clear()


class FastUserList(UserList):
    """Proxy to list."""


class MappingViewProxy(abc.ABC):

    @abc.abstractmethod
    def _keys(self) -> Iterable[KT]:
        ...

    @abc.abstractmethod
    def _values(self) -> Iterable[VT]:
        ...

    @abc.abstractmethod
    def _items(self) -> Iterable[Tuple[KT, VT]]:
        ...


class ProxyKeysView(KeysView):

    def __init__(self, mapping: MappingViewProxy) -> None:
        self._mapping = mapping

    def __iter__(self) -> Iterator[KT]:
        return self._mapping._keys()


class ProxyValuesView(ValuesView):

    def __init__(self, mapping: MappingViewProxy) -> None:
        self._mapping = mapping

    def __iter__(self) -> Iterator[VT]:
        yield from self._mapping._values()


class ProxyItemsView(ItemsView):

    def __init__(self, mapping: MappingViewProxy) -> None:
        self._mapping = mapping

    def __iter__(self) -> Iterator[Tuple[KT, VT]]:
        yield from self._mapping._items()


class LRUCache(FastUserDict, MutableMapping[KT, VT], MappingViewProxy):
    """LRU Cache implementation using a doubly linked list to track access.

    Arguments:
        limit (int): The maximum number of keys to keep in the cache.
            When a new key is inserted and the limit has been exceeded,
            the *Least Recently Used* key will be discarded from the
            cache.
        thread_safety (bool): Enable if multiple OS threads are going
            to access/mutate the cache.
    """

    limit: int
    thread_safety: bool
    _mutex: ContextManager
    data: OrderedDict

    def __init__(self, limit: int = None,
                 *,
                 thread_safety: bool = False) -> None:
        self.limit = limit
        self.thread_safety = thread_safety
        self._mutex = self._new_lock()
        self.data: OrderedDict = OrderedDict()

    def __getitem__(self, key: KT) -> VT:
        with self._mutex:
            value = self[key] = self.data.pop(key)
            return value

    def update(self, *args: Any, **kwargs: Any) -> None:
        with self._mutex:
            data, limit = self.data, self.limit
            data.update(*args, **kwargs)
            if limit and len(data) > limit:
                # pop additional items in case limit exceeded
                for _ in range(len(data) - limit):
                    data.popitem(last=False)

    def popitem(self, *, last: bool = True) -> Tuple[KT, VT]:
        with self._mutex:
            return self.data.popitem(last)

    def __setitem__(self, key: KT, value: VT) -> None:
        # remove least recently used key.
        with self._mutex:
            if self.limit and len(self.data) >= self.limit:
                self.data.pop(next(iter(self.data)))
            self.data[key] = value

    def __iter__(self) -> Iterator:
        return iter(self.data)

    def keys(self) -> KeysView[KT]:
        return ProxyKeysView(self)

    def _keys(self) -> Iterator[KT]:
        # userdict.keys in py3k calls __getitem__
        with self._mutex:
            yield from self.data.keys()

    def values(self) -> ValuesView[VT]:
        return ProxyValuesView(self)

    def _values(self) -> Iterator[VT]:
        with self._mutex:
            for k in self:
                try:
                    yield self.data[k]
                except KeyError:  # pragma: no cover
                    pass

    def items(self) -> ItemsView[KT, VT]:
        return ProxyItemsView(self)

    def _items(self) -> Iterator[Tuple[KT, VT]]:
        with self._mutex:
            for k in self:
                try:
                    yield (k, self.data[k])
                except KeyError:  # pragma: no cover
                    pass

    def incr(self, key: KT, delta: int = 1) -> int:
        with self._mutex:
            # this acts as memcached does- store as a string, but return a
            # integer as long as it exists and we can cast it
            newval = int(self.data.pop(key)) + delta
            self[key] = cast(VT, str(newval))
            return newval

    def _new_lock(self) -> ContextManager:
        if self.thread_safety:
            return cast(ContextManager, threading.RLock())
        return DummyContext()

    def __getstate__(self) -> Mapping[str, Any]:
        d = dict(vars(self))
        d.pop('_mutex')
        return d

    def __setstate__(self, state: Dict[str, Any]) -> None:
        self.__dict__ = state
        self._mutex = self._new_lock()


class ManagedUserSet(FastUserSet):
    """A MutableSet that adds callbacks for when keys are get/set/deleted."""

    def on_key_get(self, key: Any) -> None:
        ...

    def on_key_set(self, key: Any) -> None:
        ...

    def on_key_del(self, key: Any) -> None:
        ...

    def on_clear(self) -> None:
        ...

    def __contains__(self, key: Any) -> bool:
        self.on_key_get(key)
        return super().__contains__(key)

    def add(self, key: Any) -> None:
        self.on_key_set(key)
        return super().add(key)

    def discard(self, key: Any) -> None:
        self.on_key_del(key)
        return super().discard(key)

    def clear(self) -> None:
        self.on_clear()
        return super().clear()

    def raw_update(self, *args: Any, **kwargs: Any) -> None:
        self.data.update(*args, **kwargs)


class ManagedUserDict(FastUserDict):
    """A UserDict that adds callbacks for when keys are get/set/deleted."""

    def on_key_get(self, key: Any) -> None:
        """Handle that key is being retrieved."""
        ...

    def on_key_set(self, key: Any, value: Any) -> None:
        """Handle that value for a key is being set."""
        ...

    def on_key_del(self, key: Any) -> None:
        """Handle that a key is deleted."""
        ...

    def on_clear(self) -> None:
        """Handle that the mapping is being cleared."""
        ...

    def __getitem__(self, key: Any) -> Any:
        self.on_key_get(key)
        return super().__getitem__(key)

    def __setitem__(self, key: Any, value: Any) -> None:
        self.on_key_set(key, value)
        self.data[key] = value

    def __delitem__(self, key: Any) -> None:
        self.on_key_del(key)
        del self.data[key]

    def update(self, *args: Any, **kwargs: Any) -> None:
        for d in args:
            for key, value in d.items():
                self.on_key_set(key, value)
        for key, value in kwargs.items():
            self.on_key_set(key, value)
        self.data.update(*args, **kwargs)

    def clear(self) -> None:
        self.on_clear()
        self.data.clear()

    def raw_update(self, *args: Any, **kwargs: Any) -> None:
        self.data.update(*args, **kwargs)


class AttributeDictMixin:
    """Mixin for Mapping interface that adds attribute access.

    I.e., `d.key -> d[key]`).
    """

    def __getattr__(self, k: str) -> Any:
        """`d.key -> d[key]`."""
        try:
            return self[k]
        except KeyError:
            raise AttributeError(
                f'{type(self).__name__!r} object has no attribute {k!r}')

    def __setattr__(self, key: str, value: Any) -> None:
        """`d[key] = value -> d.key = value`."""
        self[key] = value


class AttributeDict(dict, AttributeDictMixin):
    """Dict subclass with attribute access."""
    ...


class DictAttribute(MutableMapping[KT, VT], MappingViewProxy):
    """Dict interface to attributes.

    `obj[k] -> obj.k`
    `obj[k] = val -> obj.k = val`
    """

    obj: Any = None

    def __init__(self, obj: Any) -> None:
        object.__setattr__(self, 'obj', obj)

    def __getattr__(self, key: Any) -> Any:
        return getattr(self.obj, key)

    def __setattr__(self, key: Any, value: Any) -> None:
        return setattr(self.obj, key, value)

    def get(self, key: Any, default: Any = None) -> Any:
        # type: (Any, Any) -> Any
        try:
            return self[key]
        except KeyError:
            return default

    def setdefault(self, key: Any, default: Any = None) -> Any:
        if key in self:
            return self[key]
        self[key] = default
        return default

    def __getitem__(self, key: Any) -> Any:
        try:
            return getattr(self.obj, key)
        except AttributeError:
            raise KeyError(key)

    def __setitem__(self, key: Any, value: Any) -> None:
        setattr(self.obj, key, value)

    def __contains__(self, key: Any) -> bool:
        return hasattr(self.obj, key)

    def __iter__(self) -> Iterable[KT]:
        return self._keys()

    def _keys(self) -> Iterator[KT]:
        for key in dir(self.obj):
            yield key

    def _values(self) -> Iterator[VT]:
        # type: () -> Iterable
        obj = self.obj
        for key in self:
            yield getattr(obj, key)

    def _items(self) -> Iterator[Tuple[KT, VT]]:
        # type: () -> Iterable
        obj = self.obj
        for key in self:
            yield key, getattr(obj, key)
collections.MutableMapping.register(DictAttribute)  # noqa: E305


def force_mapping(m: Any) -> Mapping:
    # type: (Any) -> Mapping
    """Wrap object into supporting the mapping interface if necessary."""
    if isinstance(m, (LazyObject, LazySettings)):
        m = m._wrapped
    return DictAttribute(m) if not isinstance(m, Mapping) else m
