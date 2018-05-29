import asyncio
import unittest.mock
from asyncio import coroutine
from typing import Any

__all__ = [
    'ANY',
    'AsyncMock',
    'FutureMock',
    'MagicMock',
    'Mock',
    'call',
    'patch',
]


def AsyncMock(name: str = None, **kwargs: Any) -> unittest.mock.Mock:
    coro = Mock(**kwargs)
    corofun = Mock(name=name)
    corofun.attach_mock(coro, 'coro')
    corofun.side_effect = coroutine(coro)
    return corofun


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
