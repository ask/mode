import asyncio
import pytest
from mode import Service


class X(Service):
    ...


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
