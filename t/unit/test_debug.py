import signal
import sys
from unittest.mock import AsyncMock, Mock, patch

import pytest

from mode.debug import Blocking, BlockingDetector


@pytest.mark.skipif(sys.platform == "win32", reason="win32: no SIGALRM")
class test_BlockingDetector:
    @pytest.fixture()
    def block(self):
        return BlockingDetector(timeout=10.0)

    @pytest.mark.asyncio
    async def test__deadman_switch(self, block):
        block._reset_signal = Mock()
        block.sleep = AsyncMock()

        def on_sleep(*args, **kwargs):
            block._stopped.set()

        block.sleep.side_effect = on_sleep
        await block._deadman_switch(block)

    def test_reset_signal(self, block):
        with patch("signal.signal") as sig:
            block._arm = Mock()
            block._reset_signal()

            sig.assert_called_once_with(signal.SIGALRM, block._on_alarm)
            block._arm.assert_called_with(10.0)

    def test__clear_signal(self, block):
        block._arm = Mock()
        block._clear_signal()
        block._arm.asssert_called_once_with(0)

    def test__arm(self, block):
        with patch("mode.debug.arm_alarm") as arm_alarm:
            block._arm(1.11)
            arm_alarm.assert_called_once_with(1.11)

    def test__on_alarm(self, block):
        with patch("traceback.format_stack"):
            block._reset_signal = Mock()
            with pytest.raises(Blocking):
                block._on_alarm(30, Mock())
