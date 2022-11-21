import pickle
from unittest.mock import Mock, call, patch

import pytest

from mode.utils.collections import (
    AttributeDictMixin,
    DictAttribute,
    FastUserDict,
    FastUserSet,
    Heap,
    LRUCache,
    ManagedUserDict,
    ManagedUserSet,
    force_mapping,
)


class test_FastUserDict:
    @pytest.fixture()
    def d(self):
        class X(FastUserDict):
            def __init__(self):
                self.data = {}

        return X()

    def test_fromkeys(self, d):
        x = d.fromkeys(["a", "b", "c"], value=3)
        assert x == {"a": 3, "b": 3, "c": 3}
        assert type(x) is type(d)

    def test__missing__(self, d):
        i = 0

        class X(type(d)):
            def __missing__(self, key):
                nonlocal i
                i += 1
                return "default", i

        x = X()
        assert x["foo"] == ("default", 1)
        assert x["foo"] == ("default", 2)
        assert x["bar"] == ("default", 3)
        x["foo"] = "moo"
        assert x["foo"] == "moo"

    def test_repr(self, d):
        d.update({"foo": "bar", "baz": 300.33})
        assert repr(d) == repr(d.data)

    def test_copy(self, d):
        d.update({"foo": [1, 2, 3], "bar": "baz"})
        e = d.copy()
        assert e == d
        assert e is not d
        assert e["foo"] is d["foo"], "shallow copy"

    def test_setgetdel(self, d):
        with pytest.raises(KeyError):
            d["foo"]
        d["foo"] = 303
        assert d["foo"] == 303
        d["foo"] = 606
        assert d["foo"] == 606
        del d["foo"]
        with pytest.raises(KeyError):
            d["foo"]

    def test_missing(self):
        m = Mock()

        class X(FastUserDict):
            def __init__(self):
                self.data = {}

            def __missing__(self, key):
                return m(key)

        x = X()
        assert x["foo"] is m.return_value
        assert x["foo"] is m.return_value
        assert m.call_count == 2

    def test_get(self, d):
        sentinel = object()
        assert d.get("foo", sentinel) is sentinel
        d["foo"] = 303
        assert d.get("foo") == 303

    def test_len(self, d):
        assert not d
        d["foo"] = 1
        assert len(d) == 1

    def test_iter(self, d):
        d.update(a=1, b=2, c=3)
        assert list(iter(d)) == ["a", "b", "c"]

    def test_contains(self, d):
        assert "foo" not in d
        d["foo"] = 1
        assert "foo" in d

    def test_clear(self, d):
        d.update(a=1, b=2, c=3)
        assert d["a"] == 1
        assert d["b"] == 2
        assert d["c"] == 3
        assert len(d) == 3
        d.clear()
        assert not d
        for k in "a", "b", "c":
            with pytest.raises(KeyError):
                d[k]

    def test_keys_items_values(self, d):
        src = {"a": 1, "b": 2, "c": 3}
        d.update(src)
        assert list(d.keys()) == list(src.keys())
        assert list(d.items()) == list(src.items())
        assert list(d.values()) == list(src.values())


