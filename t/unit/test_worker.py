from mode.worker import Worker
from mode.utils.mocks import Mock, patch
import pytest


class test_Worker:

        def setup_method(self, method):
            self.setup_logging_patch = patch(
                'mode.utils.logging.setup_logging')
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
                logging_config=None,
                loghandlers=loghandlers,
            )
            worker_inst._setup_logging()
            self.setup_logging.assert_called_once_with(
                loglevel=5,
                logfile="TEMP",
                logging_config=None,
                loghandlers=loghandlers or [],
            )
