"""Logging utilities."""
import asyncio
import logging
import os
import sys
import threading
import traceback
from functools import singledispatch
from itertools import count
from pprint import pformat, pprint
from time import asctime
from types import TracebackType
from typing import (
    Any,
    Callable,
    ClassVar,
    ContextManager,
    Dict,
    IO,
    Iterable,
    List,
    Mapping,
    NamedTuple,
    Optional,
    Set,
    Tuple,
    Type,
    Union,
)
from .text import abbr, title
from .times import Seconds, want_seconds

import colorlog

__all__ = [
    'ExtensionFormatter',
    'CompositeLogger',
    'formatter',
    'cry',
    'get_logger',
    'level_name',
    'level_number',
    'setup_logging',
    'flight_recorder',
]

DEVLOG: bool = bool(os.environ.get('DEVLOG', ''))
DEFAULT_FORMAT: str = """\
[%(asctime)s: %(levelname)s]: %(log_color)s%(message)s\
"""

DEFAULT_COLORS = {
    **colorlog.default_log_colors,
    'INFO': 'white',
    'DEBUG': 'blue',
}

#: Set by ``setup_logging`` if logging target file is a TTY.
LOG_ISATTY: bool = False

FormatterHandler = Callable[[Any], Any]


_formatter_registry: Set[FormatterHandler]
_formatter_registry = set()


def formatter(fun: FormatterHandler) -> FormatterHandler:
    """Register formatter for logging positional args."""
    _formatter_registry.add(fun)
    return fun


class ExtensionFormatter(colorlog.TTYColoredFormatter):
    """Formatter that can register callbacks to format args.

    Extends :pypi:`colorlog`.
    """

    def format(self, record: logging.LogRecord) -> str:
        self._format_args(record)
        return super().format(record)

    def _format_args(self, record: logging.LogRecord) -> None:
        if isinstance(record.args, Mapping):
            # logger.log(severity, "msg %(foo)s", foo=303)
            record.args = {
                k: self._format_arg(v) for k, v in record.args.items()
            }
        else:
            if not isinstance(record.args, tuple):
                # logger.log(severity, "msg %s", foo)
                record.args = (record.args,)
            # logger.log(severity, "msg %s", ('foo',))
            record.args = tuple(
                self._format_arg(arg) for arg in record.args
            )

    def _format_arg(self, arg: Any) -> Any:
        # Reduce value by calling all registered formatters.
        for fun in _formatter_registry:
            res = fun(arg)
            if res is not None:
                arg = res
        return arg


def get_logger(name: str) -> logging.Logger:
    """Get logger by name."""
    logger = logging.getLogger(name)
    if not logger.handlers:
        logger.addHandler(logging.NullHandler())
    return logger


@singledispatch
def level_name(loglevel: int) -> str:
    """Convert log level to number."""
    return logging.getLevelName(loglevel)


@level_name.register(str)
def _when_str(loglevel: str) -> str:
    return loglevel.upper()


@singledispatch
def level_number(loglevel: int) -> int:
    """Convert log level number to name."""
    return loglevel


@level_number.register(str)
def _(loglevel: str) -> int:
    return logging.getLevelName(loglevel.upper())  # type: ignore


def setup_logging(
        *,
        loglevel: Union[str, int] = None,
        logfile: Union[str, IO] = None,
        logformat: str = None,
        loghandlers: List[logging.StreamHandler] = None,
        log_colors: Mapping[str, str] = DEFAULT_COLORS) -> int:
    """Setup logging to file/stream."""
    stream: IO = None
    _loglevel: int = level_number(loglevel)
    if not isinstance(logfile, str):
        stream, logfile = logfile, None
        if stream is None:
            stream = sys.stdout
        global LOG_ISATTY
        try:
            LOG_ISATTY = stream.isatty()
        except AttributeError:
            pass

    logging.root.handlers.clear()

    _setup_logging(
        level=_loglevel,
        filename=logfile,
        stream=stream,
        format=logformat or DEFAULT_FORMAT,
        log_colors=log_colors,
        handlers=loghandlers,
    )
    return _loglevel


