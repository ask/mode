"""Logging utilities."""
import abc
import asyncio
import logging
import logging.config
import os
import sys
import threading
import traceback
import typing
from contextlib import contextmanager
from functools import singledispatch, wraps
from itertools import count
from logging import Logger
from pprint import pprint
from time import asctime
from types import TracebackType
from typing import (
    Any,
    AnyStr,
    BinaryIO,
    Callable,
    ClassVar,
    ContextManager,
    Dict,
    IO,
    Iterable,
    Iterator,
    List,
    Mapping,
    NamedTuple,
    Optional,
    Set,
    TextIO,
    Tuple,
    Type,
    Union,
    cast,
)
from .contexts import ExitStack
from .futures import all_tasks, current_task
from .locals import LocalStack
from .text import title
from .times import Seconds, want_seconds
from .tracebacks import format_task_stack, print_task_stack
from .typing import Protocol

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
    'formatter2',
    'get_logger',
    'level_name',
    'level_number',
    'redirect_logger',
    'redirect_stdouts',
    'setup_logging',
]

DEVLOG: bool = bool(os.environ.get('DEVLOG', ''))
DEFAULT_FORMAT: str = '''
[%(asctime)s] [%(process)s] [%(levelname)s]: %(message)s %(extra)s
'''.strip()

DEFAULT_COLOR_FORMAT = '''
[%(asctime)s] [%(process)s] [%(levelname)s] %(log_color)s%(message)s %(extra)s
'''.strip()


DEFAULT_COLORS = {
    **colorlog.default_log_colors,
    'INFO': 'white',
    'DEBUG': 'blue',
}

DEFAULT_FORMATTERS = {
    'default': {
        '()': 'mode.utils.logging.DefaultFormatter',
        'format': DEFAULT_FORMAT,
    },
    'colored': {
        '()': 'mode.utils.logging.ExtensionFormatter',
        'format': DEFAULT_COLOR_FORMAT,
        'log_colors': DEFAULT_COLORS,
        'stream': sys.stdout,
    },
}


current_flight_recorder_stack: LocalStack['flight_recorder']
current_flight_recorder_stack = LocalStack()


def current_flight_recorder() -> Optional['flight_recorder']:
    return current_flight_recorder_stack.top


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
FormatterHandler2 = Callable[[Any, logging.LogRecord], Any]
Severity = Union[int, str]

_formatter_registry: Set[FormatterHandler] = set()
_formatter_registry2: Set[FormatterHandler2] = set()


def get_logger(name: str) -> Logger:
    """Get logger by name."""
    logger = logging.getLogger(name)
    if not logger.handlers:
        logger.addHandler(logging.NullHandler())
    return logger


redirect_logger = get_logger('mode.redirect')


class HasLog(Protocol):

    @abc.abstractmethod
    def log(self,
            severity: int,
            message: str,
            *args: Any, **kwargs: Any) -> None:
        ...


if typing.TYPE_CHECKING:
    LogSeverityMixinBase = HasLog
else:
    LogSeverityMixinBase = object


class LogSeverityMixin(LogSeverityMixinBase):
    """Mixin class that delegates standard logging methods to logger.

    The class that mixes in this class must define the ``log`` method.

    Example:
        >>> class Foo(LogSeverityMixin):
        ...
        ...    logger = get_logger('foo')
        ...
        ...    def log(self,
        ...            severity: int,
        ...            message: str,
        ...            *args: Any, **kwargs: Any) -> None:
        ...        return self.logger.log(severity, message, *args, **kwargs)
    """

    def dev(self: HasLog, message: str, *args: Any, **kwargs: Any) -> None:
        if DEVLOG:
            self.log(logging.INFO, message, *args, **kwargs)

    def debug(self: HasLog, message: str, *args: Any, **kwargs: Any) -> None:
        self.log(logging.DEBUG, message, *args, **kwargs)

    def info(self: HasLog, message: str, *args: Any, **kwargs: Any) -> None:
        self.log(logging.INFO, message, *args, **kwargs)

    def warn(self: HasLog, message: str, *args: Any, **kwargs: Any) -> None:
        self.log(logging.WARN, message, *args, **kwargs)

    def warning(self: HasLog, message: str, *args: Any, **kwargs: Any) -> None:
        self.log(logging.WARN, message, *args, **kwargs)

    def error(self: HasLog, message: str, *args: Any, **kwargs: Any) -> None:
        self.log(logging.ERROR, message, *args, **kwargs)

    def crit(self: HasLog, message: str, *args: Any, **kwargs: Any) -> None:
        self.log(logging.CRITICAL, message, *args, **kwargs)

    def critical(self: HasLog, message: str,
                 *args: Any, **kwargs: Any) -> None:
        self.log(logging.CRITICAL, message, *args, **kwargs)

    def exception(self: HasLog, message: str,
                  *args: Any, **kwargs: Any) -> None:
        self.log(logging.ERROR, message, *args, exc_info=1, **kwargs)


