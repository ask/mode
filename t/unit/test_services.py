import asyncio
from mode import Service
from mode.utils.mocks import Mock
import pytest


class S(Service):

    def __post_init__(self):
        self.on_started_log = Mock()
        self.on_stopped_log = Mock()
        self.on_shutdown_log = Mock()

    async def on_start(self):
        self.on_started_log()

    async def on_stop(self):
        self.on_stopped_log()

    async def on_shutdown(self):
        self.on_shutdown_log()


@pytest.mark.asyncio
async def test_start_stop():
    s = S()
    assert s.state == 'init'
    await s.maybe_start()
    await s.maybe_start()
    assert s.state == 'running'
    s.on_started_log.assert_called_with()
    await s.stop()
    s.on_stopped_log.assert_called_with()
    s.on_shutdown_log.assert_called_with()
    assert s.state == 'stopping'


def test_state_stopped():
    s = S()
    s._started.set()
    s._stopped.set()
    s._shutdown.set()
    assert s.state == 'shutdown'


@pytest.mark.asyncio
async def test_aenter():
    s = S()
    async with s:
        s.on_started_log.assert_called_with()
    s.on_stopped_log.assert_called_with()
    s.on_shutdown_log.assert_called_with()


@pytest.mark.asyncio
async def test_interface():
    s = Service()
    s.on_init()
    s.__post_init__()
    await s.on_start()
    await s.on_stop()
    await s.on_shutdown()


def test_repr():
    assert repr(S())


@pytest.mark.asyncio
async def test_subclass_can_override_Service_task():

    class ATaskService(Service):
        values = []

        def __post_init__(self):
            self.event = asyncio.Event(loop=self.loop)

        @Service.task
        async def _background_task(self):
            self.values.append(1)
            self.event.set()

    class BTaskService(ATaskService):

        @Service.task
        async def _background_task(self):
            self.values.append(2)
            self.event.set()

    async with BTaskService() as service:
        await service.event.wait()

    assert ATaskService.values == [2]
