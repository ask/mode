import abc
import sys
from typing import (
    AbstractSet,
    AsyncGenerator,
    AsyncIterable,
    AsyncIterator,
    Awaitable,
    Mapping,
    MutableMapping,
    MutableSequence,
    MutableSet,
    Sequence,
)
from unittest.mock import MagicMock, Mock

import pytest

from mode.locals import (
    AsyncContextManagerProxy,
    AsyncGeneratorProxy,
    AsyncIterableProxy,
    AsyncIteratorProxy,
    AwaitableProxy,
    CallableProxy,
    ContextManagerProxy,
    CoroutineProxy,
    MappingProxy,
    MutableMappingProxy,
    MutableSequenceProxy,
    MutableSetProxy,
    Proxy,
    SequenceProxy,
    SetProxy,
    maybe_evaluate,
)


class test_Proxy:
    def test_std_class_attributes(self):
        assert Proxy.__name__ == "Proxy"
        assert Proxy.__module__ == "mode.locals"
        assert isinstance(Proxy.__doc__, str)

    def test_doc(self):
        def real():
            pass

        x = Proxy(real, __doc__="foo")
        assert x.__doc__ == "foo"

    def test_name(self):
        def real():
            """real function"""
            return "REAL"

        x = Proxy(lambda: real, name="xyz")
        assert x.__name__ == "xyz"

        y = Proxy(lambda: real)
        assert y.__name__ == "real"

        assert x.__doc__ == "real function"

        assert x.__class__ == type(real)
        assert x.__dict__ == real.__dict__
        assert repr(x) == repr(real)
        assert x.__module__

    def test_get_current_local(self):
        x = Proxy(lambda: 10)
        object.__setattr__(x, "_Proxy_local", Mock())
        assert x._get_current_object()

    def test_bool(self):
        class X(object):
            def __bool__(self):
                return False

            __nonzero__ = __bool__

        x = Proxy(lambda: X())
        assert not x

    def test_slots(self):
        class X(object):
            __slots__ = ()

        x = Proxy(X)
        with pytest.raises(AttributeError):
            x.__dict__

    def test_dir(self):
        class X(object):
            def __dir__(self):
                return ["a", "b", "c"]

        x = Proxy(lambda: X())
        assert dir(x) == ["a", "b", "c"]

        class Y(object):
            def __dir__(self):
                raise RuntimeError()

        y = Proxy(lambda: Y())
        assert dir(y) == []

    def test_qualname(self):
        class X:
            ...

        x = Proxy(lambda: X)
        assert x.__qualname__ == X.__qualname__

    def test_getsetdel_attr(self):
        class X(object):
            a = 1
            b = 2
            c = 3

            def __dir__(self):
                return ["a", "b", "c"]

        v = X()

        x = Proxy(lambda: v)
        assert x.__members__ == ["a", "b", "c"]
        assert x.a == 1
        assert x.b == 2
        assert x.c == 3

        setattr(x, "a", 10)  # noqa: B010
        assert x.a == 10

        del x.a
        assert x.a == 1

    def test_dictproxy(self):
        v = {}
        x = MutableMappingProxy(lambda: v)
        x["foo"] = 42
        assert x["foo"] == 42
        assert len(x) == 1
        assert "foo" in x
        del x["foo"]
        with pytest.raises(KeyError):
            x["foo"]
        assert iter(x)

    def test_complex_cast(self):
        class Object(object):
            def __complex__(self):
                return complex(10.333)

        o = Proxy(Object)
        assert o.__complex__() == complex(10.333)

    def test_index(self):
        class Object(object):
            def __index__(self):
                return 1

        o = Proxy(Object)
        assert o.__index__() == 1

    def test_coerce(self):
        class Object(object):
            def __coerce__(self, other):
                return self, other

        o = Proxy(Object)
        assert o.__coerce__(3)

    def test_hash(self):
        class X(object):
            def __hash__(self):
                return 1234

        assert hash(Proxy(lambda: X())) == 1234

    def test_call(self):
        class X(object):
            def __call__(self):
                return 1234

        assert CallableProxy(lambda: X())() == 1234

    def test_context(self):
        class X(object):
            entered = exited = False

            def __enter__(self):
                self.entered = True
                return 1234

            def __exit__(self, *exc_info):
                self.exited = True

        v = X()
        x = ContextManagerProxy(lambda: v)
        with x as val:
            assert val == 1234
        assert x.entered
        assert x.exited

    @pytest.mark.asyncio
    async def test_async_context(self):
        class X(object):
            entered = exited = False

            async def __aenter__(self):
                self.entered = True
                return 1234

            async def __aexit__(self, *exc_info):
                self.exited = True

        v = X()
        x = AsyncContextManagerProxy(lambda: v)
        async with x as val:
            assert val == 1234
        assert x.entered
        assert x.exited

    def test_reduce(self):
        class X(object):
            def __reduce__(self):
                return 123

        x = Proxy(lambda: X())
        assert x.__reduce__() == 123


