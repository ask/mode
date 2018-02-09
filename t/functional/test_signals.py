import pytest
from unittest.mock import Mock
from mode.signals import HasSignals, Signal, SignalT



class X(HasSignals):
    on_started: SignalT = Signal()
    on_stopped: SignalT = Signal()




class Y(X):

    def __init__(self, mock: Mock = None) -> None:
        self.mock = mock if mock is not None else Mock()
        super().__init__()

    async def on_stopped(self, value, **kwargs):
        self.mock(self, value)


@pytest.mark.asyncio
async def test_signals():
    x, y = X(), Y()

    on_stopped_mock = Mock()
    @y.on_stopped.connect
    async def my_on_stopped(self, value, **kwargs):
        on_stopped_mock(self, value)

    on_started_mock = Mock()
    @y.on_started.connect
    async def my_on_started(self, value, **kwargs):
        on_started_mock(self, value)

    await y.on_started.send(value=1)

    on_started_mock.assert_called_once_with(y, 1)
    await y.on_stopped.send(value=2)

    y.mock.assert_called_once_with(y, 2)
    on_stopped_mock.assert_called_once_with(y, 2)
    assert on_started_mock.call_count == 1
    await x.on_started.send(value=3)
    await x.on_stopped.send(value=4)

    assert on_started_mock.call_count == 1
    assert on_stopped_mock.call_count == 1
    assert y.mock.call_count == 1
