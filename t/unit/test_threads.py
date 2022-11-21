import asyncio
import sys
import threading
from asyncio.locks import Event
from unittest.mock import ANY, Mock, patch

if sys.version_info < (3, 8):
    from mock.mock import AsyncMock
else:
    from unittest.mock import AsyncMock

import pytest

from mode.threads import MethodQueue, QueueServiceThread, ServiceThread, WorkerThread
from mode.utils.futures import done_future


class test_WorkerThread:
    @pytest.fixture()
    def service(self):
        return Mock(name="service")

    @pytest.fixture()
    def thread(self, *, service):
        return WorkerThread(service)

    def test_run(self, *, thread, service):
        thread.run()
        service._start_thread.assert_called_once_with()
        assert service.is_stopped.is_set()

    def test_stop__alive(self, *, thread):
        thread.is_stopped = Mock()
        thread.is_alive = Mock(return_value=True)
        thread.join = Mock()
        thread.stop()

        thread.is_stopped.wait.assert_called_once_with()
        thread.join.assert_called_with(threading.TIMEOUT_MAX)

    def test_stop__not_alive(self, *, thread):
        thread.is_stopped = Mock()
        thread.is_alive = Mock(return_value=False)
        thread.join = Mock()
        thread.stop()

        thread.is_stopped.wait.assert_called_once_with()
        thread.join.assert_not_called()


