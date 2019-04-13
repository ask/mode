import asyncio
import io
import logging
import sys
import pytest
from mode.utils.logging import (
    CompositeLogger,
    DefaultFormatter,
    FileLogProxy,
    LogMessage,
    Logwrapped,
    _formatter_registry,
    _logger_config,
    _setup_logging,
    flight_recorder,
    formatter,
    get_logger,
    level_name,
    level_number,
    print_task_name,
    redirect_stdouts,
    setup_logging,
)
from mode.utils.mocks import ANY, AsyncMock, Mock, call, patch


def test__logger_config():
    assert _logger_config([1, 2], level='WARNING') == {
        'handlers': [1, 2],
        'level': 'WARNING',
    }


class test_CompositeLogger:

    @pytest.fixture()
    def logger(self):
        return Mock(name='logger')

    @pytest.fixture()
    def formatter(self):
        return Mock(name='formatter')

    @pytest.fixture()
    def log(self, *, logger, formatter):
        return CompositeLogger(logger=logger, formatter=formatter)

    def test_log(self, *, log, logger, formatter):
        log.log(logging.INFO, 'msg', 1, kw=2)
        logger.log.assert_called_once_with(
            logging.INFO,
            formatter.return_value,
            1, kw=2,
        )
        formatter.assert_called_once_with(logging.INFO, 'msg', 1, kw=2)

    def test_log__no_formatter(self, *, log, logger):
        log.formatter = None
        log.log(logging.INFO, 'msg', 1, kw=2)
        logger.log.assert_called_once_with(
            logging.INFO,
            'msg',
            1, kw=2,
        )

    @pytest.mark.parametrize('method,severity,extra', [
        ('debug', logging.DEBUG, {}),
        ('info', logging.INFO, {}),
        ('warn', logging.WARN, {}),
        ('warning', logging.WARN, {}),
        ('error', logging.ERROR, {}),
        ('crit', logging.CRITICAL, {}),
        ('critical', logging.CRITICAL, {}),
        ('exception', logging.ERROR, {'exc_info': 1}),
    ])
    def test_severity_mixin(self, method, severity, extra, *, log, logger):
        log.formatter = None
        getattr(log, method)('msg', 'arg1', kw1=3, kw2=5)
        logger.log.assert_called_once_with(
            severity, 'msg', 'arg1', kw1=3, kw2=5, **extra)

    def test_dev__enabled(self, log):
        log.info = Mock()
        with patch('mode.utils.logging.DEVLOG', True):
            log.dev('msg', 1, k=2)
            log.info.assert_called_once_with('msg', 1, k=2)

    def test_dev__disabled(self, log):
        log.info = Mock()
        with patch('mode.utils.logging.DEVLOG', False):
            log.dev('msg', 1, k=2)
            log.info.assert_not_called()


def test_formatter():
    f = Mock()
    formatter(f)
    try:
        assert f in _formatter_registry
    finally:
        _formatter_registry.remove(f)


def test_DefaultFormatter():
    record = logging.LogRecord(
        'name', logging.INFO, 'path', 303, 'msg',
        {'foo': 1, 'extra': {'data': {'moo': 30, 'baz': [1, 2]}}},
        exc_info=None,
    )
    DefaultFormatter().format(record)


@pytest.mark.parametrize('input,expected', [
    ('DEBUG', logging.DEBUG),
    ('INFO', logging.INFO),
    ('WARNING', logging.WARNING),
    ('WARNING', logging.WARNING),
    ('ERROR', logging.ERROR),
    ('CRITICAL', logging.CRITICAL),
    (logging.ERROR, logging.ERROR),
])
def test_level_number(input, expected):
    assert level_number(input) == expected


@pytest.mark.parametrize('input,expected', [
    (logging.DEBUG, 'DEBUG'),
    (logging.INFO, 'INFO'),
    (logging.WARN, 'WARNING'),
    (logging.WARNING, 'WARNING'),
    (logging.ERROR, 'ERROR'),
    (logging.CRITICAL, 'CRITICAL'),
    ('INFO', 'INFO'),
])
def test_level_name(input, expected):
    assert level_name(input) == expected


