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