class test_Proxy__cached:
    def test_only_evaluated_once(self):
        class X(object):
            attr = 123
            evals = 0

            def __init__(self):
                self.__class__.evals += 1

        p = Proxy(X, cache=True)
        assert p.attr == 123
        assert p.attr == 123
        assert X.evals == 1

    def test_maybe_evaluate(self):
        x = Proxy(lambda: 30, cache=True)
        assert not x.__evaluated__()
        assert maybe_evaluate(x) == 30
        assert maybe_evaluate(x) == 30

        assert maybe_evaluate(30) == 30
        assert x.__evaluated__()


class test_MappingProxy:
    @pytest.fixture()
    def orig(self):
        return {0: 1, 2: 3, 4: 5, 6: 7, 8: 9}

    @pytest.fixture()
    def s(self, *, orig):
        return MappingProxy(lambda: orig)

    def test_type(self, *, s):
        assert isinstance(s, Mapping)

    def test_getitem(self, *, s):
        assert s[0] == 1
        with pytest.raises(KeyError):
            s[1]

    def test_get(self, *, s):
        assert s.get(0) == 1
        assert s.get(1) is None
        assert s.get(1, 1) == 1

    def test_items(self, *, s, orig):
        assert list(s.items()) == list(orig.items())

    def test_keys(self, *, s, orig):
        assert list(s.keys()) == list(orig.keys())

    def test_values(self, *, s, orig):
        assert list(s.values()) == list(orig.values())

    def test_contains(self, *, s):
        assert 0 in s
        assert 1 not in s

    def test_iter(self, *, s, orig):
        assert list(iter(s)) == list(iter(orig))

    def test_len(self, *, s, orig):
        assert len(s) == len(orig)


class test_MutableMappingProxy(test_MappingProxy):
    # Note: Inherits all test cases from test_MappingProxy

    @pytest.fixture()
    def s(self, *, orig):
        return MutableMappingProxy(lambda: orig)

    def test_type(self, *, s):
        super().test_type(s=s)
        assert isinstance(s, MutableMapping)

    def test_setitem(self, *, s, orig):
        s[0] = "foo"
        assert s[0] == "foo"
        assert orig[0] == "foo"

    def test_delitem(self, *, s, orig):
        del s[0]
        assert 0 not in s
        assert 0 not in orig

        with pytest.raises(KeyError):
            del s[0]

    def test_clear(self, *, s, orig):
        s.clear()
        assert s == {}
        assert orig == {}

    def test_pop(self, *, s, orig):
        assert s.pop(0) == 1
        assert 0 not in s
        assert 0 not in orig

        with pytest.raises(KeyError):
            s.pop(0)

        assert s.pop(0, 1) == 1

    def test_popitem(self, *, s, orig):
        assert s.popitem() == (8, 9)
        assert 8 not in s
        assert 8 not in orig

    def test_setdefault(self, *, s, orig):
        assert s.setdefault(1, 2) == 2
        assert s.setdefault(1, 3) == 2
        assert orig[1] == 2

    def test_update__kwargs(self, *, s, orig):
        s.update(foo="foo")
        assert s["foo"] == "foo"
        assert orig["foo"] == "foo"

    def test_update__dict(self, *, s, orig):
        s.update({"foo": "foo"})
        assert s["foo"] == "foo"
        assert orig["foo"] == "foo"

    def test_update__iterable(self, *, s, orig):
        s.update([("foo", "foo")])
        assert s["foo"] == "foo"
        assert orig["foo"] == "foo"