class test_setup_logging:

    def test_default(self):
        with patch('mode.utils.logging._setup_logging') as _sl:
            setup_logging(loglevel='INFO', logfile=None)

            _sl.assert_called_once_with(
                level=logging.INFO,
                filename=None,
                stream=sys.stdout,
                loghandlers=None,
                logging_config=None,
            )

    def test_logfile(self):
        with patch('mode.utils.logging._setup_logging') as _sl:
            setup_logging(loglevel='INFO', logfile='foo.txt')

            _sl.assert_called_once_with(
                level=logging.INFO,
                filename='foo.txt',
                stream=None,
                loghandlers=None,
                logging_config=None,
            )

    def test_io(self):
        logfile = Mock()
        with patch('mode.utils.logging._setup_logging') as _sl:
            setup_logging(loglevel='INFO', logfile=logfile)

            _sl.assert_called_once_with(
                level=logging.INFO,
                filename=None,
                stream=logfile,
                loghandlers=None,
                logging_config=None,
            )

    def test_io_no_tty(self):
        logfile = Mock()
        logfile.isatty.side_effect = AttributeError()
        with patch('mode.utils.logging._setup_logging') as _sl:
            setup_logging(loglevel='INFO', logfile=logfile)

            _sl.assert_called_once_with(
                level=logging.INFO,
                filename=None,
                stream=logfile,
                loghandlers=None,
                logging_config=None,
            )


class test__setup_logging:

    def setup_method(self, method):
        self.extension_formatter_patch = patch(
            'mode.utils.logging.ExtensionFormatter')
        self.extension_formatter = self.extension_formatter_patch.start()
        self.colorlog_patch = patch('mode.utils.logging.colorlog')
        self.colorlog = self.colorlog_patch.start()
        self.logging_patch = patch('mode.utils.logging.logging')
        self.logging = self.logging_patch.start()

    def teardown_method(self):
        self.extension_formatter_patch.stop()
        self.colorlog_patch.stop()
        self.logging_patch.stop()

    def test_get_logger(self):
        assert get_logger(__name__)
        assert get_logger(__name__).handlers == get_logger(__name__).handlers

    def test_setup_logging_helper_both_filename_and_stream(self):
        with pytest.raises(AssertionError):
            _setup_logging(filename='TEMP', stream=Mock())

    def test_setup_logging_helper_with_filename(self):
        _setup_logging(filename='TEMP')
        self.logging.config.dictConfig.assert_called_once_with(ANY)

    def test_setup_logging_helper_with_stream_no_handlers(self):
        _setup_logging(stream=Mock())
        self.logging.config.dictConfig.assert_called_once_with(ANY)

    def test_setup_logging_helper_with_stream(self):
        mock_handler = Mock()
        _setup_logging(
            filename=None,
            stream=Mock(),
            loghandlers=[mock_handler],
        )
        self.logging.config.dictConfig.assert_called_once_with(ANY)
        self.logging.root.handlers.extend.assert_called_once_with(
            [mock_handler])

    def test_setup_logging_helper_with_merge_config(self):
        _setup_logging(
            filename=None,
            stream=Mock(),
            logging_config={'merge': True, 'foo': 1},
        )
        self.logging.config.dictConfig.assert_called_once_with(ANY)

    def test_setup_logging_helper_no_merge_config(self):
        _setup_logging(
            logging_config={'merge': False, 'foo': 1},
        )
        self.logging.config.dictConfig.assert_called_once_with(ANY)


class test_Logwrapped:

    @pytest.fixture()
    def obj(self):
        return Mock(name='obj')

    @pytest.fixture()
    def logger(self):
        return Mock(name='logger')

    @pytest.fixture()
    def wrapped(self, *, obj, logger):
        return Logwrapped(obj, logger, severity='INFO', ident='ident')

    def test_constructor(self, wrapped):
        assert wrapped.severity == logging.INFO

    def test_wrapper(self, wrapped, obj):
        obj.calculate.__name__ = 'calculate'
        wrapped.calculate(1, 2, kw=1)
        obj.calculate.assert_called_once_with(1, 2, kw=1)

    def test_wrapper__no_ident(self, wrapped, obj):
        wrapped.ident = None
        obj.calculate.__name__ = 'calculate'
        wrapped.calculate(1, 2, kw=1)
        obj.calculate.assert_called_once_with(1, 2, kw=1)

    def test_wrapper__no_args(self, wrapped, obj):
        obj.calculate.__name__ = 'calculate'
        wrapped.calculate()
        obj.calculate.assert_called_once_with()

    def test_wrapper__only_kwargs(self, wrapped, obj):
        obj.calculate.__name__ = 'calculate'
        wrapped.calculate(kw=3)
        obj.calculate.assert_called_once_with(kw=3)

    def test_wrapper__ignored(self, wrapped, logger, obj):
        logger.log.assert_not_called()
        obj.__enter__ = Mock()
        obj.__exit__ = Mock()
        assert wrapped.__enter__ is obj.__enter__
        assert wrapped.__exit__ is obj.__exit__

    def test_repr(self, wrapped, obj):
        assert repr(wrapped) == repr(obj)

    def test_dir(self, wrapped, obj):
        assert dir(wrapped) == dir(obj)


