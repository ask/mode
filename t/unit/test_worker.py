from unittest.mock import Mock, patch
from mode.worker import Worker
import pytest


class TestWorker:

        def setup_method(self, method):
            self.setup_logging_patch = patch("mode.worker.setup_logging")
            self.setup_logging = self.setup_logging_patch.start()

        def teardown_method(self):
            self.setup_logging_patch.stop()

        @pytest.mark.parametrize("loghandlers", [
            [],
            [Mock(), Mock()],
            [Mock()],
            None,
        ])
        def test_setup_logging(self, loghandlers):
            worker_inst = Worker(
                loglevel=5,
                logfile="TEMP",
                logformat="LOGFORMAT",
                loghandlers=loghandlers,
            )
            worker_inst._setup_logging()
            self.setup_logging.assert_called_once_with(
                loglevel=5,
                logfile="TEMP",
                logformat="LOGFORMAT",
                loghandlers=loghandlers,
            )

        def test_setup_logging_no_log_level(self):
            mock_log_handler = Mock()
            worker_inst = Worker(
                logfile="TEMP",
                logformat="LOGFORMAT",
                loghandlers=[mock_log_handler],
            )
            worker_inst._setup_logging()
            self.setup_logging.assert_not_called()