class test_SequenceProxy:
    @pytest.fixture()
    def orig(self):
        return [1, 2, 3, 4, 5, 6, 7]

    @pytest.fixture()
    def s(self, *, orig):
        return SequenceProxy(lambda: orig)

    def test_type(self, *, s):
        assert isinstance(s, Sequence)

    def test_getitem(self, *, s):
        assert s[0] == 1
        assert s[3] == 4
        with pytest.raises(IndexError):
            s[7]

    def test_index(self, *, s):
        assert s.index(1) == 0
        assert s.index(7) == 6
        with pytest.raises(ValueError):
            s.index(8)

    def test_count(self, *, s):
        assert s.count(1) == 1
        assert s.count(8) == 0

    def test_contains(self, *, s):
        assert 1 in s
        assert 8 not in s

    def test_iter(self, *, s, orig):
        assert list(iter(s)) == list(iter(orig))

    def test_reversed(self, *, s, orig):
        assert list(reversed(s)) == list(reversed(orig))

    def test_len(self, *, s, orig):
        assert len(s) == len(orig)


class test_MutableSequenceProxy(test_SequenceProxy):
    # Note: Inherits all test cases from test_SequenceProxy

    @pytest.fixture()
    def s(self, *, orig):
        return MutableSequenceProxy(lambda: orig)

    def test_type(self, *, s):
        super().test_type(s=s)
        assert isinstance(s, MutableSequence)

    def test_insert(self, *, s, orig):
        s.insert(0, 10)
        assert s == orig == [10, 1, 2, 3, 4, 5, 6, 7]

        assert s != [1, 2, 3]

    def test_str(self, *, s, orig):
        assert str(s) == str(orig)

    def test_setitem(self, *, s, orig):
        s[0] = 10
        assert s[0] == orig[0] == 10

    def test_delitem(self, *, s, orig):
        del s[0]
        assert s == orig == [2, 3, 4, 5, 6, 7]

    def test_append(self, *, s, orig):
        s.append(8)
        assert s == orig == [1, 2, 3, 4, 5, 6, 7, 8]

    def test_extend(self, *, s, orig):
        s.extend([8, 9, 10])
        assert s == orig == [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]

    def test_reverse(self, *, s, orig):
        s.reverse()
        assert s == orig == [7, 6, 5, 4, 3, 2, 1]

    def test_pop(self, *, s, orig):
        assert s.pop() == 7
        assert s == orig == [1, 2, 3, 4, 5, 6]

    def test_remove(self, *, s, orig):
        s.remove(3)
        assert s == orig == [1, 2, 4, 5, 6, 7]
        with pytest.raises(ValueError):
            s.remove(3)

    def test_iadd(self, *, s, orig):
        s += [8, 9]
        assert s == orig == [1, 2, 3, 4, 5, 6, 7, 8, 9]


class test_SetProxy:
    @pytest.fixture()
    def orig(self):
        return {1, 2, 3, 4, 5, 6, 7}

    @pytest.fixture()
    def s(self, *, orig):
        return SetProxy(lambda: orig)

    def test_type(self, *, s):
        assert isinstance(s, AbstractSet)

    def test_contains(self, *, s):
        assert 1 in s
        assert 8 not in s

    def test_len(self, *, s):
        assert len(s) == 7

    def test_iter(self, *, s, orig):
        assert sorted(iter(s)) == sorted(orig)

    def test_isdisjoint(self, *, s):
        assert s.isdisjoint({10, 11, 12})
        assert not s.isdisjoint({2, 3})

    def test_lt(self, *, s):
        assert s < {1, 2, 3, 4, 5, 6, 7, 8}

    def test_gt(self, *, s):
        assert s > {1, 2, 3, 4, 5, 6}

    def test_le(self, *, s):
        assert s <= {1, 2, 3, 4, 5, 6, 7}

    def test_ge(self, *, s):
        assert s >= {1, 2, 3, 4, 5, 6, 7}

    def test_and(self, *, s):
        assert s & {6, 7, 8, 9} == {6, 7}

    def test_or(self, *, s):
        assert s | {6, 7, 8, 9} == {1, 2, 3, 4, 5, 6, 7, 8, 9}

    def test_sub(self, *, s):
        assert s - {1, 2, 3, 8} == {4, 5, 6, 7}

    def test_xor(self, *, s):
        assert s ^ {2, 3, 4, 5, 6, 7, 8} == {1, 8}