def test_print_task_name():
    out = io.StringIO()
    task = Mock()
    task.__wrapped__ = Mock()
    task._coro.__name__ = 'foo'
    print_task_name(task, file=out)
    assert out.getvalue()

    task._coro.__name__ = None
    task.__wrapped__ = None
    print_task_name(task, file=out)
    assert out.getvalue()


class test_flight_recorder:

    @pytest.fixture()
    def logger(self):
        return Mock(name='logger')

    @pytest.fixture()
    def bb(self, *, logger):
        return flight_recorder(logger, timeout=30.0)

    def test_wrap_debug(self, bb):
        obj = Mock()
        bb.wrap = Mock()
        bb.wrap_debug(obj)
        bb.wrap.assert_called_once_with(logging.DEBUG, obj)

    def test_wrap_info(self, bb):
        obj = Mock()
        bb.wrap = Mock()
        bb.wrap_info(obj)
        bb.wrap.assert_called_once_with(logging.INFO, obj)

    def test_wrap_warn(self, bb):
        obj = Mock()
        bb.wrap = Mock()
        bb.wrap_warn(obj)
        bb.wrap.assert_called_once_with(logging.WARN, obj)

    def test_wrap_error(self, bb):
        obj = Mock()
        bb.wrap = Mock()
        bb.wrap_error(obj)
        bb.wrap.assert_called_once_with(logging.ERROR, obj)

    def test_wrap(self, bb):
        obj = Mock()
        with patch('mode.utils.logging.Logwrapped') as Logwrapped:
            ret = bb.wrap(logging.ERROR, obj)
            assert ret is Logwrapped.return_value
            Logwrapped.assert_called_once_with(
                logger=bb,
                severity=logging.ERROR,
                obj=obj,
            )

    def test_activate(self, bb):
        bb._fut = None
        bb._waiting = Mock()
        with patch('mode.utils.logging.current_task') as current_task:
            with patch('asyncio.ensure_future') as ensure_future:
                bb.activate()
                assert bb.started_at_date
                assert bb.enabled_by is current_task.return_value
                ensure_future.assert_called_once_with(
                    bb._waiting.return_value, loop=bb.loop,
                )
                assert bb._fut is ensure_future.return_value

    def test_activate__already_activated(self, bb):
        bb._fut = Mock()
        with pytest.raises(RuntimeError):
            bb.activate()

    def test_cancel(self, bb):
        bb._fut = None
        bb._logs = [1, 2, 3]
        bb.cancel()
        assert bb._logs == []
        assert bb._fut is None

        fut = bb._fut = Mock()
        bb.cancel()
        assert bb._fut is None
        fut.cancel.assert_called_once_with()

    def test_log__active(self, bb, logger):
        bb._fut = Mock()
        bb._buffer_log = Mock()
        bb.log(logging.DEBUG, 'msg %r %(foo)s', 1, foo='bar')
        bb._buffer_log.assert_called_once_with(
            logging.DEBUG, 'msg %r %(foo)s', (1,), {'foo': 'bar'},
        )

    def test_log__inactive(self, bb, logger):
        bb._fut = None
        bb._buffer_log = Mock()
        bb.log(logging.DEBUG, 'msg %r %(foo)s', 1, foo='bar')
        logger.log.assert_called_once_with(
            logging.DEBUG, 'msg %r %(foo)s', 1, foo='bar',
        )

    def test__buffer_log(self, bb):
        with patch('mode.utils.logging.asctime') as asctime:
            bb._buffer_log(
                logging.ERROR, 'msg %r %(foo)s', (1,), {'foo': 'bar'})
            assert bb._logs[-1] == LogMessage(
                logging.ERROR,
                'msg %r %(foo)s',
                asctime(),
                (1,),
                {'foo': 'bar'},
            )

    @pytest.mark.asyncio
    async def test__waiting__cancelled(self, bb):
        assert not bb._logs
        bb._buffer_log(
            logging.ERROR, 'msg %r %(foo)s', (1,), {'foo': 'bar'})
        with patch('asyncio.sleep', AsyncMock()) as sleep:
            sleep.coro.side_effect = asyncio.CancelledError()
            await bb._waiting()
            sleep.assert_called_once_with(bb.timeout)
            assert bb._logs

    @pytest.mark.asyncio
    async def test__waiting__has_logs(self, bb):
        assert not bb._logs
        bb._buffer_log(
            logging.ERROR, 'msg %r %(foo)s', (1,), {'foo': 'bar'})
        assert bb._logs
        with patch('asyncio.sleep', AsyncMock()):
            await bb._waiting()

    @pytest.mark.asyncio
    async def test__waiting__no_logs(self, bb):
        assert not bb._logs
        with patch('asyncio.sleep', AsyncMock()):
            await bb._waiting()

    @pytest.mark.asyncio
    async def test__waiting__enabled_by(self, bb):
        assert not bb._logs
        bb.enabled_by = Mock()
        with patch('asyncio.sleep', AsyncMock()):
            with patch('mode.utils.logging.format_task_stack') as fts:
                await bb._waiting()
            fts.assert_called_once_with(bb.enabled_by)

    @pytest.mark.asyncio
    async def test__waiting__raises(self, bb):
        assert not bb._logs
        bb.logger.warning = Mock(side_effect=KeyError())
        with patch('asyncio.sleep', AsyncMock()):
            with pytest.raises(KeyError):
                await bb._waiting()

    def test_repr(self, bb):
        assert repr(bb)

    def test_context(self, bb):
        bb.activate = Mock()
        bb.cancel = Mock()
        with bb:
            bb.activate.assert_called_once_with()
        bb.cancel.assert_called_once_with()


