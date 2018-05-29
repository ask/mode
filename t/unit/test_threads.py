import asyncio
import sys
import pytest
from mode.threads import ServiceThread
from mode.utils.mocks import AsyncMock, Mock, patch


class test_ServiceThread:

    @pytest.fixture
    def executor(self):
        return Mock(name='executor')

    @pytest.fixture
    def loop(self):
        return Mock(name='loop')

    @pytest.fixture
    def thread_loop(self):
        return Mock(name='thread_loop')

    @pytest.fixture
    def thread(self, *, executor, loop, thread_loop):
        return ServiceThread(
            executor=executor,
            loop=loop,
            thread_loop=thread_loop)

    @pytest.mark.asyncio
    async def test_on_thread_stop(self, *, thread):
        await thread.on_thread_stop()

    def test_new_shutdown_event(self, *, thread):
        event = thread._new_shutdown_event()
        assert isinstance(event, asyncio.Event)
        assert not event.is_set()

    @pytest.mark.asyncio
    async def test_maybe_start(self, *, thread):
        thread.start = AsyncMock(name='start')
        thread._thread_started.set()
        await thread.maybe_start()
        thread.start.assert_not_called()

        thread._thread_started.clear()
        await thread.maybe_start()
        thread.start.assert_called_once_with()

    @pytest.mark.asyncio
    async def test_start(self, *, thread):
        thread.add_future = AsyncMock(name='thread.add_future')
        await thread.start()

        thread.loop.run_in_executor.assert_called_once_with(
            thread.executor, thread._start_thread,
        )

        thread.add_future.assert_called_once_with(
            thread.loop.run_in_executor())

        assert thread._thread_started.is_set()

    @pytest.mark.asyncio
    async def test_start__already_started_raises(self, *, thread):
        thread._thread_started.set()
        with pytest.raises(AssertionError):
            await thread.start()

    def test_start_thread(self, *, thread):
        thread._serve = Mock(name='thread._serve')
        with patch('asyncio.set_event_loop') as set_event_loop:
            thread._start_thread()
            set_event_loop.assert_called_once_with(thread.loop)
            thread._serve.assert_called_once_with()
            thread.loop.run_until_complete.assert_called_once_with(
                thread._serve())

    @pytest.mark.asyncio
    async def test_stop_children(self, *, thread):
        await thread._stop_children()

    @pytest.mark.asyncio
    async def test_stop_futures(self, *, thread):
        await thread._stop_futures()

    @pytest.mark.asyncio
    async def test_shutdown_thread(self, *, thread):
        thread._default_stop_children = AsyncMock(name='stop_children')
        thread.on_thread_stop = AsyncMock(name='on_thread_stop')
        thread._default_stop_futures = AsyncMock(name='stop_futures')
        await thread._shutdown_thread()

        thread._default_stop_children.assert_called_once_with()
        thread.on_thread_stop.assert_called_once_with()
        thread._default_stop_futures.assert_called_once_with()
        thread._shutdown.is_set()

    @pytest.mark.asyncio
    async def test_serve(self, *, thread):
        self.mock_for_serve(thread)
        await thread._serve()

        thread._default_start.assert_called_once_with()
        thread.wait_until_stopped.assert_called_once_with()
        thread._shutdown_thread.assert_called_once_with()

    @pytest.mark.asyncio
    async def test_serve__CancelledError(self, *, thread):
        self.mock_for_serve(thread)
        thread._default_start.side_effect = asyncio.CancelledError()

        with pytest.raises(asyncio.CancelledError):
            await thread._serve()
        thread.crash.assert_not_called()
        thread._shutdown_thread.assert_called_once_with()

    @pytest.mark.asyncio
    async def test_serve__Exception(self, *, thread):
        self.mock_for_serve(thread)
        exc = thread._default_start.side_effect = KeyError()

        with pytest.raises(KeyError):
            await thread._serve()

        thread.crash.assert_called_once_with(exc)
        thread._shutdown_thread.assert_called_once_with()

    @pytest.mark.asyncio
    async def test_serve__Exception_no_beacon(self, *, thread):
        self.mock_for_serve(thread)
        thread.beacon.root = None
        exc = thread._default_start.side_effect = KeyError()

        with pytest.raises(KeyError):
            await thread._serve()

        thread.crash.assert_called_once_with(exc)
        thread._shutdown_thread.assert_called_once_with()

    def mock_for_serve(self, thread):
        thread._default_start = AsyncMock(name='start')
        thread.wait_until_stopped = AsyncMock(name='wait_until_stopped')
        thread.crash = AsyncMock(name='crash')
        thread.on_crash = Mock(name='on_crash')
        thread.beacon = Mock(name='beacon')
        thread.beacon.root.data.crash = AsyncMock(name='root.crash')
        thread._shutdown_thread = AsyncMock(name='shutdown_thread')

    def test_on_crash(self, *, thread):
        with patch('traceback.print_exc') as print_exc:
            thread.on_crash('foo {0!r}', 10)
            print_exc.assert_called_once_with(None, sys.stderr)
