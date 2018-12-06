import asyncio
import logging as _logging
import reprlib
import signal
import sys
import typing
from contextlib import suppress
from logging import Logger, StreamHandler
from typing import Any, Dict, IO, Iterable, List, Optional, Tuple, Union, cast

from .services import Service
from .types import ServiceT
from .utils import logging
from .utils.imports import symbol_by_name
from .utils.times import Seconds

if typing.TYPE_CHECKING:
    from .debug import BlockingDetector
else:
    class BlockingDetector: ...  # noqa

__all__ = ['Worker']

logger = logging.get_logger(__name__)

BLOCK_DETECTOR = 'mode.debug:BlockingDetector'


class _TupleAsListRepr(reprlib.Repr):

    def repr_tuple(self, x: Tuple, level: int) -> str:
        return self.repr_list(cast(list, x), level)
# this repr formats tuples as if they are lists.
_repr = _TupleAsListRepr().repr  # noqa: E305


class Worker(Service):

    stdout: IO
    stderr: IO
    debug: bool
    quiet: bool
    blocking_timeout: Seconds
    logging_config: Optional[Dict]
    loglevel: Optional[Union[str, int]]
    logfile: Optional[Union[str, IO]]
    console_port: int
    loghandlers: List[StreamHandler]
    redirect_stdouts: bool
    redirect_stdouts_level: int

    services: Iterable[ServiceT]

    _blocking_detector: Optional[BlockingDetector] = None

    # signals can be called multiple times,
    # so when stopped by signal we record the time to make sure
    # we don't start the process multiple times.
    _signal_stop_time: Optional[float] = None
    _signal_stop_future: Optional[asyncio.Future] = None

    def __init__(
            self, *services: ServiceT,
            debug: bool = False,
            quiet: bool = False,
            logging_config: Dict = None,
            loglevel: Union[str, int] = None,
            logfile: Union[str, IO] = None,
            redirect_stdouts: bool = True,
            redirect_stdouts_level: logging.Severity = None,
            stdout: IO = sys.stdout,
            stderr: IO = sys.stderr,
            console_port: int = 50101,
            loghandlers: List[StreamHandler] = None,
            blocking_timeout: Seconds = 10.0,
            loop: asyncio.AbstractEventLoop = None,
            daemon: bool = True,
            **kwargs: Any) -> None:
        self.services = services
        self.debug = debug
        self.quiet = quiet
        self.logging_config = logging_config
        self.loglevel = loglevel
        self.logfile = logfile
        self.loghandlers = loghandlers or []
        self.redirect_stdouts = redirect_stdouts
        self.redirect_stdouts_level = logging.level_number(
            redirect_stdouts_level or 'WARN')
        if stdout is None:
            stdout = sys.stdout
        self.stdout = stdout
        if stderr is None:
            stderr = sys.stderr
        self.stderr = stderr
        self.console_port = console_port
        self.blocking_timeout = blocking_timeout
        self.daemon = daemon
        super().__init__(loop=loop, **kwargs)

        if self.services:
            for service in self.services:
                service.beacon.reattach(self.beacon)
                assert service.beacon.root is self.beacon

    def say(self, msg: str) -> None:
        """Write message to standard out."""
        self._say(msg)

    def carp(self, msg: str) -> None:
        """Write warning to standard err."""
        self._say(msg, file=self.stderr)

    def _say(self,
             msg: str,
             file: Optional[IO] = None,
             end: str = '\n',
             **kwargs: Any) -> None:
        if file is None:
            file = self.stdout
        if not self.quiet:
            print(msg, file=file, end=end, **kwargs)  # noqa: T003

    def on_init_dependencies(self) -> Iterable[ServiceT]:
        return self.services

    async def on_first_start(self) -> None:
        await self.default_on_first_start()

    async def default_on_first_start(self) -> None:
        self._setup_logging()
        await self.on_execute()
        if self.debug:
            await self._add_monitor()
        self.install_signal_handlers()

    async def on_execute(self) -> None:
        ...

    def _setup_logging(self) -> None:
        _loglevel: int = 0
        try:
            _loglevel = logging.setup_logging(
                loglevel=self.loglevel,
                logfile=self.logfile,
                logging_config=self.logging_config,
                loghandlers=self.loghandlers,
            )
        except Exception as exc:
            try:
                sys.stderr.write(f'CANNOT SETUP LOGGING: {exc!r} from ')
                import traceback
                traceback.print_stack(file=sys.stderr)
            except Exception:
                pass
            raise
        self.on_setup_root_logger(_logging.root, _loglevel)
        if self.redirect_stdouts:
            self._redirect_stdouts()

    def _redirect_stdouts(self) -> None:
        self.add_context(
            logging.redirect_stdouts(severity=self.redirect_stdouts_level))

    def on_setup_root_logger(self,
                             logger: Logger,
                             level: int) -> None:
        ...

    async def maybe_start_blockdetection(self) -> None:
        if self.debug:
            await self.blocking_detector.maybe_start()

    def install_signal_handlers(self) -> None:
        self.loop.add_signal_handler(signal.SIGINT, self._on_sigint)
        self.loop.add_signal_handler(signal.SIGTERM, self._on_sigterm)
        self.loop.add_signal_handler(signal.SIGUSR1, self._on_sigusr1)

    def _on_sigint(self) -> None:
        self.carp('-INT- -INT- -INT- -INT- -INT- -INT-')
        self._schedule_shutdown(signal.SIGINT)

    def _on_sigterm(self) -> None:
        self._schedule_shutdown(signal.SIGTERM)

    def _on_sigusr1(self) -> None:
        self.add_future(self._cry())

    async def _cry(self) -> None:
        logging.cry(file=self.stderr)

    def _schedule_shutdown(self, signal: signal.Signals) -> None:
        if not self._signal_stop_time:
            self._signal_stop_time = self.loop.time()
            self._signal_stop_future = asyncio.ensure_future(
                self._stop_on_signal(signal), loop=self.loop)

    async def _stop_on_signal(self, signal: signal.Signals) -> None:
        self.log.info('Signal received: %s (%s)', signal, signal.value)
        await self.stop()

    def execute_from_commandline(self) -> None:
        try:
            self.loop.run_until_complete(self.start())
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            self.log.exception('Error: %r', exc)
        finally:
            self.on_worker_shutdown()
            self.stop_and_shutdown()

    def on_worker_shutdown(self) -> None:
        ...

    def stop_and_shutdown(self) -> None:
        if self._signal_stop_future and not self._signal_stop_future.done():
            self.loop.run_until_complete(self._signal_stop_future)
        elif not self._stopped.is_set():
            self.loop.run_until_complete(self.stop())
        self._shutdown_loop()

    def _shutdown_loop(self) -> None:
        # Gather futures created by us.
        self.log.info('Gathering service tasks...')
        with suppress(asyncio.CancelledError):
            self.loop.run_until_complete(self._gather_futures())
        # Gather absolutely all asyncio futures.
        self.log.info('Gathering all futures...')
        self._gather_all()
        try:
            # Wait until loop is fully stopped.
            while self.loop.is_running():
                self.log.info('Waiting for event loop to shutdown...')
                self.loop.stop()
                self.loop.run_until_complete(asyncio.sleep(1.0))
        except BaseException as exc:
            self.log.exception('Got exception while waiting: %r', exc)
        finally:
            # Then close the loop.
            fut = asyncio.ensure_future(self._sentinel_task(), loop=self.loop)
            self.loop.run_until_complete(fut)
            self.loop.stop()
            self.log.info('Closing event loop')
            self.loop.close()
            if self._crash_reason:
                self.log.critical(
                    'We experienced a crash! Reraising original exception...')
                raise self._crash_reason from self._crash_reason

    async def _sentinel_task(self) -> None:
        await asyncio.sleep(1.0, loop=self.loop)

    def _gather_all(self) -> None:
        # sleeps for at most 40 * 0.1s
        for _ in range(1):
            if not len(asyncio.Task.all_tasks(loop=self.loop)):
                break
            self.loop.run_until_complete(asyncio.sleep(0.1))
        for task in asyncio.Task.all_tasks(loop=self.loop):
            task.cancel()

    async def start(self) -> None:
        await super().start()
        if self.daemon:
            await self.wait_until_stopped()

    async def _add_monitor(self) -> Any:
        try:
            import aiomonitor
        except ImportError:
            self.log.warn('Cannot start console: aiomonitor is not installed')
        else:
            monitor = aiomonitor.start_monitor(
                port=self.console_port,
                loop=self.loop,
            )
            self.add_context(monitor)

    def _repr_info(self) -> str:
        return _repr(self.services)

    @Service.task
    async def _keepalive(self) -> None:
        while not self.should_stop:
            # Keeps MainThread loop alive, by ensuring it wakes up
            # every second.
            await asyncio.sleep(1.0)

    @property
    def blocking_detector(self) -> BlockingDetector:
        if self._blocking_detector is None:
            self._blocking_detector = symbol_by_name(BLOCK_DETECTOR)(
                self.blocking_timeout,
                beacon=self.beacon,
                loop=self.loop,
            )
        return cast(BlockingDetector, self._blocking_detector)