class test_FastUserSet:
    class X(FastUserSet):
        def __init__(self):
            self.data = set()

    @pytest.fixture()
    def d(self):
        return self.X()

    def test_reduce(self, d):
        assert d.__reduce__()

    def test_reduce_ex(self, d):
        assert d.__reduce_ex__(1)

    def test_pickle(self, d):
        d.update({1, 2, 3, 4, 5})
        e = pickle.loads(pickle.dumps(d))
        assert isinstance(e, set), "default reduce to built-in set"
        assert d == e

    def test_setgetdel(self, d):
        assert "foo" not in d
        d.add("foo")
        assert "foo" in d
        d.discard("foo")
        assert "foo" not in d

    def test_len(self, d):
        assert not d
        d.add("foo")
        assert len(d) == 1
        d.add("bar")
        assert len(d) == 2

    def test_contains(self, d):
        assert "foo" not in d
        d.add("foo")
        assert "foo" in d

    def test_clear(self, d):
        d.update({1, 2, 3})
        assert 1 in d
        assert len(d) == 3
        d.clear()
        assert not d
        for k in "a", "b", "c":
            assert k not in d

    def test_and(self, d):
        d.update({1, 2, 3})
        assert (d & {2, 3, 4}) == {2, 3}
        assert ({2, 3, 4} & d) == {2, 3}

    def test_ge(self, d):
        d.update({1, 2, 3})
        assert d >= {1, 2, 3}
        assert d >= {1, 2}
        assert d >= {1}

    def test_le(self, d):
        d.update({1, 2, 3})
        assert d <= {1, 2, 3, 4}
        assert d <= {1, 2, 3}

    def test_iter(self, d):
        d.update({1, 2, 3})
        assert sorted(iter(d)) == sorted([1, 2, 3])
        assert set(d) == d

    def test_or(self, d):
        d.update({1, 2, 3})
        assert (d | {3, 4, 5}) == {1, 2, 3, 4, 5}
        assert ({3, 4, 5} | d) == {1, 2, 3, 4, 5}

    def test_repr(self, d):
        d.update({1, 2, 3})
        assert repr(d) == repr({1, 2, 3})

    def test_sub(self, d):
        d.update({1, 2, 3})
        assert (d - {2, 3, 4}) == {1}
        assert ({2, 3, 4} - d) == {1}

    def test_xor(self, d):
        d.update({1, 2, 3})
        assert (d ^ {2, 3, 4, 5}) == {1, 4, 5}
        assert ({2, 3, 4, 5} ^ d) == {1, 4, 5}

    def test_sizeof(self, d):
        d.update({1, 2, 3})
        assert d.__sizeof__() == ({1, 2, 3}).__sizeof__()

    def test_str(self, d):
        d.update({1, 2, 3})
        assert str(d) == str({1, 2, 3})

    def test_copy(self, d):
        d.update({1, 2, 3})
        assert d.copy() == {1, 2, 3}
        z = d.copy()
        z.add(4)
        assert d == {1, 2, 3}

    def test_difference(self, d):
        d.update({1, 2, 3})
        assert d.difference({2, 3, 4}) == {1}

    def test_intersection(self, d):
        d.update({1, 2, 3})
        assert d.intersection({2, 3, 4}) == {2, 3}

    def test_isdisjoin(self, d):
        d.update({1, 2, 3})
        assert not d.isdisjoint({1, 2, 3})
        assert not d.isdisjoint({1})
        assert not d.isdisjoint({1, 2})
        assert not d.isdisjoint({1, 3, 4, 5})
        assert d.isdisjoint({4, 5, 6})

    def test_issubset(self, d):
        d.update({1, 2, 3})
        assert d.issubset({1, 2, 3, 4, 5})
        assert not d.issubset({1, 3, 4, 5})

    def test_issuperset(self, d):
        d.update({1, 2, 3})
        assert not d.issuperset({1, 2, 3, 4, 5, 6})
        assert d.issuperset({1, 2})
        assert d.issuperset({1})

    def test_symmetric_difference(self, d):
        d.update({1, 2, 3})
        assert d.symmetric_difference({2, 3, 4, 5}) == {1, 4, 5}

    def test_union(self, d):
        d.update({1, 2, 3})
        assert d.union({3, 4, 5}) == {1, 2, 3, 4, 5}

    def test_pop(self, d):
        d.add("foo")
        assert d.pop() == "foo"
        assert d == set()
        with pytest.raises(KeyError):
            d.pop()

    def test__iand__(self, d):
        d.update({1, 2, 3, 5})
        d &= {2, 3, 4}
        assert d == {2, 3}
        assert isinstance(d, self.X)

    def test__ior__(self, d):
        d.update({1, 2, 3})
        d |= {1, 2, 4, 5, 6}
        assert d == {1, 2, 3, 4, 5, 6}
        assert isinstance(d, self.X)

    def test__isub__(self, d):
        d.update({1, 2, 3})
        d -= {2, 3, 4, 5}
        assert d == {1}
        assert isinstance(d, self.X)

    def test__ixor__(self, d):
        d.update({1, 2, 3})
        d ^= {2, 3, 4, 5}
        assert d == {1, 4, 5}
        assert isinstance(d, self.X)

    def test_difference_update(self, d):
        d.update({1, 2, 3})
        d.difference_update({2, 3, 4, 5})
        assert d == {1}

    def test_intersection_update(self, d):
        d.update({1, 2, 3, 5})
        d.intersection_update({2, 3, 4})
        assert d == {2, 3}

    def test_symmetric_difference_update(self, d):
        d.update({1, 2, 3})
        d.symmetric_difference_update({2, 3, 4, 5})
        assert d == {1, 4, 5}

    def test_update(self, d):
        d.update({1, 2, 3})
        d.update({1, 2, 4, 5, 6})
        assert d == {1, 2, 3, 4, 5, 6}

    def test_remove(self, d):
        d.update({1, 2, 3})
        d.remove(3)
        assert d == {1, 2}


