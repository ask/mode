import asyncio
from time import monotonic
import pytest
from mode.utils.mocks import Mock
from mode.utils.queues import (
    FlowControlEvent,
    FlowControlQueue,
    ThrowableQueue,
)


class test_FlowControlEvent:

    def test_constructor(self):
        assert not FlowControlEvent(initially_suspended=True).is_active()
        assert FlowControlEvent(initially_suspended=False).is_active()

    def test_loop__default(self):
        assert FlowControlEvent().loop is None

    def test_loop__custom(self):
        loop = Mock(name='loop')
        assert FlowControlEvent(loop=loop).loop is loop


class test_FlowControlQueue:

    @pytest.mark.asyncio
    async def test_suspend_resume(self):
        flow_control = FlowControlEvent()
        queue = FlowControlQueue(flow_control=flow_control)
        flow_control.resume()
        await queue.put(1)
        flow_control.suspend()
        asyncio.ensure_future(self._resume_soon(0.2, flow_control))
        time_now = monotonic()
        await queue.put(2)
        assert monotonic() - time_now > 0.1
        assert await queue.get() == 1
        assert await queue.get() == 2

    @pytest.mark.asyncio
    async def test_suspend_resume__clear_on_resume(self):
        flow_control = FlowControlEvent()
        queue = FlowControlQueue(
            clear_on_resume=True,
            flow_control=flow_control,
        )
        assert queue in flow_control._queues
        flow_control.resume()
        await queue.put(1)
        flow_control.suspend()
        asyncio.ensure_future(self._resume_soon(0.2, flow_control))
        time_now = monotonic()
        await queue.put(2)
        assert monotonic() - time_now > 0.1
        await queue.get() == 2

    @pytest.mark.asyncio
    async def test_suspend_resume__initially_suspended(self):
        flow_control = FlowControlEvent(initially_suspended=True)
        queue = FlowControlQueue(flow_control=flow_control)
        asyncio.ensure_future(self._resume_soon(0.2, flow_control))
        time_now = monotonic()
        await queue.put(1)
        assert await queue.get() == 1
        assert monotonic() - time_now > 0.1

    @pytest.mark.asyncio
    async def test_suspend_resume__initially_resumed(self):
        flow_control = FlowControlEvent(initially_suspended=False)
        queue = FlowControlQueue(flow_control=flow_control)
        await queue.put(1)
        assert await queue.get() == 1

    async def _resume_soon(self, timeout, flow_control):
        await asyncio.sleep(timeout)
        flow_control.resume()


class test_ThrowableQueue:

    @pytest.mark.asyncio
    async def test_get__throw_first_in_buffer(self):
        flow_control = FlowControlEvent(initially_suspended=False)
        queue = ThrowableQueue(flow_control=flow_control)

        await queue.put(1)
        await queue.put(2)
        assert await queue.get() == 1
        assert await queue.get() == 2
        await queue.put(3)
        await queue.put(4)
        await queue.throw(KeyError('foo'))
        with pytest.raises(KeyError):
            await queue.get()
        assert await queue.get() == 3
        assert await queue.get() == 4
        await queue.throw(ValueError('bar'))
        with pytest.raises(ValueError):
            await queue.get()

    @pytest.mark.asyncio
    async def test_get_nowait_throw_first_in_buffer(self):
        flow_control = FlowControlEvent(initially_suspended=False)
        queue = ThrowableQueue(flow_control=flow_control)

        await queue.put(1)
        await queue.put(2)
        assert queue.get_nowait() == 1
        assert queue.get_nowait() == 2
        await queue.put(3)
        await queue.put(4)
        await queue.throw(KeyError('foo'))
        with pytest.raises(KeyError):
            queue.get_nowait()
        assert queue.get_nowait() == 3
        assert queue.get_nowait() == 4
        await queue.throw(ValueError('bar'))
        with pytest.raises(ValueError):
            queue.get_nowait()

    def test_get_nowait_empty(self):
        flow_control = FlowControlEvent(initially_suspended=False)
        queue = ThrowableQueue(flow_control=flow_control)

        with pytest.raises(asyncio.QueueEmpty):
            queue.get_nowait()
