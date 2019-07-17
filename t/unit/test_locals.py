import sys
import pytest
from mode.locals import (
    CallableMixin,
    MutableMappingProxy,
    PromiseProxy,
    Proxy,
    maybe_evaluate,
)
from mode.utils.mocks import Mock


class test_Proxy:

    def test_std_class_attributes(self):
        assert Proxy.__name__ == 'Proxy'
        assert Proxy.__module__ == 'mode.locals'
        assert isinstance(Proxy.__doc__, str)

    def test_doc(self):
        def real():
            pass
        x = Proxy(real, __doc__='foo')
        assert x.__doc__ == 'foo'

    def test_name(self):

        def real():
            """real function"""
            return 'REAL'

        x = Proxy(lambda: real, name='xyz')
        assert x.__name__ == 'xyz'

        y = Proxy(lambda: real)
        assert y.__name__ == 'real'

        assert x.__doc__ == 'real function'

        assert x.__class__ == type(real)
        assert x.__dict__ == real.__dict__
        assert repr(x) == repr(real)
        assert x.__module__

    def test_get_current_local(self):
        x = Proxy(lambda: 10)
        object.__setattr__(x, '_Proxy_local', Mock())
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
                return ['a', 'b', 'c']

        x = Proxy(lambda: X())
        assert dir(x) == ['a', 'b', 'c']

        class Y(object):

            def __dir__(self):
                raise RuntimeError()
        y = Proxy(lambda: Y())
        assert dir(y) == []

    def test_getsetdel_attr(self):

        class X(object):
            a = 1
            b = 2
            c = 3

            def __dir__(self):
                return ['a', 'b', 'c']

        v = X()

        x = Proxy(lambda: v)
        assert x.__members__ == ['a', 'b', 'c']
        assert x.a == 1
        assert x.b == 2
        assert x.c == 3

        setattr(x, 'a', 10)  # noqa: B010
        assert x.a == 10

        del(x.a)
        assert x.a == 1

    def test_dictproxy(self):
        v = {}
        x = MutableMappingProxy(lambda: v)
        x['foo'] = 42
        assert x['foo'] == 42
        assert len(x) == 1
        assert 'foo' in x
        del(x['foo'])
        with pytest.raises(KeyError):
            x['foo']
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

        class CallableProxy(Proxy, CallableMixin):
            ...

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
        x = Proxy(lambda: v)
        with x as val:
            assert val == 1234
        assert x.entered
        assert x.exited

    def test_reduce(self):

        class X(object):

            def __reduce__(self):
                return 123

        x = Proxy(lambda: X())
        assert x.__reduce__() == 123


class test_PromiseProxy:

    def test_only_evaluated_once(self):

        class X(object):
            attr = 123
            evals = 0

            def __init__(self):
                self.__class__.evals += 1

        p = PromiseProxy(X)
        assert p.attr == 123
        assert p.attr == 123
        assert X.evals == 1

    def test_maybe_evaluate(self):
        x = PromiseProxy(lambda: 30)
        assert not x.__evaluated__()
        assert maybe_evaluate(x) == 30
        assert maybe_evaluate(x) == 30

        assert maybe_evaluate(30) == 30
        assert x.__evaluated__()
