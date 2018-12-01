"""Logging utilities."""
import asyncio
import logging
import logging.config
import os
import sys
import threading
import traceback
from contextlib import contextmanager
from functools import singledispatch, wraps
from itertools import count
from logging import Logger
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
    Sequence,
    Set,
    Tuple,
    Type,
    Union,
)
from .text import abbr, title
from .times import Seconds, want_seconds

import colorlog

__all__ = [
    'CompositeLogger',
    'ExtensionFormatter',
    'FileLogProxy',
    'FormatterHandler',
    'LogSeverityMixin',
    'Logwrapped',
    'Severity',
    'cry',
    'flight_recorder',
    'formatter',
    'get_logger',
    'level_name',
    'level_number',
    'redirect_logger',
    'redirect_stdouts',
    'setup_logging',
]

DEVLOG: bool = bool(os.environ.get('DEVLOG', ''))
DEFAULT_FORMAT: str = '[%(asctime)s: %(levelname)s]: %(message)s'
DEFAULT_COLOR_FORMAT = '[%(asctime)s: %(levelname)s]: %(log_color)s%(message)s'

DEFAULT_COLORS = {
    **colorlog.default_log_colors,
    'INFO': 'white',
    'DEBUG': 'blue',
}


DEFAULT_FORMATTERS = {
    'default': {
        'format': '[%(asctime)s: %(levelname)s]: %(message)s',
    },
    'colored': {
        '()': 'mode.utils.logging.ExtensionFormatter',
        'format': DEFAULT_COLOR_FORMAT,
        'log_colors': DEFAULT_COLORS,
    },
}


def _logger_config(handlers: List[str],
                   level: Union[str, int] = 'INFO') -> Dict:
    return {
        'handlers': handlers,
        'level': level,
    }


def create_logconfig(version: int = 1,
                     disable_existing_loggers: bool = False,
                     formatters: Dict = DEFAULT_FORMATTERS,
                     handlers: Dict = None,
                     root: Dict = None) -> Dict:
    return {
        'version': version,
        # do not disable existing loggers from other modules.
        # see https://www.caktusgroup.com/blog/2015/01/27/
        #    Django-Logging-Configuration-logging_config-default-settings-logger/
        'disable_existing_loggers': disable_existing_loggers,
        'formatters': formatters,
        'handlers': handlers,
        'root': root,
    }


#: Set by ``setup_logging`` if logging target file is a TTY.
LOG_ISATTY: bool = False

FormatterHandler = Callable[[Any], Any]
Severity = Union[int, str]

_formatter_registry: Set[FormatterHandler] = set()


def get_logger(name: str) -> Logger:
    """Get logger by name."""
    logger = logging.getLogger(name)
    if not logger.handlers:
        logger.addHandler(logging.NullHandler())
    return logger


redirect_logger = get_logger('mode.redirect')


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
    logger: Logger

    def __init__(self,
                 logger: Logger,
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
        loghandlers: List[logging.StreamHandler] = None,
        logging_config: Dict = None) -> int:
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
        logging_config=logging_config,
        loghandlers=loghandlers,
    )
    return _loglevel


def _setup_logging(*,
                   level: Union[int, str] = None,
                   filename: str = None,
                   stream: IO = None,
                   loghandlers: List[logging.StreamHandler] = None,
                   logging_config: Dict = None) -> None:
    if filename:
        assert stream is None
        handlers = {
            'default': {
                'level': level,
                'class': 'logging.FileHandler',
                'formatter': 'default',
                'filename': filename,
            },
        }
    elif stream:
        handlers = {
            'default': {
                'level': level,
                'class': 'colorlog.StreamHandler',
                'formatter': 'colored',
            },
        }
    config = create_logconfig(handlers=handlers, root={
        'level': level,
        'handlers': ['default'],
    })
    if logging_config is None:
        logging_config = config
    elif logging_config.pop('merge', False):
        logging_config = {**config, **logging_config}
        for k in ('formatters', 'filters', 'handlers', 'loggers', 'root'):
            logging_config[k] = {**config.get(k, {}),
                                 **logging_config.get(k, {})}
    logging.config.dictConfig(logging_config)
    if loghandlers is not None:
        logging.root.handlers.extend(loghandlers)


