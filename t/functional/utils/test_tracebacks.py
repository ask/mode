import asyncio
from unittest.mock import Mock, patch

import pytest

from mode.utils.tracebacks import Traceback, format_task_stack


@pytest.mark.asyncio
async def test_format_task_stack():

    on_done = asyncio.Event()

    async def foo():
        await bar()

    async def bar():
        await baz()

    async def baz():
        task = asyncio.ensure_future(xuz())
        await asyncio.sleep(0.1)
        for _ in range(100):
            assert format_task_stack(task, limit=0)
            assert format_task_stack(task, limit=-300)
            assert format_task_stack(task, limit=None)
            assert format_task_stack(task, limit=3, capture_locals=True)
        await on_done.wait()

    async def xuz():
        await xuz1()
        await xuz2()

    async def xuz1():
        await asyncio.sleep(1)

    async def xuz2():
        await asyncio.sleep(0.1)
        [i async for i in xuz3()]
        on_done.set()

    async def xuz3():
        for i in range(100):
            yield i

    await foo()

    task = asyncio.ensure_future(xuz2())
    await asyncio.sleep(0.05)
    assert format_task_stack(task, limit=None)

    async def moo():
        await asyncio.sleep(0.1)

    task = asyncio.ensure_future(moo())
    await asyncio.sleep(0.05)
    assert format_task_stack(task, limit=None)


class test_Traceback:
    @pytest.fixture()
    def frame(self):
        return Mock(name="frame")

    @pytest.fixture()
    def tb(self, *, frame):
        return Traceback(frame)

    def test_from_coroutine__async_generator_asend(self, tb):
        class async_generator_asend:
            f_lineno = 303
            f_lasti = None

        assert Traceback.from_coroutine(async_generator_asend())

    def test_from_coroutine__unknown(self, tb):
        class foo_frame:
            f_lineno = 303
            f_lasti = None

        with pytest.raises(AttributeError):
            Traceback.from_coroutine(foo_frame())

    def test_too_many_frames(self, tb):
        class coro:
            cr_frame = Mock()
            cr_await = None

        coro.cr_frame.tb_next = coro.cr_frame  # loop

        Traceback.from_coroutine(coro(), limit=10)

    def test_no_frames(self, tb):
        class coro:
            cr_frame = None
            cr_await = Mock()

        with patch("asyncio.iscoroutine") as iscoroutine:
            iscoroutine.return_value = True
            Traceback.from_coroutine(coro(), limit=10)