class test_FileLogProxy:

    def test_constructor__defaults(self):
        logger = get_logger('foo')
        logger.level = None
        assert logger.level is None
        f = FileLogProxy(logger)
        assert f.severity == logging.WARN

    def test_constructor__severity_from_logger(self):
        logger = get_logger('foo')
        logger.level = logging.DEBUG
        f = FileLogProxy(logger)
        assert f.severity == logging.DEBUG

    def test_constructor__explicit_severity(self):
        logger = get_logger('foo')
        logger.level = logging.DEBUG
        f = FileLogProxy(logger, severity=logging.ERROR)
        assert f.severity == logging.ERROR

    def test__safewrap_handler(self):
        f = FileLogProxy(get_logger('foo'))
        handler = Mock()
        f._safewrap_handler(handler)

        with patch('traceback.print_exc') as print_exc:
            record = Mock()
            handler.handleError(record)
            print_exc.assert_called_once_with(None, sys.__stderr__)
            print_exc.side_effect = IOError()
            handler.handleError(record)

    def test_write(self):
        logger = Mock(handlers=[])
        f = FileLogProxy(logger)
        f._threadlocal.recurse_protection = True
        f.write('foo')
        logger.log.assert_not_called()

        f._threadlocal.recurse_protection = False
        f.write('')
        f.write('               ')
        f.close()
        f.write('msg')
        logger.log.assert_not_called()

        f.closed = False
        f.write(' msg ')
        logger.log.assert_called_once_with(f.severity, 'msg')

        f.writelines(['foo', 'bar'])
        logger.log.assert_has_calls([
            call(f.severity, 'msg'),
            call(f.severity, 'foo'),
            call(f.severity, 'bar'),
        ])

    def test_flush(self):
        FileLogProxy(get_logger('foo')).flush()

    def test_isatty(self):
        assert not FileLogProxy(get_logger('foo')).isatty()


def test_redirect_stdouts():
    prev_stdout = sys.stdout
    prev_stderr = sys.stderr
    with redirect_stdouts(stdout=False, stderr=False):
        assert sys.stdout == prev_stdout
        assert sys.stderr == prev_stderr
    prev_stdout = sys.stdout  # pytest keep changing this
    prev_stderr = sys.stderr
    with redirect_stdouts(stdout=True, stderr=False):
        assert isinstance(sys.stdout, FileLogProxy)
        assert sys.stderr == prev_stderr
    prev_stdout = sys.stdout
    prev_stderr = sys.stderr
    with redirect_stdouts(stdout=False, stderr=True):
        assert sys.stdout == prev_stdout
        assert isinstance(sys.stderr, FileLogProxy)
    prev_stdout = sys.stdout
    prev_stderr = sys.stderr
    with redirect_stdouts(stdout=True, stderr=True):
        assert isinstance(sys.stdout, FileLogProxy)
        assert isinstance(sys.stderr, FileLogProxy)