class CompositeLogger(LogSeverityMixin):
    """Composite logger for classes.

    The class can be used as both mixin and composite,
    and may also define a ``.formatter`` attribute
    which will reformat any log messages sent.

    Service uses this to add logging methods:

    .. sourcecode:: python

        class Service(ServiceT):

            log: CompositeLogger

            def __init__(self):
                self.log = CompositeLogger(
                    logger=self.logger,
                    formatter=self._format_log,
                )

            def _format_log(self, severity: int, message: str,
                            *args: Any, **kwargs: Any) -> str:
                return (f'[^{"-" * (self.beacon.depth - 1)}'
                        f'{self.shortlabel}]: {message}')

    This means those defining a service may also use it to log:

    .. sourcecode:: pycon

        >>> service.log.info('Something happened')

    and when logging additional information about the service is automatically
    included.
    """

    logger: Logger

    def __init__(self,
                 logger: Logger,
                 formatter: Callable[..., str] = None) -> None:
        self.logger = logger
        self.formatter: Optional[Callable[..., str]] = formatter

    def log(self, severity: int, message: str,
            *args: Any, **kwargs: Any) -> None:
        self.logger.log(severity,
                        self.format(severity, message, *args, **kwargs),
                        *args, **kwargs)

    def format(self, severity: int, message: str,
               *args: Any, **kwargs: Any) -> str:
        if self.formatter:
            return self.formatter(severity, message, *args, **kwargs)
        return message


def formatter(fun: FormatterHandler) -> FormatterHandler:
    """Register formatter for logging positional args."""
    _formatter_registry.add(fun)
    return fun


def formatter2(fun: FormatterHandler2) -> FormatterHandler2:
    """Register formatter for logging positional args.

    Like :func:`formatter` but the handler accepts
    two arguments instead of one: ``(arg, logrecord)``.

    Passing the log record as additional argument expands
    the capabilities of the formatter to do things
    such as read the log message.
    """
    _formatter_registry2.add(fun)
    return fun


def _format_extra(record: logging.LogRecord) -> str:
    return ', '.join(
        f'{k}={v!r}' for k, v in record.__dict__.get('data', {}).items()
    )


class DefaultFormatter(logging.Formatter):
    """Default formatter adds support for extra data."""

    def format(self, record: logging.LogRecord) -> str:
        record.extra = _format_extra(record)  # type: ignore
        return super().format(record)


class ExtensionFormatter(colorlog.TTYColoredFormatter):  # type: ignore
    """Formatter that can register callbacks to format args.

    Extends :pypi:`colorlog`.
    """

    def __init__(self, stream: IO = None, **kwargs: Any) -> None:
        super().__init__(stream=stream or sys.stdout, **kwargs)

    def format(self, record: logging.LogRecord) -> str:
        self._format_args(record)
        record.extra = _format_extra(record)  # type: ignore
        return cast(str, super().format(record))

    def _format_args(self, record: logging.LogRecord) -> None:
        format_arg = self.format_arg
        if isinstance(record.args, Mapping):
            # logger.log(severity, "msg %(foo)s", foo=303)
            record.args = {
                k: format_arg(v, record) for k, v in record.args.items()
            }
        else:
            if not isinstance(record.args, tuple):
                # logger.log(severity, "msg %s", foo)
                # mypy thinks this is unreachable as record is
                # always Tuple
                record.args = (record.args,)  # type: ignore
            # logger.log(severity, "msg %s", ('foo',))
            record.args = tuple(
                format_arg(arg, record) for arg in record.args
            )

    def format_arg(self, arg: Any, record: logging.LogRecord) -> Any:
        return self._format_arg2(self._format_arg(arg), record)

    def _format_arg(self, arg: Any) -> Any:
        # Reduce value by calling all registered formatters.
        for fun in _formatter_registry:
            res = fun(arg)
            if res is not None:
                arg = res
        return arg

    def _format_arg2(self, arg: Any, record: logging.LogRecord) -> Any:
        for fun in _formatter_registry2:
            res = fun(arg, record)
            if res is not None:
                arg = res
        return arg


