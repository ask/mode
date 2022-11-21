import asyncio
import signal
import sys
from contextlib import contextmanager
from signal import Signals
from unittest.mock import Mock, patch

if sys.version_info < (3, 8):
    from mock.mock import AsyncMock
else:
    from unittest.mock import AsyncMock

import pytest

from mode import Service
from mode.debug import BlockingDetector
from mode.utils.mocks import call, mask_module, patch_module
from mode.worker import Worker, exiting


def test_exiting():
    with patch("builtins.print") as print:
        with pytest.raises(SystemExit) as excinfo:
            with exiting(print_exception=True):
                raise KeyError()
        assert excinfo.value.code > 0
        print.assert_called()


class test_Worker:
    @pytest.fixture()
    def worker(self):
        return Worker(loglevel="INFO", logfile=None)

    def setup_method(self, method):
        self.setup_logging_patch = patch("mode.utils.logging.setup_logging")
        self.setup_logging = self.setup_logging_patch.start()

    def teardown_method(self):
        self.setup_logging_patch.stop()

    def test_constructor(self):
        stdout = Mock()
        stderr = Mock()
        assert Worker(stdout=stdout).stdout is stdout
        assert Worker(stderr=stderr).stderr is stderr
        assert Worker(stdout=None).stdout is not stdout
        assert Worker(stderr=None).stderr is not stderr

    def test_constructor_aligns_beacons(self):
        x = Service()
        y = Service()
        Worker(x, y)

    def test_say__quiet(self, worker):
        worker.quiet = True
        with patch("builtins.print") as print:
            worker.say("msg")
            print.assert_not_called()

    def test__say(self, worker):
        worker.quiet = False
        file = Mock()
        with patch("builtins.print") as print:
            worker._say("msg", file=file, foo=1)
            print.assert_called_once_with("msg", file=file, foo=1, end="\n")

    def test__say__default_file(self, worker):
        worker.quiet = False
        with patch("builtins.print") as print:
            worker._say("msg", file=None, end=".")
            print.assert_called_once_with("msg", file=worker.stdout, end=".")

    def test_on_init_dependencies(self, worker):
        workers = [Mock(), Mock(), Mock()]
        worker.services = workers
        assert worker.on_init_dependencies() == workers

    def _setup_for_on_first_start(self, worker):
        worker._setup_logging = Mock()
        worker.on_execute = AsyncMock()
        worker._add_monitor = AsyncMock()
        worker.install_signal_handlers = Mock()

    @pytest.mark.asyncio
    async def test_on_first_start(self, worker):
        self._setup_for_on_first_start(worker)
        worker.debug = False

        await worker.on_first_start()
        worker._setup_logging.assert_called_once_with()
        worker.on_execute.assert_awaited_once_with()
        worker._add_monitor.assert_not_called()
        worker.install_signal_handlers.assert_called_once_with()

        worker.debug = True
        await worker.on_first_start()
        worker._add_monitor.assert_awaited_once_with()

    @pytest.mark.asyncio
    async def test_on_first_start__override_logging(self):
        worker = Worker(override_logging=False)
        self._setup_for_on_first_start(worker)
        await worker.on_first_start()

        worker._setup_logging.assert_not_called()  # type: ignore[attr-defined]

    @pytest.mark.asyncio
    async def test_on_execute(self, worker):
        await worker.on_execute()

    @pytest.mark.parametrize(
        "loghandlers",
        [
            [],
            [Mock(), Mock()],
            [Mock()],
            None,
        ],
    )
    def test_setup_logging(self, loghandlers):
        worker_inst = Worker(
            loglevel=5,
            logfile="TEMP",
            loghandlers=loghandlers,
            logging_config=None,
        )
        worker_inst._setup_logging()
        self.setup_logging.assert_called_once_with(
            loglevel=5,
            logfile="TEMP",
            loghandlers=loghandlers or [],
            logging_config=None,
        )

    def test_setup_logging_raises_exception(self, worker):
        with patch("sys.stderr"):
            with patch("traceback.print_stack") as print_stack:
                with patch("mode.utils.logging.setup_logging") as sl:
                    sl.side_effect = KeyError("foo")
                    with pytest.raises(KeyError):
                        worker._setup_logging()

                    print_stack.side_effect = ValueError()
                    with pytest.raises(KeyError):
                        worker._setup_logging()

    def test_setup_logging__no_redirect(self, worker):
        worker.redirect_stdouts = False
        with patch("mode.utils.logging.setup_logging"):
            worker._setup_logging()

    @pytest.mark.asyncio
    async def test_maybe_start_blockdetection(self, worker):
        worker._blocking_detector = Mock(maybe_start=AsyncMock())
        worker.debug = False
        await worker.maybe_start_blockdetection()
        worker._blocking_detector.maybe_start.assert_not_awaited()

        worker.debug = True
        await worker.maybe_start_blockdetection()
        worker._blocking_detector.maybe_start.assert_awaited_once_with()

    def test_instal_signal_handlers(self, worker):
        worker._install_signal_handlers_windows = Mock()
        worker._install_signal_handlers_unix = Mock()

        worker.install_signal_handlers()
        if sys.platform == "win32":
            worker._install_signal_handlers_windows.assert_called_once_with()
        else:
            worker._install_signal_handlers_unix.assert_called_once_with()

    def test__install_signal_handlers_windows(self, worker):
        with patch("signal.signal") as sig:
            worker._install_signal_handlers_windows()
            sig.assert_called_once_with(signal.SIGTERM, worker._on_win_sigterm)

    @pytest.mark.skipif(sys.platform == "win32", reason="win32: no SIGUSR1")
    def test__install_signal_handlers_unix(self, worker):
        worker.loop = Mock()
        worker._install_signal_handlers_unix()
        worker.loop.add_signal_handler.assert_has_calls(
            [
                call(signal.SIGINT, worker._on_sigint),
                call(signal.SIGTERM, worker._on_sigterm),
                call(signal.SIGUSR1, worker._on_sigusr1),
            ]
        )

    def test__on_sigint(self, worker):
        worker._schedule_shutdown = Mock()
        worker._on_sigint()
        worker._schedule_shutdown.assert_called_once_with(signal.SIGINT)

    def test__on_sigterm(self, worker):
        worker._schedule_shutdown = Mock()
        worker._on_sigterm()
        worker._schedule_shutdown.assert_called_once_with(signal.SIGTERM)

    def test__on_win_sigterm(self, worker):
        worker._schedule_shutdown = Mock()
        worker._on_win_sigterm(1, Mock())
        worker._schedule_shutdown.assert_called_once_with(signal.SIGTERM)

    def test__on_sigusr1(self, worker):
        worker._cry = Mock()
        worker.add_future = Mock()
        worker._on_sigusr1()
        worker.add_future.assert_called_once_with(worker._cry.return_value)

    @pytest.mark.asyncio
    async def test__cry(self, worker):
        with patch("mode.utils.logging.cry") as cry:
            await worker._cry()
            cry.assert_called_once_with(file=worker.stderr)

    def test__schedule_shutdown(self, worker):
        with patch("asyncio.ensure_future") as ensure_future:
            worker._stop_on_signal = Mock()
            worker._schedule_shutdown(Signals.SIGTERM)
            assert worker._signal_stop_time
            ensure_future.assert_called_once_with(
                worker._stop_on_signal.return_value,
                loop=worker.loop,
            )
            worker._stop_on_signal.assert_called_once_with(Signals.SIGTERM)

            worker._schedule_shutdown(Signals.SIGTERM)

    @pytest.mark.asyncio
    async def test__stop_on_signal(self, worker):
        worker.stop = AsyncMock()
        await worker._stop_on_signal(Signals.SIGTERM)
        worker.stop.assert_awaited_once()

    def test_execute_from_commandline(self, worker):
        with self.patch_execute(worker) as ensure_future:
            with pytest.raises(SystemExit) as excinfo:
                worker.execute_from_commandline()
            assert excinfo.value.code == 0
            assert worker._starting_fut is ensure_future.return_value
            ensure_future.assert_called_once_with(
                worker.start.return_value, loop=worker.loop
            )
            worker.stop_and_shutdown.assert_called_once_with()

    def test_execute_from_commandline__MemoryError(self, worker):
        with self.patch_execute(worker):
            worker.start.side_effect = MemoryError()
            with pytest.raises(SystemExit) as excinfo:
                worker.execute_from_commandline()
            assert excinfo.value.code > 0

    def test_execute_from_commandline__CancelledError(self, worker):
        with self.patch_execute(worker):
            worker.start.side_effect = asyncio.CancelledError()
            with pytest.raises(SystemExit) as excinfo:
                worker.execute_from_commandline()
            assert excinfo.value.code == 0

    def test_execute_from_commandline__Exception(self, worker):
        with self.patch_execute(worker):
            worker.start.side_effect = KeyError("foo")
            with pytest.raises(SystemExit) as excinfo:
                worker.execute_from_commandline()
            assert excinfo.value.code > 0

    @contextmanager
    def patch_execute(self, worker):
        worker.loop = Mock()
        worker.start = Mock()
        worker.stop_and_shutdown = Mock()
        with patch("asyncio.ensure_future") as ensure_future:
            yield ensure_future

    def test_on_worker_shutdown(self, worker):
        worker.on_worker_shutdown()

    def test_stop_and_shutdown__stopping_worker(self, worker):
        worker.loop = Mock()
        worker.stop = Mock()
        worker._shutdown_loop = Mock()
        worker._signal_stop_future = None
        worker._stopped.clear()
        worker.loop = Mock()
        worker.stop_and_shutdown()

        worker.loop.run_until_complete.assert_called_with(worker.stop.return_value)

    def test__shutdown_loop(self, worker):
        with self.patch_shutdown_loop(worker, is_running=False):
            worker._shutdown_loop()

    def test__shutdown_loop__wait(self, worker):
        with self.patch_shutdown_loop(worker, is_running=True):

            def on_loop_stop():
                if worker.loop.stop.call_count >= 3:
                    worker.loop.is_running.return_value = False
                return worker.loop.stop.return_value

            worker.loop.stop.side_effect = on_loop_stop

            worker._shutdown_loop()

            assert worker.loop.stop.call_count == 4

    def test__shutdown_loop__wait_raises(self, worker):
        with self.patch_shutdown_loop(worker, is_running=True):
            worker.log.exception = Mock()

            def on_loop_stop():
                if worker.loop.stop.call_count >= 3:
                    print("MOO")
                    worker.loop.stop.side_effect = None
                    raise ValueError("moo")
                return worker.loop.stop.return_value

            worker.loop.stop.side_effect = on_loop_stop

            worker._shutdown_loop()

            assert worker.loop.stop.call_count == 4
            worker.log.exception.assert_called_once()

    def test__shutdown_loop__service_crashed(self, worker):
        worker.crash_reason = KeyError("foo")
        with self.patch_shutdown_loop(worker, is_running=False):
            with pytest.raises(KeyError):
                worker._shutdown_loop()

    @contextmanager
    def patch_shutdown_loop(self, worker, is_running=False):
        worker.loop = Mock()
        worker._gather_futures = Mock()
        worker._gather_all = Mock()
        worker.loop.is_running.return_value = is_running
        worker._sentinel_task = AsyncMock()
        with patch("asyncio.ensure_future") as ensure_future:
            with patch("asyncio.sleep", AsyncMock()):
                yield ensure_future

    @pytest.mark.asyncio
    async def test__sentinel_task(self, worker):
        with patch("asyncio.sleep", AsyncMock()) as sleep:
            await worker._sentinel_task()
            sleep.assert_called_once_with(1.0)

    def test__gather_all(self, worker):
        with patch("mode.worker.all_tasks") as all_tasks:
            with patch("asyncio.sleep", AsyncMock()):
                all_tasks.return_value = [Mock(), Mock(), Mock()]
                worker.loop = Mock()

                worker._gather_all()

                for task in all_tasks.return_value:
                    task.cancel.assert_called_once_with()

    def test__gather_all_early(self, worker):
        with patch("mode.worker.all_tasks") as all_tasks:
            with patch("asyncio.sleep"):
                worker.loop = Mock()

                def on_all_tasks(loop):
                    if all_tasks.call_count >= 5:
                        return []
                    return [Mock(), Mock(), Mock()]

                all_tasks.side_effect = on_all_tasks

                worker._gather_all()

                for task in all_tasks.return_value:
                    task.cancel.assert_called_once_with()

    @pytest.mark.asyncio
    async def test_on_started(self, worker):
        worker.daemon = False
        worker.wait_until_stopped = AsyncMock()
        await worker.on_started()
        worker.wait_until_stopped.assert_not_awaited()
        worker.daemon = True
        await worker.on_started()
        worker.wait_until_stopped.assert_awaited_once()

    @pytest.mark.asyncio
    async def test__add_monitor(self, worker):
        worker.add_context = Mock()
        with patch_module("aiomonitor"):
            import aiomonitor

            await worker._add_monitor()

            worker.add_context.assert_called_once_with(
                aiomonitor.start_monitor.return_value
            )

            aiomonitor.start_monitor.assert_called_once_with(
                port=worker.console_port,
                loop=worker.loop,
            )

    @pytest.mark.asyncio
    async def test__add_monitor__no_aiomonitor(self, worker):
        worker.log.warning = Mock()
        with mask_module("aiomonitor"):
            await worker._add_monitor()
            worker.log.warning.assert_called_once()

    def test_repr_info(self, worker):
        assert repr(worker)

    def test_blocking_detector(self, worker):
        b = worker.blocking_detector
        assert isinstance(b, BlockingDetector)
        assert b.timeout == worker.blocking_timeout
        assert b.beacon.parent is worker.beacon
        assert b.loop is worker.loop