class test_MutableSetProxy(test_SetProxy):
    # Note: Inerhits all test cases from test_SetProxy

    @pytest.fixture()
    def s(self, *, orig):
        return MutableSetProxy(lambda: orig)

    def test_type(self, *, s):
        super().test_type(s=s)
        assert isinstance(s, MutableSet)

    def test_add(self, *, s):
        s.add(8)
        assert s == {1, 2, 3, 4, 5, 6, 7, 8}

    def test_discard(self, *, s):
        s.discard(1)
        assert s == {2, 3, 4, 5, 6, 7}
        s.discard(1)  # can repeat without error

    def test_clear(self, *, s):
        s.clear()
        assert s == set()

    def test_pop(self, *, s):
        assert s.pop() == 1

    def test_remove(self, *, s):
        s.remove(1)
        assert s == {2, 3, 4, 5, 6, 7}
        with pytest.raises(KeyError):
            s.remove(1)

    def test_ior(self, *, s):
        s |= {2, 3, 8, 9}
        assert s == {1, 2, 3, 4, 5, 6, 7, 8, 9}

    def test_iand(self, *, s):
        s &= {2, 3, 8, 9}
        assert s == {2, 3}

    def test_isub(self, *, s):
        s -= {2, 3, 4, 8, 9}
        assert s == {1, 5, 6, 7}

    def test_ixor(self, *, s):
        s ^= {0, 2, 3, 4, 5, 6, 7, 9}
        assert s == {0, 1, 9}


class test_AwaitableProxy:
    async def asynfun(self):
        return 10

    @pytest.fixture()
    def s(self):
        return AwaitableProxy(lambda: self.asynfun(), cache=True)

    @pytest.mark.asyncio
    async def test_type(self, *, s):
        assert isinstance(s, Awaitable)
        assert await s  # fixes 'was never awaited' warning.

    @pytest.mark.asyncio
    async def test_awaitable(self, *, s):
        assert await s == 10


class test_AsyncIterableProxy:
    async def aiter(self):
        for i in range(10):
            yield i

    @pytest.fixture()
    def orig(self):
        return self.aiter()

    @pytest.fixture()
    def s(self, *, orig):
        return AsyncIterableProxy(lambda: orig)

    def test_type(self, *, s):
        assert isinstance(s, AsyncIterable)

    def test_aiter(self, *, s):
        assert isinstance(s.__aiter__(), AsyncIterator)

    @pytest.mark.asyncio
    async def test_async_for(self, *, s):
        assert [i async for i in s] == list(range(10))


class test_AsyncIteratorProxy(test_AsyncIterableProxy):
    # Note: Inherits all test cases from test_AsyncIterableProxy

    @pytest.fixture()
    def s(self, *, orig):
        return AsyncIteratorProxy(lambda: orig)

    def test_type(self, *, s):
        super().test_type(s=s)
        assert isinstance(s, AsyncIterator)

    @pytest.mark.asyncio
    async def test_anext(self, *, s):
        for i in range(10):
            assert await s.__anext__() == i


