import asyncio
import logging
from typing import ContextManager
from mode.utils.compat import AsyncContextManager
from mode.utils.locks import Event
from mode.utils.mocks import Mock
import mode
import pytest


class X(mode.Service):
    ...


class Context(ContextManager):
    acquires = 0
    releases = 0

    def __enter__(self):
        self.acquires += 1
        return self

    def __exit__(self, *exc_info):
        self.releases += 1


class AsyncContext(AsyncContextManager):
    acquires = 0
    releases = 0

    async def __aenter__(self):
        self.acquires += 1
        return self

    async def __aexit__(self, *exc_info):
        self.releases += 1


class Z(mode.Service):
    x: X = None

    wait_for_shutdown = True
    did_set_shutdown = False
    background_wakeup = 0

    @mode.task
    async def _shutdown_setter(self):
        try:
            while not self.should_stop:
                await self.sleep(0.4)
                self.background_wakeup += 1
        finally:
            self.set_shutdown()
            self.did_set_shutdown = True

    async def on_start(self):
        self.did_set_shutdown = False
        self.background_wakeup = 0
        self.x = await self.add_runtime_dependency(X())
        self.add_future(self.some_coroutine())
        self.add_future(self.another_coroutine())

    async def some_coroutine(self) -> None:
        await self.sleep(1000.0)

    async def another_coroutine(self) -> None:
        # This one sleeps forever, but we kill it.
        await asyncio.sleep(10000000000000000000.0)


class Y(mode.Service):
    z: Z
    sync_context = None
    async_context = None

    def __post_init__(self):
        self.z = self.add_dependency(Z())

    async def on_start(self):
        self.sync_context = self.add_context(Context())
        self.async_context = await self.add_async_context(AsyncContext())


class Complex(mode.Service):
    x: X
    y: Y

    def __post_init__(self):
        self.x = self.add_dependency(X())
        self.y = self.add_dependency(Y())


@pytest.mark.asyncio
async def test_start_stop_simple():
    async with X():
        ...


@pytest.mark.asyncio
async def test_start_stop_restart_complex():
    async with Complex() as service:
        assert service.y.sync_context.acquires == 1
        assert service.y.async_context.acquires == 1
        assert service.y.z.x._started.is_set()
        await service.sleep(0.6)
        await service.stop()
        assert service.y.z.x._stopped.is_set()
        assert service.y.sync_context.releases == 1
        assert service.y.async_context.releases == 1
        assert service.y.z.background_wakeup
        assert service.y.z.did_set_shutdown

        await service.restart()
        assert not service.y.z.did_set_shutdown
        assert not service.y.z.background_wakeup
        assert service.y.z.x._started.is_set()
        assert service.y.sync_context.acquires == 1
        assert service.y.async_context.acquires == 1
        await service.sleep(0.6)
        await service.stop()
        assert service.y.z.x._stopped.is_set()
        assert service.y.sync_context.releases == 1
        assert service.y.async_context.releases == 1
        assert service.y.z.background_wakeup
        assert service.y.z.did_set_shutdown
        assert service.y.z.x._started.is_set()


async def crash(service, exc):
    try:
        raise exc
    except type(exc) as thrown_exc:
        await service.crash(thrown_exc)
        return thrown_exc


@pytest.mark.asyncio
async def test_crash_leaf():
    async with Complex() as service:
        error = None
        error = await crash(service.y.z, KeyError('foo'))

        # crash propagates up chain
        assert service.y.z.x._crash_reason is error
        assert service.y.z._crash_reason is error
        assert service.y._crash_reason is error
        assert service.x._crash_reason is error
        assert service._crash_reason is error


@pytest.mark.asyncio
async def test_crash_middle():
    async with Complex() as service:
        error = await crash(service.y, KeyError('foo'))
        assert service.y.z.x._crash_reason is error
        assert service.y.z._crash_reason is error
        assert service.y._crash_reason is error
        assert service.x._crash_reason is error
        assert service._crash_reason is error


@pytest.mark.asyncio
async def test_crash_head():
    async with Complex() as service:
        error = await crash(service, KeyError('foo'))
        assert service.y.z.x._crash_reason is error
        assert service.y.z._crash_reason is error
        assert service.y._crash_reason is error
        assert service.x._crash_reason is error
        assert service._crash_reason is error


@pytest.mark.asyncio
async def test_wait():
    async with X() as service:
        await service.wait(asyncio.sleep(0.1))


@pytest.mark.asyncio
async def test_wait__future_cancelled():
    async with X() as service:

        async def sleeper():
            await asyncio.sleep(10)

        fut = asyncio.ensure_future(sleeper())

        async def canceller():
            await asyncio.sleep(0.1)
            fut.cancel()

        fut2 = asyncio.ensure_future(canceller())
        with pytest.raises(asyncio.CancelledError):
            await service.wait(fut)

        fut2.cancel()


@pytest.mark.asyncio
async def test_wait__when_stopped():
    async with X() as service:

        async def sleeper():
            await asyncio.sleep(10)

        fut = asyncio.ensure_future(sleeper())

        async def stopper():
            await asyncio.sleep(0.1)
            await service.stop()

        fut2 = asyncio.ensure_future(stopper())
        assert (await service.wait(fut)).stopped

        fut2.cancel()


@pytest.mark.asyncio
async def test_wait__when_crashed():
    async with X() as service:

        async def sleeper():
            await asyncio.sleep(10)

        fut = asyncio.ensure_future(sleeper())

        async def crasher():
            await asyncio.sleep(0.1)
            try:
                raise RuntimeError('foo')
            except RuntimeError as exc:
                await service.crash(exc)

        fut2 = asyncio.ensure_future(crasher())
        assert await service.wait_for_stopped(fut)

        fut2.cancel()


@pytest.mark.asyncio
async def test_wait__multiple_events():
    async with X() as service:
        event1 = Event()
        event2 = Event()

        async def loser():
            await asyncio.sleep(1)
            event1.set()

        async def winner():
            await asyncio.sleep(0.1)
            event2.set()

        fut1 = asyncio.ensure_future(loser())
        try:
            fut2 = asyncio.ensure_future(winner())
            try:
                result = await service.wait_first(event1, event2)
                assert not result.stopped
                assert event2 in result.done
                assert event1 not in result.done
            finally:
                fut2.cancel()
        finally:
            fut1.cancel()


class MundaneLogsDefault(mode.Service):
    ...


class MundaneLogsDebug(mode.Service):
    mundane_level = 'debug'


@pytest.mark.asyncio
@pytest.mark.parametrize('service_cls,expected_level', [
    (MundaneLogsDefault, logging.INFO),
    (MundaneLogsDebug, logging.DEBUG),
])
async def test_mundane_level__default(service_cls, expected_level):
    service = service_cls()
    await assert_mundane_level_is(expected_level, service)


async def assert_mundane_level_is(level: int, service: mode.ServiceT) -> None:
    logger = service.log = Mock(name='service.log')
    async with service:
        ...
    severity = _find_logging_call_severity(logger.log, 'Starting...')
    assert severity == level


def _find_logging_call_severity(mock, needle):
    assert mock.call_count
    for call_ in mock.call_args_list:
        severity, msg, *_ = call_[0]
        if needle in msg:
            return severity