class Logwrapped(object):
    """Wrap all object methods, to log on call."""
    obj: Any
    logger: Any
    severity: int
    ident: str

    _ignore: ClassVar[Set[str]] = {'__enter__', '__exit__'}

    def __init__(self,
                 obj: Any,
                 logger: Any = None,
                 severity: Severity = None,
                 ident: str = '') -> None:
        self.obj = obj
        self.logger = logger
        self.severity = level_number(severity) if severity else severity
        self.ident = ident

    def __getattr__(self, key: str) -> Any:
        meth = getattr(self.obj, key)

        if not callable(meth) or key in self.__ignore:
            return meth

        @wraps(meth)
        def __wrapped(*args: Any, **kwargs: Any) -> Any:
            info = ''
            if self.ident:
                info += self.ident.format(self.obj)
            info += f'{meth.__name__}('
            if args:
                info += ', '.join(map(repr, args))
            if kwargs:
                if args:
                    info += ', '
                info += ', '.join(f'{key}={value!r}'
                                  for key, value in kwargs.items())
            info += ')'
            self.logger.log(self.severity, info)
            return meth(*args, **kwargs)

        return __wrapped

    def __repr__(self):
        return repr(self.obj)

    def __dir__(self):
        return dir(self.obj)


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
                    coro_name = getattr(coro, '__name__', None)
                    if coro_name is None:
                        # some coroutines does not have a __name__ attribute
                        # e.g. async_generator_asend
                        coro_name = repr(coro)
                    print(f'  TASK {coro_name}', file=file)      # noqa: T003
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


class LogMessage(NamedTuple):
    severity: int
    message: str
    asctime: str
    args: Tuple[Any, ...]
    kwargs: Dict[str, Any]


class flight_recorder(ContextManager, LogSeverityMixin):
    """Flight Recorder context for use with :keyword:`with` statement.

    This is a logging utility to log stuff only when something
    times out.

    For example if you have a background thread that is sometimes
    hanging::

        class RedisCache(mode.Service):

            @mode.timer(1.0)
            def _background_refresh(self) -> None:
                self._users = await self.redis_client.get(USER_KEY)
                self._posts = await self.redis_client.get(POSTS_KEY)

    You want to figure out on what line this is hanging, but logging
    all the time will provide way too much output, and will even change
    how fast the program runs and that can mask race conditions, so that
    they never happen.

    Use the flight recorder to save the logs and only log when it times out:

    .. sourcecode:: python

        logger = mode.get_logger(__name__)

        class RedisCache(mode.Service):

            @mode.timer(1.0)
            def _background_refresh(self) -> None:
                with mode.flight_recorder(logger, timeout=10.0) as on_timeout:
                    on_timeout.info(f'+redis_client.get({USER_KEY!r})')
                    await self.redis_client.get(USER_KEY)
                    on_timeout.info(f'-redis_client.get({USER_KEY!r})')

                    on_timeout.info(f'+redis_client.get({POSTS_KEY!r})')
                    await self.redis_client.get(POSTS_KEY)
                    on_timeout.info(f'-redis_client.get({POSTS_KEY!r})')

    If the body of this :keyword:`with` statement completes before the
    timeout, the logs are forgotten about and never emitted -- if it
    takes more than ten seconds to complete, we will see these messages
    in the log:

    .. sourcecode:: text

        [2018-04-19 09:43:55,877: WARNING]: Warning: Task timed out!
        [2018-04-19 09:43:55,878: WARNING]:
            Please make sure it is hanging before restarting.
        [2018-04-19 09:43:55,878: INFO]: [Flight Recorder-1]
            (started at Thu Apr 19 09:43:45 2018) Replaying logs...
        [2018-04-19 09:43:55,878: INFO]: [Flight Recorder-1]
            (Thu Apr 19 09:43:45 2018) +redis_client.get('user')
        [2018-04-19 09:43:55,878: INFO]: [Flight Recorder-1]
            (Thu Apr 19 09:43:49 2018) -redis_client.get('user')
        [2018-04-19 09:43:55,878: INFO]: [Flight Recorder-1]
            (Thu Apr 19 09:43:46 2018) +redis_client.get('posts')
        [2018-04-19 09:43:55,878: INFO]: [Flight Recorder-1] -End of log-

    Now we know this ``redis_client.get`` call can take too long to complete,
    and should consider adding a timeout to it.
    """

    _id_source: ClassVar[Iterable[int]] = count(1)

    logger: Any
    timeout: float
    loop: asyncio.AbstractEventLoop
    started_at_date: str

    _fut: asyncio.Future
    _logs: List[Tuple[int, str, Tuple[Any], Dict[str, Any]]]

    def __init__(self, logger: Any, *,
                 timeout: Seconds,
                 loop: asyncio.AbstractEventLoop = None) -> None:
        self.id = next(self._id_source)
        self.logger = logger
        self.timeout = want_seconds(timeout)
        self.loop = loop or asyncio.get_event_loop()
        self.started_at_date = None
        self._fut = None
        self._logs = []

    def wrap_debug(self, obj: Any) -> Logwrapped:
        return self.wrap(logging.DEBUG, obj)

    def wrap_info(self, obj: Any) -> Logwrapped:
        return self.wrap(logging.INFO, obj)

    def wrap_warn(self, obj: Any) -> Logwrapped:
        return self.wrap(logging.WARN, obj)

    def wrap_error(self, obj: Any) -> Logwrapped:
        return self.wrap(logging.ERROR, obj)

    def wrap(self, severity: int, obj: Any) -> Logwrapped:
        return Logwrapped(logger=self, severity=severity, obj=obj)

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
            self._buffer_log(severity, message, args, kwargs)
        else:
            self.logger.log(severity, message, *args, **kwargs)

    def _buffer_log(self, severity: int, message: str,
                    args: Any, kwargs: Any) -> None:
        log = LogMessage(severity, message, asctime(), args, kwargs)
        self._logs.append(log)

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


