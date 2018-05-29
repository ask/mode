from typing import Any
from mode.signals import Signal, SignalT, SyncSignal, SyncSignalT
from mode.utils.mocks import Mock
import pytest


class X:
    on_started: SignalT = Signal()
    on_stopped: SignalT = Signal()

    def __init__(self):
        self.on_started = self.on_started.with_default_sender(self)
        self.on_stopped = self.on_stopped.with_default_sender(self)


class Y(X):
    ...


class SyncX:
    on_started: SyncSignalT = SyncSignal()
    on_stopped: SyncSignalT = SyncSignal()

    def __init__(self):
        self.on_started = self.on_started.with_default_sender(self)
        self.on_stopped = self.on_stopped.with_default_sender(self)


@pytest.mark.asyncio
async def test_signals():
    x, y = X(), Y()

    on_stopped_mock = Mock()
    on_started_mock = Mock()

    @y.on_stopped.connect
    async def my_on_stopped(self, value, **kwargs):
        on_stopped_mock(self, value)

    @y.on_started.connect
    async def my_on_started(self, value, **kwargs):
        on_started_mock(self, value)

    await y.on_started.send(value=1)
    on_started_mock.assert_called_once_with(y, 1)

    await y.on_stopped.send(value=2)
    on_stopped_mock.assert_called_once_with(y, 2)
    assert on_started_mock.call_count == 1
    await x.on_started.send(value=3)
    await x.on_stopped.send(value=4)

    assert on_started_mock.call_count == 1
    assert on_stopped_mock.call_count == 1


def test_sync_signals():
    x = SyncX()
    x2 = SyncX()

    on_stopped_mock = Mock()
    on_started_mock = Mock()

    @x.on_stopped.connect
    def my_on_stopped(self, code: int, reason: str, **kwargs: Any) -> None:
        assert kwargs['signal'] == x.on_stopped
        on_stopped_mock(self, code, reason)

    @x.on_started.connect
    def my_on_started(self, **kwargs: Any) -> None:
        assert kwargs['signal'] == x.on_started
        on_started_mock(self)

    x.on_started.send()
    on_started_mock.assert_called_once_with(x)

    x.on_stopped.send(303, 'sorry not sorry')
    on_stopped_mock.assert_called_once_with(x, 303, 'sorry not sorry')
    assert on_started_mock.call_count == 1

    x.on_started.send()
    assert on_started_mock.call_count == 2

    x2.on_started.send()
    x2.on_started.send()

    assert on_started_mock.call_count == 2
