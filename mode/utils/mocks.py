import asyncio
import unittest.mock
from asyncio import coroutine
from typing import Any

__all__ = [
    'ANY',
    'AsyncMock',
    'AsyncContextManagerMock',
    'FutureMock',
    'MagicMock',
    'Mock',
    'call',
    'patch',
]


class AsyncMock(unittest.mock.Mock):

    def __init__(self, *args: Any,
                 name: str = None,
                 **kwargs: Any) -> None:
        super().__init__(name=name)
        coro = Mock(*args, **kwargs)
        self.attach_mock(coro, 'coro')
        self.side_effect = coroutine(coro)


class AsyncContextManagerMock(unittest.mock.Mock):
    """Mock for :class:`typing.AsyncContextManager`

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
                 **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.aenter_return = aenter_return
        self.aexit_return = aexit_return

    async def __aenter__(self) -> Any:
        mgr = self.aenter_return or self.return_value
        if isinstance(mgr, AsyncMock):
            return mgr.coro
        return mgr

    async def __aexit__(self, *args: Any) -> Any:
        return self.aexit_return


class FutureMock(unittest.mock.Mock):
    awaited = False

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._loop = asyncio.get_event_loop()

    def __await__(self):
        self.awaited = True
        yield self()

    def assert_awaited(self):
        assert self.awaited

    def assert_not_awaited(self):
        assert not self.awaited


ANY = unittest.mock.ANY
Mock = unittest.mock.Mock
MagicMock = unittest.mock.MagicMock
call = unittest.mock.call
patch = unittest.mock.patch