def _setup_logging(*,
                   filename: str = None,
                   stream: IO = None,
                   format: str = DEFAULT_FORMAT,
                   log_colors: Mapping[str, str] = DEFAULT_COLORS,
                   handlers: List[logging.StreamHandler] = None,
                   **kwargs: Any) -> None:
    if filename:
        assert stream is None
        logging.basicConfig(filename=filename, **kwargs)
    if stream:
        assert filename is None
        handlers = handlers or []
        handlers.append(_setup_console_handler(
            stream=stream,
            format=format,
            log_colors=log_colors,
        ))
        logging.basicConfig(handlers=handlers, **kwargs)


def _setup_console_handler(*,
                           stream: IO = None,
                           format: str = DEFAULT_FORMAT,
                           log_colors: Mapping[str, str] = DEFAULT_COLORS):
    console_handler = colorlog.StreamHandler(stream)
    formatter = ExtensionFormatter(format, log_colors=log_colors)
    console_handler.setFormatter(formatter)
    return console_handler


class LogSeverityMixin:

    def dev(self, msg: str, *args: Any, **kwargs: Any) -> None:
        if DEVLOG:
            self.info(msg, *args, **kwargs)

    def debug(self, msg: str, *args: Any, **kwargs: Any) -> None:
        self.log(logging.DEBUG, msg, *args, **kwargs)

    def info(self, msg: str, *args: Any, **kwargs: Any) -> None:
        self.log(logging.INFO, msg, *args, **kwargs)

    def warn(self, msg: str, *args: Any, **kwargs: Any) -> None:
        self.log(logging.WARN, msg, *args, **kwargs)

    def error(self, msg: str, *args: Any, **kwargs: Any) -> None:
        self.log(logging.ERROR, msg, *args, **kwargs)

    def crit(self, msg: str, *args: Any, **kwargs: Any) -> None:
        self.log(logging.CRITICAL, msg, *args, **kwargs)

    def critical(self, msg: str, *args: Any, **kwargs: Any) -> None:
        self.log(logging.CRITICAL, msg, *args, **kwargs)

    def exception(self, msg: str, *args: Any, **kwargs: Any) -> None:
        self.log(logging.ERROR, msg, *args, exc_info=1, **kwargs)


class CompositeLogger(LogSeverityMixin):
    logger: logging.Logger

    def __init__(self, logger: logging.Logger,
                 formatter: Callable[..., str] = None) -> None:
        self.logger = logger
        self.formatter: Callable[..., str] = formatter

    def log(self, severity: int, msg: str,
            *args: Any, **kwargs: Any) -> None:
        self.logger.log(severity,
                        self.format(severity, msg, *args, **kwargs),
                        *args, **kwargs)

    def format(self, severity: int, msg: str,
               *args: Any, **kwargs: Any) -> str:
        if self.formatter:
            return self.formatter(severity, msg, *args, **kwargs)
        return msg