class test_ManagedUserDict:
    def test_interface_on_key_get(self):
        ManagedUserDict().on_key_get("k")

    def test_interface_on_key_set(self):
        ManagedUserDict().on_key_set("k", "v")

    def test_interface_on_key_del(self):
        ManagedUserDict().on_key_del("k")

    def test_interface_on_clear(self):
        ManagedUserDict().on_clear()

    @pytest.fixture
    def d(self):
        class X(ManagedUserDict):
            def __init__(self):
                self.key_get = Mock()
                self.key_set = Mock()
                self.key_del = Mock()
                self.cleared = Mock()
                self.data = {}

            def on_key_get(self, key):
                self.key_get(key)

            def on_key_set(self, key, value):
                self.key_set(key, value)

            def on_key_del(self, key):
                self.key_del(key)

            def on_clear(self):
                self.cleared()

        return X()

    def test_get_set_del(self, d):
        with pytest.raises(KeyError):
            d["foo"]
        d.key_get.assert_called_once_with("foo")
        d["foo"] = 303
        d.key_set.assert_called_once_with("foo", 303)
        assert d["foo"] == 303
        assert d.key_get.call_count == 2

        del d["foo"]
        d.key_del.assert_called_once_with("foo")
        with pytest.raises(KeyError):
            d["foo"]
        assert d.key_get.call_count == 3

    def test_update__args(self, d):
        d.update({"a": 1, "b": 2, "c": 3})
        d.key_set.assert_has_calls(
            [
                call("a", 1),
                call("b", 2),
                call("c", 3),
            ]
        )

    def test_update__kwargs(self, d):
        d.update(a=1, b=2, c=3)
        d.key_set.assert_has_calls(
            [
                call("a", 1),
                call("b", 2),
                call("c", 3),
            ]
        )

    def test_clear(self, d):
        d.update(a=1, b=2, c=3)
        assert len(d) == 3
        d.clear()
        assert not d
        d.cleared.assert_called_once_with()

    def test_raw_update(self, d):
        d.raw_update(a=1, b=2)
        assert d == {"a": 1, "b": 2}