@singledispatch
def level_name(loglevel: int) -> str:
    """Convert log level to number."""
    return cast(str, logging.getLevelName(loglevel))


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
        loghandlers: List[logging.Handler] = None,
        logging_config: Dict = None) -> int:
    """Configure logging subsystem."""
    stream: Optional[IO] = None
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
                   loghandlers: List[logging.Handler] = None,
                   logging_config: Dict = None) -> None:
    handlers = {}
    if filename:
        assert stream is None
        handlers.update({
            'default': {
                'level': level,
                'class': 'logging.FileHandler',
                'formatter': 'default',
                'filename': filename,
            },
        })
    elif stream:
        handlers.update({
            'default': {
                'level': level,
                'class': 'colorlog.StreamHandler',
                'formatter': 'colored',
            },
        })
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
        self.severity = level_number(severity) if severity else logging.WARN
        self.ident = ident

    def __getattr__(self, key: str) -> Any:
        meth = getattr(self.obj, key)

        ignore = object.__getattribute__(self, '_ignore')

        if not callable(meth) or key in ignore:
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

    def __repr__(self) -> str:
        return repr(self.obj)

    def __dir__(self) -> List[str]:
        return dir(self.obj)


def cry(file: IO,
        *,
        sep1: str = '=',
        sep2: str = '-',
        sep3: str = '~',
        seplen: int = 49) -> None:  # pragma: no cover
    """Return stack-trace of all active threads.

    See Also:
        Taken from https://gist.github.com/737056.
    """
    # get a map of threads by their ID so we can print their names
    # during the traceback dump
    tmap = {t.ident: t for t in threading.enumerate()}

    current_thread = threading.current_thread()
    sep1 = sep1 * seplen if len(sep1) == 1 else sep1
    sep2 = sep2 * seplen if len(sep2) == 1 else sep2
    sep3 = sep3 * seplen if len(sep3) == 1 else sep3

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
                for task in all_tasks(loop=loop):
                    print_task_name(task, file=file)
                    print(f'  {sep3}', file=file)
                    print_task_stack(task, file=file, capture_locals=True)
            print('\n', file=file)                               # noqa: T003


def print_task_name(task: asyncio.Task, file: IO) -> None:
    """Print name of :class:`asyncio.Task` in tracebacks."""
    coro = task._coro  # type: ignore
    wrapped = getattr(task, '__wrapped__', None)
    coro_name = getattr(coro, '__name__', None)
    if coro_name is None:
        # some coroutines does not have a __name__ attribute
        # e.g. async_generator_asend
        coro_name = repr(coro)
    print(f'  TASK {coro_name}', file=file)
    if wrapped:
        print(f'   -> {wrapped}', file=file)
    print(f'   {task!r}', file=file)


class LogMessage(NamedTuple):
    """Archived log message."""

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

    _id_source: ClassVar[Iterator[int]] = count(1)

    logger: Any
    timeout: float
    loop: asyncio.AbstractEventLoop
    started_at_date: Optional[str]
    enabled_by: Optional[asyncio.Task]
    extra_context: Dict[str, Any]

    _fut: Optional[asyncio.Future]
    _logs: List[LogMessage]
    _default_context: Dict[str, Any]

    def __init__(self, logger: Any, *,
                 timeout: Seconds,
                 loop: asyncio.AbstractEventLoop = None) -> None:
        self.id = next(self._id_source)
        self.logger = logger
        self.timeout = want_seconds(timeout)
        self.loop = loop or asyncio.get_event_loop()
        self.started_at_date = None
        self.enabled_by = None
        self.exit_stack = ExitStack()
        self._fut = None
        self._logs = []
        self.extra_context = {}

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
        self.enabled_by = current_task()
        self.started_at_date = asctime()
        current_flight_recorder = current_flight_recorder_stack.top
        if current_flight_recorder is not None:
            for k, v in current_flight_recorder.extra_context.items():
                self.extra_context.setdefault(k, v)
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
            self.blush()

    def blush(self) -> None:
        try:
            logger = self.logger
            ident = self._ident()
            logger.warning('Warning: Task timed out!')
            logger.warning(
                "Please make sure it's hanging before restart.")
            logger.info('[%s] (started at %s) Replaying logs...',
                        ident, self.started_at_date)
            self.flush_logs(ident=ident)
            logger.info('[%s] -End of log-', ident)
            logger.info('[%s] Task traceback', ident)
            if self.enabled_by is not None:
                logger.info(format_task_stack(self.enabled_by))
            else:
                logger.info('[%s] -missing-: not enabled by task')
        except Exception as exc:
            logger.exception('Flight recorder internal error: %r', exc)
            raise

    def flush_logs(self, ident: str = None) -> None:
        logs = self._logs
        logger = self.logger
        ident = ident or self._ident()
        if logs:
            try:
                for sev, message, datestr, args, kwargs in logs:
                    self._fill_extra_context(kwargs)
                    logger.log(
                        sev, f'[%s] (%s) {message}', ident, datestr,
                        *args, **kwargs)
            finally:
                logs.clear()

    def _fill_extra_context(self, kwargs: Dict) -> None:
        if self.extra_context:
            extra = kwargs['extra'] = kwargs.get('extra') or {}
            extra['data'] = {
                **self.extra_context,
                **(extra.get('data') or {}),
            }

    def _ident(self) -> str:
        return f'{title(type(self).__name__)}-{self.id}'

    def __repr__(self) -> str:
        return f'<{self._ident()} @{id(self):#x}>'

    def __enter__(self) -> 'flight_recorder':
        self.activate()
        self.exit_stack.enter_context(
            current_flight_recorder_stack.push(self))
        self.exit_stack.__enter__()
        return self

    def __exit__(self,
                 exc_type: Type[BaseException] = None,
                 exc_val: BaseException = None,
                 exc_tb: TracebackType = None) -> Optional[bool]:
        self.exit_stack.__exit__(exc_type, exc_val, exc_tb)
        self.cancel()
        return None


