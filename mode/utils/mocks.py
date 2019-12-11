"""Mocking and testing utilities."""
import asyncio
import builtins
import sys
import types
import unittest.mock
from asyncio import coroutine
from contextlib import contextmanager
from itertools import count
from types import ModuleType
from typing import (
    Any,
    Callable,
    ContextManager,
    Iterator,
    List,
    Optional,
    Type,
    Union,
    cast,
)

__all__ = [
    'ANY',
    'IN',
    'AsyncMagicMock',
    'AsyncMock',
    'AsyncContextMock',
    'ContextMock',
    'FutureMock',
    'MagicMock',
    'Mock',
    'call',
    'mask_module',
    'patch',
    'patch_module',
]

MOCK_CALL_COUNT = count(0)


class IN:
    """Class used to check for multiple alternatives.

    .. sourcecode:: python

        assert foo.value IN(a, b)

    """

    def __init__(self, *alternatives: Any) -> None:
        self.alternatives = alternatives

    def __eq__(self, other: Any) -> bool:
        return other in self.alternatives

    def __ne__(self, other: Any) -> bool:
        return other not in self.alternatives

    def __repr__(self) -> str:
        sep = ' | '
        return f'<IN: {sep.join(map(str, self.alternatives))}>'


class Mock(unittest.mock.Mock):  # type: ignore
    """Mock object."""

    global_call_count: Optional[int] = None
    call_counts: List[int] = cast(List[int], None)

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        ret = super().__call__(*args, **kwargs)
        count = self.global_call_count = next(MOCK_CALL_COUNT)
        if self.call_counts is None:
            # mypy thinks this is unreachable as we mask that this is Optional
            self.call_counts = [count]  # type: ignore
        else:
            self.call_counts.append(count)
        return ret

    def reset_mock(self, *args: Any, **kwargs: Any) -> None:
        super().reset_mock(*args, **kwargs)
        if self.call_counts is not None:
            self.call_counts.clear()


class _ContextMock(Mock, ContextManager):
    """Internal context mock class.

    Dummy class implementing __enter__ and __exit__
    as the :keyword:`with` statement requires these to be implemented
    in the class, not just the instance.
    """

    def __enter__(self) -> '_ContextMock':
        return self

    def __exit__(self,
                 exc_type: Type[BaseException] = None,
                 exc_val: BaseException = None,
                 exc_tb: types.TracebackType = None) -> Optional[bool]:
        pass


def ContextMock(*args: Any, **kwargs: Any) -> _ContextMock:
    """Mock that mocks :keyword:`with` statement contexts."""
    obj = _ContextMock(*args, **kwargs)
    obj.attach_mock(_ContextMock(), '__enter__')
    obj.attach_mock(_ContextMock(), '__exit__')
    obj.__enter__.return_value = obj  # type: ignore
    # if __exit__ return a value the exception is ignored,
    # so it must return None here.
    obj.__exit__.return_value = None  # type: ignore
    return obj


class AsyncMock(unittest.mock.Mock):  # type: ignore
    """Mock for ``async def`` function/method or anything awaitable."""

    def __init__(self, *args: Any,
                 name: str = None,
                 **kwargs: Any) -> None:
        super().__init__(name=name)
        coro = Mock(*args, **kwargs)
        self.attach_mock(coro, 'coro')
        self.side_effect = coroutine(coro)


class AsyncMagicMock(unittest.mock.MagicMock):  # type: ignore
    """A magic mock type for ``async def`` functions/methods."""

    def __init__(self, *args: Any,
                 name: str = None,
                 **kwargs: Any) -> None:
        super().__init__(name=name)
        coro = MagicMock(*args, **kwargs)
        self.attach_mock(coro, 'coro')
        self.side_effect = coroutine(coro)


