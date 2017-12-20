from unittest.mock import Mock, patch
from mode.utils import logging
from mode.utils.logging import get_logger
import pytest


class TestFeedController:

    def setup_method(self, method):
        self.extension_formatter_patch = patch(
            "mode.utils.logging.ExtensionFormatter")
        self.extension_formatter = self.extension_formatter_patch.start()
        self.colorlog_patch = patch("mode.utils.logging.colorlog")
        self.colorlog = self.colorlog_patch.start()
        self.logging_patch = patch("mode.utils.logging.logging")
        self.logging = self.logging_patch.start()

    def teardown_method(self):
        self.extension_formatter_patch.stop()
        self.colorlog_patch.stop()
        self.logging_patch.stop()

    def test_setup_console_handler(self):
        resp = logging._setup_console_handler()
        self.extension_formatter.assert_called_once_with(
            logging.DEFAULT_FORMAT,
            log_colors=logging.DEFAULT_COLORS,
        )
        self.colorlog.StreamHandler.assert_called_once_with(None)
        assert resp == self.colorlog.StreamHandler()

    def test_setup_console_handler_with_set_parameters(self):
        mock_stream = Mock()
        resp = logging._setup_console_handler(
            stream=mock_stream, format="TEMP", log_colors={"T": "A"})
        self.extension_formatter.assert_called_once_with(
            "TEMP",
            log_colors={"T": "A"},
        )
        self.colorlog.StreamHandler.assert_called_once_with(mock_stream)
        assert resp == self.colorlog.StreamHandler()

    def test_get_logger(self):
        assert get_logger(__name__)
        assert get_logger(__name__).handlers == get_logger(__name__).handlers

    def test_setup_logging_helper_both_filename_and_stream(self):
        with pytest.raises(AssertionError):
            logging._setup_logging(filename="TEMP", stream=Mock())

    def test_setup_logging_helper_with_filename(self):
        logging._setup_logging(filename="TEMP")
        self.logging.basicConfig.assert_called_once_with(
            filename="TEMP")

    def test_setup_logging_helper_with_stream_no_handlers(self):
        logging._setup_logging(stream=Mock())
        self.logging.basicConfig.assert_called_once_with(
            handlers=[self.colorlog.StreamHandler()])

    def test_setup_logging_helper_with_stream(self):
        mock_handler = Mock()
        logging._setup_logging(stream=Mock(), handlers=[mock_handler])
        self.logging.basicConfig.assert_called_once_with(
            handlers=[mock_handler, self.colorlog.StreamHandler()])

    def test_setup_logging_no_log_handlers(self):
        assert logging.setup_logging(loghandlers=[]) is None
        self.logging.basicConfig.assert_called_once_with(
            handlers=[self.colorlog.StreamHandler()], level=None)

    def test_setup_logging(self):
        mock_handler = Mock()
        assert logging.setup_logging(
            loglevel=5, loghandlers=[mock_handler]) == 5
        self.logging.basicConfig.assert_called_once_with(
            handlers=[mock_handler, self.colorlog.StreamHandler()], level=5)
