from mode.utils import logging
from mode.utils.logging import get_logger
from mode.utils.mocks import ANY, Mock, patch
import pytest


class test_FeedController:

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

    def test_get_logger(self):
        assert get_logger(__name__)
        assert get_logger(__name__).handlers == get_logger(__name__).handlers

    def test_setup_logging_helper_both_filename_and_stream(self):
        with pytest.raises(AssertionError):
            logging._setup_logging(filename="TEMP", stream=Mock())

    def test_setup_logging_helper_with_filename(self):
        logging._setup_logging(filename="TEMP")
        self.logging.config.dictConfig.assert_called_once_with(ANY)

    def test_setup_logging_helper_with_stream_no_handlers(self):
        logging._setup_logging(stream=Mock())
        self.logging.config.dictConfig.assert_called_once_with(ANY)

    def test_setup_logging_helper_with_stream(self):
        mock_handler = Mock()
        logging._setup_logging(stream=Mock(), loghandlers=[mock_handler])
        self.logging.config.dictConfig.assert_called_once_with(ANY)
        self.logging.root.handlers.extend.assert_called_once_with(
            [mock_handler])