class FileLogProxy:

    mode: str = 'w'
    name: str = None
    closed: bool = False
    severity: int = logging.WARN
    _threadlocal: threading.local = threading.local()

    def __init__(self, logger: Logger, *, severity: Severity = None) -> None:
        self.logger = logger
        if severity:
            self.severity = level_number(severity)
        elif self.logger.level:
            self.severity = self.logger.level
        self._safewrap_handlers()

    def _safewrap_handlers(self):
        for handler in self.logger.handlers:
            self._safewrap_handler(handler)

    def _safewrap_handler(self, handler: logging.Handler) -> None:
        # Make the logger handlers dump internal errors to
        # :data:`sys.__stderr__` instead of :data:`sys.stderr` to circumvent
        # infinite loops.
        class WithSafeHandleError(logging.Handler):

            def handleError(self, record: logging.LogRecord) -> None:
                try:
                    traceback.print_exc(None, sys.__stderr__)
                except IOError:
                    pass    # see python issue 5971

        handler.handleError = WithSafeHandleError().handleError

    def write(self, data: Any) -> None:
        if not getattr(self._threadlocal, 'recurse_protection', False):
            data = data.strip()
            if data and not self.closed:
                self._threadlocal.recurse_protection = True
                try:
                    self.logger.log(self.severity, data)
                finally:
                    self._threadlocal.recurse_protection = False

    def writelines(self, lines: Sequence[str]) -> None:
        for line in lines:
            self.write(line)

    def flush(self) -> None:
        ...

    def close(self) -> None:
        self.closed = True

    def isatty(self) -> bool:
        return False


@contextmanager
def redirect_stdouts(logger: Logger = redirect_logger, *,
                     severity: Severity = None,
                     stdout: bool = True,
                     stderr: bool = True) -> ContextManager[FileLogProxy]:
    proxy = FileLogProxy(logger, severity=severity)
    if stdout:
        sys.stdout = proxy
    if stderr:
        sys.stderr = proxy
    try:
        yield proxy
    finally:
        if stdout:
            sys.stdout = sys.__stdout__
        if stderr:
            sys.stderr = sys.__stderr__