class AsyncContextMock(unittest.mock.Mock):  # type: ignore
    """Mock for :class:`typing.AsyncContextManager`.

    You can use this to mock asynchronous context managers,
    when an object with a fully defined ``__aenter__`` and ``__aexit__``
    is required.

    Here's an example mocking an :pypi:`aiohttp` client:

    .. code-block:: python

        import http
        from aiohttp.client import ClientSession
        from aiohttp.web import Response
        from mode.utils.mocks import AsyncContextManagerMock, AsyncMock, Mock

        @pytest.fixture()
        def session(monkeypatch):
            session = Mock(
                name='http_client',
                autospec=ClientSession,
                request=Mock(
                    return_value=AsyncContextManagerMock(
                        return_value=Mock(
                            autospec=Response,
                            status=http.HTTPStatus.OK,
                            json=AsyncMock(
                                return_value={'hello': 'json'},
                            ),
                        ),
                    ),
                ),
            )
            monkeypatch.setattr('where.is.ClientSession', session)
            return session

        @pytest.mark.asyncio
        async def test_session(session):
            from where.is import ClientSession
            session = ClientSession()
            async with session.get('http://example.com') as response:
                assert response.status == http.HTTPStatus.OK
                assert await response.json() == {'hello': 'json'}
    """

    def __init__(self, *args: Any,
                 aenter_return: Any = None,
                 aexit_return: Any = None,
                 side_effect: Union[Callable, BaseException] = None,
                 **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.aenter_return = aenter_return
        self.aexit_return = aexit_return
        self.side_effect = side_effect

    async def __aenter__(self) -> Any:
        mgr = self.aenter_return or self.return_value
        if self.side_effect:
            if isinstance(self.side_effect, BaseException):
                raise self.side_effect
            else:
                return self.side_effect()
        if isinstance(mgr, AsyncMock):
            return mgr.coro
        return mgr

    async def __aexit__(self, *args: Any) -> Any:
        return self.aexit_return


AsyncContextManagerMock = AsyncContextMock  # XXX compat alias


class FutureMock(unittest.mock.Mock):  # type: ignore
    """Mock a :class:`asyncio.Future`."""

    awaited = False

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._loop = asyncio.get_event_loop()

    def __await__(self) -> Any:
        self.awaited = True
        yield self()

    def assert_awaited(self) -> None:
        assert self.awaited

    def assert_not_awaited(self) -> None:
        assert not self.awaited


@contextmanager
def patch_module(*names: str, new_callable: Any = Mock) -> Iterator:
    """Mock one or modules such that every attribute is a :class:`Mock`."""
    prev = {}

    class MockModule(types.ModuleType):

        def __getattr__(self, attr: str) -> Any:
            setattr(self, attr, new_callable())
            return types.ModuleType.__getattribute__(self, attr)

    mods = []
    for name in names:
        try:
            prev[name] = sys.modules[name]
        except KeyError:
            pass
        mod = sys.modules[name] = MockModule(name)
        mods.append(mod)
    try:
        yield mods
    finally:
        for name in names:
            try:
                sys.modules[name] = prev[name]
            except KeyError:
                try:
                    del(sys.modules[name])
                except KeyError:
                    pass


@contextmanager
def mask_module(*modnames: str) -> Iterator:
    """Ban some modules from being importable inside the context.

    For example::

        >>> with mask_module('sys'):
        ...     try:
        ...         import sys
        ...     except ImportError:
        ...         print('sys not found')
        sys not found

        >>> import sys  # noqa
        >>> sys.version
        (2, 5, 2, 'final', 0)

    Taken from
    http://bitbucket.org/runeh/snippets/src/tip/missing_modules.py

    """
    realimport = builtins.__import__

    def myimp(name: str, *args: Any, **kwargs: Any) -> ModuleType:
        if name in modnames:
            raise ImportError(f'No module named {name}')
        else:
            return cast(ModuleType, realimport(name, *args, **kwargs))

    builtins.__import__ = myimp
    try:
        yield
    finally:
        builtins.__import__ = realimport


ANY = unittest.mock.ANY

MagicMock = unittest.mock.MagicMock


class _Call(unittest.mock._Call):
    # Fixes bug in Python 3.8 where call is an instance of unittest.mock._Call
    # but call.__doc__ returns a mocked method and not the class attribute.

    def __getattr__(self, attr: str) -> Any:
        if attr == '__doc__':
            return unittest.mock._Call.__doc__
        return super().__getattr__(attr)


call = _Call(from_kall=False)

patch = unittest.mock.patch
