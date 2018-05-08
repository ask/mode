from asyncio import coroutine
from typing import Any
from unittest.mock import Mock

__all__ = ['AsyncMock']


def AsyncMock(name: str = None, **kwargs: Any) -> Mock:
    coro = Mock()
    corofun = Mock(name=name)
    corofun.attach_mock(coro, 'coro')
    corofun.side_effect = coroutine(coro)
    return corofun