def cry(file: IO,
        *,
        sep1: str = '=',
        sep2: str = '-',
        sep3: str = '~',
        seplen: int = 49) -> None:
    """Return stack-trace of all active threads.

    See Also:
        Taken from https://gist.github.com/737056.
    """
    # get a map of threads by their ID so we can print their names
    # during the traceback dump
    tmap = {t.ident: t for t in threading.enumerate()}

    current_thread = threading.current_thread()
    sep1 = sep1 * seplen
    sep2 = sep2 * seplen
    sep3 = sep3 * seplen

    for tid, frame in sys._current_frames().items():
        thread = tmap.get(tid)
        if thread:
            if thread.ident == current_thread.ident:
                loop = asyncio.get_event_loop()
            else:
                loop = getattr(thread, 'loop', None)
            print(f'THREAD {thread.name}', file=file)            # noqa: T003
            print(sep1, file=file)                               # noqa: T003
            traceback.print_stack(frame, file=file)
            print(sep2, file=file)                               # noqa: T003
            print('LOCAL VARIABLES', file=file)                  # noqa: T003
            print(sep2, file=file)                               # noqa: T003
            pprint(frame.f_locals, stream=file)
            if loop is not None:
                print('TASKS', file=file)
                print(sep2, file=file)
                for task in asyncio.Task.all_tasks(loop=loop):
                    coro = task._coro  # type: ignore
                    wrapped = getattr(task, '__wrapped__', None)
                    print(f'  TASK {coro.__name__}', file=file)  # noqa: T003
                    if wrapped:
                        print(f'  -> {wrapped}', file=file)      # noqa: T003
                    print(f'  {task!r}', file=file)              # noqa: T003
                    print(f'  {sep3}', file=file)                # noqa: T003
                    frames = task.get_stack()
                    if frames:
                        frame = frames[0]
                        traceback.print_stack(frame, file=file)
                        print(sep3, file=file)                   # noqa: T003
                        print('  LOCAL VARIABLES', file=file)    # noqa: T003
                        print(f'  {sep3}', file=file)            # noqa: T003
                        for k, val in frame.f_locals.items():
                            vals = abbr(pformat(val), 2000, suffix='[...]')
                            print(f'  {k!r} = {vals}', file=file)  # noqa: T003
                    print('\n', file=file)
            print('\n', file=file)                               # noqa: T003


class flight_recorder(ContextManager, LogSeverityMixin):
    _id_source: ClassVar[Iterable[int]] = count(1)

    logger: logging.Logger
    timeout: float
    loop: asyncio.AbstractEventLoop
    started_at_date: str

    _fut: asyncio.Future
    _logs: List[Tuple[int, str, Tuple[Any], Dict[str, Any]]]

    class LogMessage(NamedTuple):
        severity: int
        message: str
        asctime: str
        args: Tuple[Any, ...]
        kwargs: Dict[str, Any]

    def __init__(self, logger: logging.Logger, *, timeout: Seconds,
                 loop: asyncio.AbstractEventLoop = None) -> None:
        self.id = next(self._id_source)
        self.logger = logger
        self.timeout = want_seconds(timeout)
        self.loop = loop or asyncio.get_event_loop()
        self.started_at_date = None
        self._fut = None
        self._logs = []

    def activate(self) -> None:
        if self._fut:
            raise RuntimeError('{type(self).__name__} already activated')
        self.started_at_date = asctime()
        self._fut = asyncio.ensure_future(self._waiting(), loop=self.loop)

    def cancel(self) -> None:
        fut, self._fut = self._fut, None
        self._logs.clear()
        if fut is not None:
            fut.cancel()

    def log(self, severity: int, message: str,
            *args: Any, **kwargs: Any) -> None:
        if self._fut:
            self._logs.append(
                self.LogMessage(severity, message, asctime(), args, kwargs))
        else:
            self.logger.log(severity, message, *args, **kwargs)

    async def _waiting(self) -> None:
        try:
            await asyncio.sleep(self.timeout)
        except asyncio.CancelledError:
            pass
        else:
            logger = self.logger
            ident = self._ident()
            logger.warn('Warning: Task timed out!')
            logger.warn('Please make sure it is hanging before restarting.')
            if self._logs:
                logger.info('[%s] (started at %s) Replaying logs...',
                            ident, self.started_at_date)
                for severity, message, datestr, args, kwargs in self._logs:
                    msg = f'[%s] (%s) {message}'
                    logger.log(severity, msg, ident, datestr, *args, **kwargs)
                logger.info('[%s] -End of log-', ident)

    def _ident(self) -> str:
        return f'{title(type(self).__name__)}-{self.id}'

    def __repr__(self) -> str:
        return f'<{self._ident()} @{id(self):#x}>'

    def __enter__(self) -> 'flight_recorder':
        self.activate()
        return self

    def __exit__(self,
                 exc_type: Type[BaseException] = None,
                 exc_val: BaseException = None,
                 exc_tb: TracebackType = None) -> Optional[bool]:
        self.cancel()