class test_ServiceThread:
    @pytest.fixture
    def loop(self, *, event_loop):
        return event_loop

    @pytest.fixture
    def thread_loop(self):
        return Mock(name="thread_loop")

    @pytest.fixture
    def Worker(self):
        return Mock(spec=WorkerThread, name="Worker")

    @pytest.fixture
    def thread(self, *, Worker, loop, thread_loop):
        return ServiceThread(Worker=Worker, loop=loop, thread_loop=thread_loop)

    @pytest.mark.asyncio
    async def test_on_thread_stop(self, *, thread):
        await thread.on_thread_stop()

    def test_constructor_worker_argument(self):
        Worker = Mock(spec=WorkerThread)
        assert ServiceThread(Worker=Worker).Worker is Worker
        assert ServiceThread(Worker=None).Worker

    def test_new_shutdown_event(self, *, thread):
        event = thread._new_shutdown_event()
        assert isinstance(event, Event)
        assert not event.is_set()

    @pytest.mark.asyncio
    async def test_maybe_start(self, *, thread):
        thread.start = AsyncMock(name="start")
        thread._thread_started.set()
        await thread.maybe_start()
        thread.start.assert_not_awaited()

        thread._thread_started.clear()
        await thread.maybe_start()
        thread.start.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_start(self, *, event_loop, thread):
        thread.add_future = AsyncMock(name="thread.add_future")
        thread._thread_running = None
        assert thread.parent_loop == event_loop
        asyncio.ensure_future(self._wait_for_event(thread))
        await thread.start()

        thread.Worker.assert_called_once_with(thread)
        thread.Worker.return_value.start.assert_called_once_with()

        assert thread._thread_started.is_set()

    @pytest.mark.asyncio
    async def test_start__no_wait(self, *, event_loop, thread):
        thread.add_future = Mock(name="thread.add_future")
        thread.wait_for_thread = False
        thread._thread_running = None
        assert thread.parent_loop == event_loop
        asyncio.ensure_future(self._wait_for_event(thread))
        await thread.start()

        thread.Worker.assert_called_once_with(thread)
        thread.Worker.return_value.start.assert_called_once_with()

        assert thread._thread_started.is_set()

    async def _wait_for_event(self, thread):
        count = 0
        while thread._thread_running is None:
            await asyncio.sleep(0.1)
            count += 1
            if count >= 10:  # fast fail to avoid block tests
                raise RuntimeError("Test failed")

        if not thread._thread_running.done():
            thread._thread_running.set_result(None)

    @pytest.mark.asyncio
    async def test_start__already_started_raises(self, *, thread):
        thread._thread_started.set()
        with pytest.raises(AssertionError):
            await thread.start()

    def test_start_thread(self, *, thread):
        thread._serve = Mock(name="thread._serve")
        with patch("asyncio.set_event_loop") as set_event_loop:
            thread._start_thread()
            set_event_loop.assert_called_once_with(thread.loop)
            thread._serve.assert_called_once_with()
            thread.loop.run_until_complete.assert_called_once_with(thread._serve())

    def test_start_thread__raises(self, *, thread):
        thread._serve = Mock(name="thread._serve")
        thread._serve.side_effect = KeyError("foo")
        assert not thread._shutdown.is_set()
        with patch("asyncio.set_event_loop") as set_event_loop:
            with pytest.raises(KeyError):
                thread._start_thread()
                set_event_loop.assert_called_once_with(thread.loop)
                thread._serve.assert_called_once_with()
                assert thread._shutdown.is_set()

    @pytest.mark.asyncio
    async def test_stop(self, *, thread):
        thread._started.clear()
        await thread.stop()
        thread._started.set()
        thread._shutdown.set()
        await thread.stop()

    @pytest.mark.asyncio
    async def test_stop_children(self, *, thread):
        await thread._stop_children()

    @pytest.mark.asyncio
    async def test_stop_futures(self, *, thread):
        await thread._stop_futures()

    @pytest.mark.asyncio
    async def test_shutdown_thread(self, *, thread):
        thread._default_stop_children = AsyncMock(name="stop_children")
        thread.on_thread_stop = AsyncMock(name="on_thread_stop")
        thread._default_stop_futures = AsyncMock(name="stop_futures")
        await thread._shutdown_thread()

        thread._default_stop_children.assert_awaited_once()
        thread.on_thread_stop.assert_awaited_once()
        thread._default_stop_futures.assert_awaited_once()
        thread._shutdown.is_set()

        thread._thread = Mock()
        await thread._shutdown_thread()
        thread._thread.stop.assert_not_called()

    @pytest.mark.asyncio
    async def test__thread_keepalive(self, *, thread):
        async def timer(interval, **kwargs):
            for _ in range(10):
                yield interval

        thread.itertimer = timer

        await thread._thread_keepalive(thread)

    @pytest.mark.asyncio
    async def test_serve(self, *, thread):
        self.mock_for_serve(thread)
        await thread._serve()

        thread._default_start.assert_awaited_once()
        thread.wait_until_stopped.assert_awaited_once()
        thread._shutdown_thread.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_serve__CancelledError(self, *, thread):
        self.mock_for_serve(thread)
        thread._default_start.side_effect = asyncio.CancelledError()

        with pytest.raises(asyncio.CancelledError):
            await thread._serve()

        thread.crash.assert_not_called()
        thread._shutdown_thread.assert_awaited_once_with()

    @pytest.mark.asyncio
    async def test_serve__Exception(self, *, thread):
        self.mock_for_serve(thread)
        exc = thread._default_start.side_effect = KeyError()

        with pytest.raises(KeyError):
            await thread._serve()

        thread.crash.assert_awaited_once_with(exc)
        thread._shutdown_thread.assert_awaited_once_with()

    @pytest.mark.asyncio
    async def test_serve__Exception_no_beacon(self, *, thread):
        self.mock_for_serve(thread)
        thread.beacon.root = None
        exc = thread._default_start.side_effect = KeyError()

        with pytest.raises(KeyError):
            await thread._serve()

        thread.crash.assert_awaited_once_with(exc)
        thread._shutdown_thread.assert_awaited_once_with()

    def mock_for_serve(self, thread):
        thread._default_start = AsyncMock(name="start")
        thread.wait_until_stopped = AsyncMock(name="wait_until_stopped")
        thread.crash = AsyncMock(name="crash")
        thread.on_crash = Mock(name="on_crash")
        thread.beacon = Mock(name="beacon")
        thread.beacon.root.data.crash = AsyncMock(name="root.crash")
        thread._shutdown_thread = AsyncMock(name="shutdown_thread")

    def test_on_crash(self, *, thread):
        with patch("traceback.print_exc") as print_exc:
            thread.on_crash("foo {0!r}", 10)
            print_exc.assert_called_once_with(None, ANY)

    @pytest.mark.asyncio
    async def test_crash(self, *, thread):
        exc = KeyError()
        thread._thread_running = None
        await thread.crash(exc)
        thread._thread_running = Mock()
        thread._thread_running.done.return_value = False
        await thread.crash(exc)
        await asyncio.sleep(0.1)  # wait for call_soon_threadsafe
        thread._thread_running.set_exception.assert_called_with(exc)


