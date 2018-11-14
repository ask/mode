import pytest
from mode.utils.collections import (
    FastUserDict,
    FastUserSet,
    ManagedUserDict,
    ManagedUserSet,
)
from mode.utils.mocks import Mock, call


class test_FastUserDict:

    @pytest.fixture()
    def d(self):
        class X(FastUserDict):

            def __init__(self):
                self.data = {}

        return X()

    def test_setgetdel(self, d):
        with pytest.raises(KeyError):
            d['foo']
        d['foo'] = 303
        assert d['foo'] == 303
        d['foo'] = 606
        assert d['foo'] == 606
        del(d['foo'])
        with pytest.raises(KeyError):
            d['foo']

    def test_missing(self):
        m = Mock()

        class X(FastUserDict):

            def __init__(self):
                self.data = {}

            def __missing__(self, key):
                return m(key)

        x = X()
        assert x['foo'] is m.return_value
        assert x['foo'] is m.return_value
        assert m.call_count == 2

    def test_get(self, d):
        sentinel = object()
        assert d.get('foo', sentinel) is sentinel
        d['foo'] = 303
        assert d.get('foo') == 303

    def test_len(self, d):
        assert not d
        d['foo'] = 1
        assert len(d) == 1

    def test_iter(self, d):
        d.update(a=1, b=2, c=3)
        assert list(iter(d)) == ['a', 'b', 'c']

    def test_contains(self, d):
        assert 'foo' not in d
        d['foo'] = 1
        assert 'foo' in d

    def test_clear(self, d):
        d.update(a=1, b=2, c=3)
        assert d['a'] == 1
        assert d['b'] == 2
        assert d['c'] == 3
        assert len(d) == 3
        d.clear()
        assert not d
        for k in 'a', 'b', 'c':
            with pytest.raises(KeyError):
                d[k]

    def test_keys_items_values(self, d):
        src = {'a': 1, 'b': 2, 'c': 3}
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

    def test_setgetdel(self, d):
        assert 'foo' not in d
        d.add('foo')
        assert 'foo' in d
        d.discard('foo')
        assert 'foo' not in d

    def test_len(self, d):
        assert not d
        d.add('foo')
        assert len(d) == 1
        d.add('bar')
        assert len(d) == 2

    def test_contains(self, d):
        assert 'foo' not in d
        d.add('foo')
        assert 'foo' in d

    def test_clear(self, d):
        d.update({1, 2, 3})
        assert 1 in d
        assert len(d) == 3
        d.clear()
        assert not d
        for k in 'a', 'b', 'c':
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
        assert list(sorted(iter(d))) == list(sorted([1, 2, 3]))
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
        d.add('foo')
        assert d.pop() == 'foo'
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


class test_ManagedUserDict:

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
            d['foo']
        d.key_get.assert_called_once_with('foo')
        d['foo'] = 303
        d.key_set.assert_called_once_with('foo', 303)
        assert d['foo'] == 303
        assert d.key_get.call_count == 2

        del d['foo']
        d.key_del.assert_called_once_with('foo')
        with pytest.raises(KeyError):
            d['foo']
        assert d.key_get.call_count == 3

    def test_update__args(self, d):
        d.update({'a': 1, 'b': 2, 'c': 3})
        d.key_set.assert_has_calls([
            call('a', 1),
            call('b', 2),
            call('c', 3),
        ])

    def test_update__kwargs(self, d):
        d.update(a=1, b=2, c=3)
        d.key_set.assert_has_calls([
            call('a', 1),
            call('b', 2),
            call('c', 3),
        ])

    def test_clear(self, d):
        d.update(a=1, b=2, c=3)
        assert len(d) == 3
        d.clear()
        assert not d
        d.cleared.assert_called_once_with()


class test_ManagedUserSet:

    class ManagedSet(ManagedUserSet):

        def __init__(self):
            self.data = set()
            self.on_add_mock = Mock(name='on_add_mock')
            self.on_discard_mock = Mock(name='on_discard_mock')
            self.on_change_mock = Mock(name='on_change_mock')
            self.on_clear_mock = Mock(name='on_clear')

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
        s.add('foo')
        s.on_add_mock.assert_called_once_with('foo')
        assert s == {'foo'}
        s.add('foo')
        assert s.on_add_mock.call_count == 1

    def test_discard(self, *, s):
        s.add('foo')
        s.discard('foo')
        s.on_discard_mock.assert_called_once_with('foo')
        s.discard('foo')
        assert s.on_discard_mock.call_count == 1
        assert s == set()

    def test_clear(self, *, s):
        s.raw_update({'foo', 'bar', 'baz'})
        s.clear()
        s.on_clear_mock.assert_called_once_with()
        assert s == set()

    def test_pop(self, *, s):
        s.add('foo')
        assert s.pop() == 'foo'
        s.on_discard_mock.assert_called_once_with('foo')
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