class _FlightRecorderProxy(LogSeverityMixin):

    def log(self,
            severity: int,
            message: str,
            *args: Any, **kwargs: Any) -> None:
        fl = self.current_flight_recorder()
        if fl is not None:
            return fl.log(severity, message, *args, **kwargs)

    def current_flight_recorder(self) -> Optional[flight_recorder]:
        return current_flight_recorder()


class FileLogProxy(TextIO):
    """File-like object that forwards data to logger."""

    severity: int = logging.WARN
    _threadlocal: threading.local = threading.local()
    _closed: bool = False

    def __init__(self, logger: Logger, *, severity: Severity = None) -> None:
        self.logger = logger
        if severity:
            self.severity = level_number(severity)
        elif self.logger.level:
            self.severity = self.logger.level
        self._safewrap_handlers()

    def _safewrap_handlers(self) -> None:
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

        handler.handleError = WithSafeHandleError().handleError  # type: ignore

    def write(self, s: AnyStr) -> int:
        if not getattr(self._threadlocal, 'recurse_protection', False):
            data = s.strip()
            if data and not self.closed:
                self._threadlocal.recurse_protection = True
                try:
                    self.logger.log(self.severity, data)
                finally:
                    self._threadlocal.recurse_protection = False
        return len(s)

    def writelines(self, lines: Iterable[str]) -> None:
        for line in lines:
            self.write(line)

    @property
    def buffer(self) -> BinaryIO:
        raise NotImplementedError()

    @property
    def encoding(self) -> str:
        return sys.getdefaultencoding()

    @property
    def errors(self) -> Optional[str]:
        return None

    def line_buffering(self) -> bool:
        return False

    @property
    def newlines(self) -> bool:
        return False

    def flush(self) -> None:
        ...

    @property
    def mode(self) -> str:
        return 'w'

    @property
    def name(self) -> str:
        return ''

    def close(self) -> None:
        self._closed = True

    @property
    def closed(self) -> bool:
        return self._closed

    def fileno(self) -> int:
        raise NotImplementedError()

    def isatty(self) -> bool:
        return False

    def read(self, n: int = -1) -> AnyStr:
        raise NotImplementedError()

    def readable(self) -> bool:
        return False

    def readline(self, limit: int = -1) -> AnyStr:
        raise NotImplementedError()

    def readlines(self, hint: int = -1) -> List[AnyStr]:
        raise NotImplementedError()

    def seek(self, offset: int, whence: int = 0) -> int:
        raise NotImplementedError()

    def seekable(self) -> bool:
        return False

    def tell(self) -> int:
        raise NotImplementedError()

    def truncate(self, size: int = None) -> int:
        raise NotImplementedError()

    def writable(self) -> bool:
        return True

    def __iter__(self) -> Iterator[str]:
        raise NotImplementedError()

    def __next__(self) -> str:
        raise NotImplementedError()

    def __enter__(self) -> 'FileLogProxy':
        return self

    def __exit__(self,
                 exc_type: Type[BaseException] = None,
                 exc_val: BaseException = None,
                 exc_tb: TracebackType = None) -> Optional[bool]:
        ...


@contextmanager
def redirect_stdouts(logger: Logger = redirect_logger, *,
                     severity: Severity = None,
                     stdout: bool = True,
                     stderr: bool = True) -> Iterator[FileLogProxy]:
    """Redirect :data:`sys.stdout` and :data:`sys.stdout` to logger."""
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


on_timeout = _FlightRecorderProxy()