class test_ManagedUserSet:
    def test_interface_on_add(self):
        ManagedUserSet().on_add("val")

    def test_interface_on_discard(self):
        ManagedUserSet().on_discard("val")

    def test_interface_on_clear(self):
        ManagedUserSet().on_clear()

    def test_interface_on_change(self):
        ManagedUserSet().on_change({1, 2}, {3, 4})

    class ManagedSet(ManagedUserSet):
        def __init__(self):
            self.data = set()
            self.on_add_mock = Mock(name="on_add_mock")
            self.on_discard_mock = Mock(name="on_discard_mock")
            self.on_change_mock = Mock(name="on_change_mock")
            self.on_clear_mock = Mock(name="on_clear")

        def on_add(self, element):
            self.on_add_mock(element)

        def on_discard(self, element):
            self.on_discard_mock(element)

        def on_change(self, added, removed):
            self.on_change_mock(added=added, removed=removed)

        def on_clear(self):
            self.on_clear_mock()

    @pytest.fixture()
    def s(self):
        return self.ManagedSet()

    def test_add(self, *, s):
        s.add("foo")
        s.on_add_mock.assert_called_once_with("foo")
        assert s == {"foo"}
        s.add("foo")
        assert s.on_add_mock.call_count == 1

    def test_discard(self, *, s):
        s.add("foo")
        s.discard("foo")
        s.on_discard_mock.assert_called_once_with("foo")
        s.discard("foo")
        assert s.on_discard_mock.call_count == 1
        assert s == set()

    def test_clear(self, *, s):
        s.raw_update({"foo", "bar", "baz"})
        s.clear()
        s.on_clear_mock.assert_called_once_with()
        assert s == set()

    def test_pop(self, *, s):
        s.add("foo")
        assert s.pop() == "foo"
        s.on_discard_mock.assert_called_once_with("foo")
        assert s == set()
        with pytest.raises(KeyError):
            s.pop()

    def test__iand__(self, *, s):
        s.raw_update({1, 2, 3, 5})
        s &= {2, 3, 4}
        assert s == {2, 3}
        assert isinstance(s, self.ManagedSet)
        s.on_change_mock.assert_called_once_with(added=set(), removed={1, 5})

    def test__ior__(self, *, s):
        s.raw_update({1, 2, 3})
        s |= {1, 2, 4, 5, 6}
        assert s == {1, 2, 3, 4, 5, 6}
        assert isinstance(s, self.ManagedSet)
        s.on_change_mock.assert_called_once_with(
            added={4, 5, 6},
            removed=set(),
        )

    def test__isub__(self, *, s):
        s.raw_update({1, 2, 3})
        s -= {2, 3, 4, 5}
        assert s == {1}
        assert isinstance(s, self.ManagedSet)
        s.on_change_mock.assert_called_once_with(added=set(), removed={2, 3})

    def test__ixor__(self, *, s):
        s.raw_update({1, 2, 3})
        s ^= {2, 3, 4, 5}
        assert s == {1, 4, 5}
        assert isinstance(s, self.ManagedSet)
        s.on_change_mock.assert_called_once_with(added={4, 5}, removed={2, 3})

    def test_difference_update(self, *, s):
        s.raw_update({1, 2, 3})
        s.difference_update({2, 3, 4, 5})
        assert s == {1}
        s.on_change_mock.assert_called_once_with(added=set(), removed={2, 3})

    def test_intersection_update(self, *, s):
        s.raw_update({1, 2, 3, 5})
        s.intersection_update({2, 3, 4})
        assert s == {2, 3}
        assert isinstance(s, self.ManagedSet)
        s.on_change_mock.assert_called_once_with(added=set(), removed={1, 5})

    def test_symmetric_difference_update(self, *, s):
        s.raw_update({1, 2, 3})
        s.symmetric_difference_update({2, 3, 4, 5})
        assert s == {1, 4, 5}
        assert isinstance(s, self.ManagedSet)
        s.on_change_mock.assert_called_once_with(added={4, 5}, removed={2, 3})

    def test_update(self, *, s):
        s.raw_update({1, 2, 3})
        s.update({1, 2, 4, 5, 6})
        assert s == {1, 2, 3, 4, 5, 6}
        assert isinstance(s, self.ManagedSet)
        s.on_change_mock.assert_called_once_with(
            added={4, 5, 6},
            removed=set(),
        )


