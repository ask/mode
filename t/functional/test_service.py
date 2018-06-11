import asyncio
from typing import ContextManager
from mode.utils.compat import AsyncContextManager
from mode.utils.mocks import AsyncMock
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
@pytest.mark.parametrize('latency', [
    0.0, 0.1, 0.5
])
async def test_concurrent_start_stop(latency):

    class Service(mode.Service):
        got_cancel_on = None

        def __post_init__(self) -> None:
            self.progress1 = AsyncMock(name='progress1')
            self.progress2 = AsyncMock(name='progress2')
            self.progress3 = AsyncMock(name='progress3')

        async def on_start(self) -> None:
            try:
                await asyncio.sleep(0.08)
                await self.progress1()
            except asyncio.CancelledError:
                self.got_cancel_on = 1
                raise

            try:
                await asyncio.sleep(0.3)
                await self.progress2()
            except asyncio.CancelledError:
                self.got_cancel_on = 2
                raise

            try:
                await asyncio.sleep(1.0)
                await self.progress3()
            except asyncio.CancelledError:
                self.got_cancel_on = 3
                raise

    service = Service()

    class Starter(mode.Service):

        async def on_start(self) -> None:
            await service.start()

    class Stopper(mode.Service):

        async def on_start(self) -> None:
            await service.stop()

    starter = Starter()
    stopper = Stopper()

    fut1 = asyncio.ensure_future(starter.start())
    await asyncio.sleep(latency)
    fut2 = asyncio.ensure_future(stopper.start())

    await service.wait_until_stopped()

    if latency < 1.0:
        service.progress3.assert_not_called()
    else:
        service.progress3.assert_called_once_with()
    if latency < 0.5:
        service.progress2.assert_not_called()
    else:
        service.progress2.assert_called_once_with()
    if latency < 0.1:
        service.progress1.assert_not_called()
    else:
        service.progress1.assert_called_once_with()

    if latency >= 1.0:
        assert service.got_cancel_on == 3
    elif latency >= 0.5:
        assert service.got_cancel_on == 3
    elif latency >= 0.1:
        assert service.got_cancel_on == 2
    elif latency >= 0.0:
        assert service.got_cancel_on == 1

    await fut1
    await fut2