class test_AsyncGeneratorProxy(test_AsyncIteratorProxy):
    # Note: Inherits all test cases from test_AsyncIteratorProxy

    class Double(Exception):
        ...  # tells coro to double multiplier

    @pytest.fixture()
    def s(self, *, orig):
        return AsyncGeneratorProxy(lambda: orig)

    def test_type(self, *, s):
        super().test_type(s=s)
        assert isinstance(s, AsyncGenerator)

    async def corogen(self):
        multiplier = 2
        while 1:
            try:
                val = yield
                yield val * multiplier
            except self.Double:
                multiplier *= 2

    @pytest.fixture()
    def _coro(self):
        return self.corogen()

    @pytest.fixture()
    def coro(self, *, _coro):
        return AsyncGeneratorProxy(lambda: _coro)

    @pytest.mark.asyncio
    async def test_coro(self, *, coro):
        await coro.__anext__()  # kickstart
        assert await coro.asend(2) == 4
        await coro.__anext__()
        assert await coro.asend(8) == 16
        await coro.athrow(self.Double())
        assert await coro.asend(2) == 8

        await coro.aclose()
        with pytest.raises(StopAsyncIteration):
            await coro.asend(2)


class test_CoroutineProxy:
    # Note: Inherits all test cases from test_AsyncIteratorProxy

    class Double(Exception):
        ...  # tells coro to double multiplier

    def corogen(self):
        multiplier = 2
        while 1:
            try:
                val = yield
                yield val * multiplier
            except self.Double:
                multiplier *= 2

    @pytest.fixture()
    def _coro(self):
        return self.corogen()

    @pytest.fixture()
    def coro(self, *, _coro):
        return CoroutineProxy(lambda: _coro)

    def test_coro(self, *, coro):
        coro.__next__()  # kickstart
        assert coro.send(2) == 4
        coro.__next__()
        assert coro.send(8) == 16
        coro.throw(self.Double())
        assert coro.send(2) == 8

        coro.close()
        with pytest.raises(StopIteration):
            coro.send(2)

    def test_await(self):
        x = MagicMock(__await__=Mock())
        s = CoroutineProxy(lambda: x)

        assert s.__await__() is x.__await__.return_value


def test_Proxy_from_source():
    class AbstractSource(abc.ABC):
        @abc.abstractmethod
        def add(self, arg):
            ...

        @abc.abstractmethod
        def mul(self, arg):
            ...

    class ConcreteSource(AbstractSource):
        def __init__(self, value):
            self.value = value

        def add(self, arg):
            return self.value + arg

        def mul(self, arg):
            return self.value * arg

    class ProxySource(Proxy[AbstractSource]):
        __proxy_source__ = AbstractSource

    on_final_mock = Mock()
    on_final = Proxy(on_final_mock)

    p = ProxySource(lambda: ConcreteSource(2))
    p._add_proxy_finalizer(on_final)
    assert p.add(4) == 6
    assert p.mul(4) == 8

    on_final_mock.assert_called_once_with()


@pytest.mark.skipif(sys.version_info < (3, 7), reason="Requires Python 3.7")
def test_Proxy_from_source__py37_class_argument():
    class AbstractSource(abc.ABC):
        @abc.abstractmethod
        def add(self, arg):
            ...

        @abc.abstractmethod
        def mul(self, arg):
            ...

    class ConcreteSource(AbstractSource):
        def __init__(self, value):
            self.value = value

        def add(self, arg):
            return self.value + arg

        def mul(self, arg):
            return self.value * arg

    class ProxySource(Proxy[AbstractSource], source=AbstractSource):
        ...

    on_final_mock = Mock()
    on_final = Proxy(on_final_mock)

    p = ProxySource(lambda: ConcreteSource(2))
    p._add_proxy_finalizer(on_final)
    assert p.add(4) == 6
    assert p.mul(4) == 8

    on_final_mock.assert_called_once_with()


def test_Proxy_from_source__no_ABCMeta():
    class Source:
        ...

    with pytest.raises(TypeError):

        class ProxySource(Proxy[Source]):
            __proxy_source__ = Source


def test_Proxy_from_source__no_abstractmethods():
    class Source(abc.ABC):
        ...

    class ProxySource(Proxy[Source]):
        __proxy_source__ = Source

    s = Source()
    p = ProxySource(lambda: s)
    assert p._get_current_object() is s
