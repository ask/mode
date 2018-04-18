import asyncio
from typing import ContextManager
from mode.utils.compat import AsyncContextManager
import pytest
from mode import Service


class X(Service):
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


class Z(Service):
    x: X = None

    wait_for_shutdown = True
    did_set_shutdown = False
    background_wakeup = 0

    @Service.task
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


class Y(Service):
    z: Z
    sync_context = None
    async_context = None

    def __post_init__(self):
        self.z = self.add_dependency(Z())

    async def on_start(self):
        self.sync_context = await self.add_context(Context())
        self.async_context = await self.add_context(AsyncContext())


class Complex(Service):
    x: X
    y: Y

    def __post_init__(self):
        self.x = self.add_dependency(X())
        self.y = self.add_dependency(Y())


@pytest.mark.asyncio
async def test_start_stop_simple():
    service = X()
    await service.start()
    await service.stop()


@pytest.mark.asyncio
async def test_start_stop_restart_complex():
    service = Complex()
    await service.start()
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


@pytest.mark.asyncio
async def test_wait():
    service = X()
    await service.start()
    await service.wait(asyncio.sleep(0.1))


@pytest.mark.asyncio
async def test_wait__future_cancelled():
    service = X()
    await service.start()

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
    service = X()
    await service.start()

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
    service = X()
    await service.start()

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