class test_LRUCache:
    @pytest.fixture()
    def d(self):
        return LRUCache(limit=10)

    def test_get_set_update_pop(self, d):
        for i in range(100):
            d[i] = i
        assert len(d) == 10
        for i in range(90, 100):
            assert d[i] == i
        d.update({i: i for i in range(100, 200)})
        assert len(d) == 10
        for i in range(190, 200):
            assert d[i] == i

        d.limit = None
        d.update({i: i for i in range(100, 200)})
        assert len(d) == 100
        for i in range(100, 200):
            assert d[i] == i

        assert d.popitem() == (199, 199)

    def test_iter_keys_items_values(self, d):
        d.update({"a": 1, "b": 2, "c": 3})
        assert list(iter(d)) == ["a", "b", "c"]
        assert list(iter(d)) == list(d.keys())
        assert list(d.values()) == [1, 2, 3]
        assert list(d.items()) == [("a", 1), ("b", 2), ("c", 3)]

    def test_incr(self, d):
        d["a"] = "0"
        assert d.incr("a") == 1
        assert d.incr("a") == 2

    def test__new_lock(self, d):
        d.thread_safety = True
        with patch("threading.RLock") as RLock:
            res = d._new_lock()
            assert res is RLock.return_value

    def test_pickle(self, d):
        d.update({"a": 1, "b": 2, "c": 3})
        e = pickle.loads(pickle.dumps(d))
        assert e == d


class test_AttributeDictMixin:
    @pytest.fixture()
    def d(self):
        class X(dict, AttributeDictMixin):
            ...

        return X()

    def test_set_get(self, *, d):
        with pytest.raises(AttributeError):
            d.foo
        d.foo = 1
        assert d.foo == 1
        assert d["foo"] == 1


class test_DictAttribute:
    @pytest.fixture()
    def d(self):
        class Object:
            def __init__(self, name):
                self.name = name

        return DictAttribute(Object("foo"))

    def test_get_set(self, *, d):
        assert d["name"] == "foo"
        assert d.name == "foo"
        assert len(d) == 1
        d.name = "bar"
        d.setdefault("name", "baz")
        assert d.get("name") == "bar"
        assert d.get("foo") is None

        d.setdefault("foo", "moo")
        assert d.foo == "moo"
        assert len(d) == 2

        with pytest.raises(NotImplementedError):
            del d["foo"]

        assert list(d) == dir(d.obj)
        assert list(d._keys()) == dir(d.obj)
        assert list(d._values()) == [getattr(d.obj, k) for k in d.keys()]
        assert list(d._items()) == [(k, getattr(d.obj, k)) for k in d.keys()]


def test_force_mapping():
    class Object:
        def __init__(self, name):
            self.name = name

    obj = Object("foo")
    obj._wrapped = Object("bar")
    assert force_mapping(obj)["name"] == "foo"

    with patch("mode.utils.collections.LazyObject", Object):
        assert force_mapping(obj)["name"] == "bar"


class test_Heap:
    def test_type_generic(self):
        class H(Heap[int]):
            pass

        h = H([999, 3, 9, 100])
        assert h.pushpop(888) == 3
        assert h.pop() == 9

    def test_heap(self):
        h = Heap()
        h.push((300, "foo"))
        assert len(h) == 1
        assert h[0] == (300, "foo")
        h.push((800, "bar"))
        assert len(h) == 2
        assert h[0] == (300, "foo")
        assert h.pop() == (300, "foo")
        assert len(h) == 1
        assert h[0] == (800, "bar")
        assert h.pushpop((100, "baz")) == (100, "baz")
        assert len(h) == 1
        assert h[0] == (800, "bar")
        h.push((300, "foo"))
        assert len(h) == 2
        assert h.replace((400, "xuzzy")) == (300, "foo")
        assert len(h) == 2
        assert h[0] == (400, "xuzzy")
        h.push((300, "foo"))
        assert len(h) == 3
        assert h[0] == (300, "foo")

        assert h.nsmallest(2) == [(300, "foo"), (400, "xuzzy")]
        assert h.nlargest(2) == [(800, "bar"), (400, "xuzzy")]

        assert str(h)
        assert repr(h)
        h.insert(0, (999, "misplaced"))
        assert h[0] == (999, "misplaced")

        h[0] = (888, "misplaced")
        assert h[0] == (888, "misplaced")
        del h[0]
        assert h[0] == (300, "foo")

        assert h.pop() == (300, "foo")
        assert len(h) == 2
        assert h
        assert h.pop() == (400, "xuzzy")
        assert len(h) == 1
        assert h.pop() == (800, "bar")
        assert not len(h)
        assert not h

        with pytest.raises(IndexError):
            h.pop()