class test_MethodQueue:
    @pytest.mark.asyncio
    async def test_call(self):
        loop = asyncio.get_event_loop_policy().get_event_loop()
        queue = MethodQueue(num_workers=2)

        async with queue:

            async def myfun(x, y):
                return x * y

            futures = []
            for i in range(10):
                fut = loop.create_future()
                await queue.call(fut, myfun, i, i)
                futures.append(fut)
            assert await asyncio.gather(*futures) == [
                i * i for i, _ in enumerate(futures)
            ]

    @pytest.mark.asyncio
    async def test_call_raising(self):
        loop = asyncio.get_event_loop_policy().get_event_loop()
        queue = MethodQueue(num_workers=2)
        all_done = asyncio.Event()
        calls = 0

        async with queue:

            async def myfun(x, y):
                nonlocal calls
                calls += 1
                if calls >= 9:
                    all_done.set()
                raise KeyError(x)

            futures = []
            for i in range(10):
                fut = loop.create_future()
                if i == 3:
                    fut.cancel()
                await queue.call(fut, myfun, i, i)
                futures.append(fut)
            await all_done.wait()

            await asyncio.sleep(0)

            for future in futures:
                if not future.cancelled():
                    with pytest.raises(KeyError):
                        future.result()

    @pytest.mark.asyncio
    async def test_cast(self):
        queue = MethodQueue(num_workers=2)

        calls = 0
        all_done = asyncio.Event()

        async with queue:

            async def myfun(x, y):
                nonlocal calls
                calls += 1
                if calls >= 9:
                    all_done.set()

            for i in range(10):
                await queue.cast(myfun, i, i)
            await all_done.wait()

    @pytest.mark.asyncio
    async def test_flush(self):
        queue = MethodQueue(num_workers=2)

        calls = 0
        all_done = asyncio.Event()

        async def myfun(x, y):
            nonlocal calls
            calls += 1
            if calls >= 9:
                all_done.set()

        for i in range(10):
            await queue.cast(myfun, i, i)
        await queue.flush()
        await all_done.wait()


class test_QueueServiceThread:
    @pytest.fixture()
    def s(self):
        return QueueServiceThread()

    def test_method_queue(self, *, s):
        assert s.method_queue is s.method_queue

    @pytest.mark.asyncio
    async def test_on_thread_started(self, *, s):
        s._method_queue = Mock(start=AsyncMock())
        await s.on_thread_started()
        s._method_queue.start.assert_awaited_once_with()

    @pytest.mark.asyncio
    async def test_on_thread_stop(self, *, s):
        s._method_queue = None
        await s.on_thread_stop()
        s._method_queue = Mock(stop=AsyncMock())
        await s.on_thread_stop()
        s._method_queue.stop.assert_awaited_once_with()

    @pytest.mark.asyncio
    async def test_call_thread(self, *, s):
        s._method_queue = Mock(call=AsyncMock())

        async def on_call(*args, **kwargs):
            return done_future("value")

        s._method_queue.call.side_effect = on_call
        s.parent_loop = Mock()
        fun = Mock()
        ret = await s.call_thread(fun, "arg1", "arg2", kw1=1, kw2=2)
        assert ret == "value"
        s.parent_loop.create_future.assert_called_once_with()
        s._method_queue.call.assert_called_once_with(
            s.parent_loop.create_future(),
            fun,
            "arg1",
            "arg2",
            kw1=1,
            kw2=2,
        )

    @pytest.mark.asyncio
    async def test_cast_thread(self, *, s):
        fun = Mock()
        s._method_queue = Mock(cast=AsyncMock())
        await s.cast_thread(fun, "arg1", "arg2", kw1=1, kw2=2)
        s._method_queue.cast.assert_awaited_once_with(
            fun,
            "arg1",
            "arg2",
            kw1=1,
            kw2=2,
        )
