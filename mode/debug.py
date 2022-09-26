"""Debugging utilities."""
import math
import signal
import traceback
from types import FrameType
from typing import Any, Type

from .services import Service
from .utils.logging import get_logger
from .utils.times import Seconds, want_seconds

__all__ = ["Blocking", "BlockingDetector"]

logger = get_logger(__name__)

if hasattr(signal, "setitimer"):  # pragma: no cover

    def arm_alarm(seconds: float) -> None:
        signal.setitimer(signal.ITIMER_REAL, seconds)


else:  # pragma: no cover
    try:
        import itimer
    except ImportError:

        def arm_alarm(seconds: float) -> None:
            signal.alarm(math.ceil(seconds))

    else:

        def arm_alarm(seconds: float) -> None:
            itimer(seconds)


class Blocking(RuntimeError):
    """Exception raised when event loop is blocked."""


class BlockingDetector(Service):
    """Service that detects blocking code using alarm/itimer.

    Examples:
        blockdetect = BlockingDetector(timeout=10.0)
        await blockdetect.start()

    Keyword Arguments:
        timeout (Seconds): number of seconds that the event loop can
            be blocked.
        raises (Type[BaseException]): Exception to raise when the blocking
            timeout is exceeded.  Defaults to :exc:`Blocking`.
    """

    logger = logger

    def __init__(
        self, timeout: Seconds, raises: Type[BaseException] = Blocking, **kwargs: Any
    ) -> None:
        self.timeout: float = want_seconds(timeout)
        self.raises: Type[BaseException] = raises
        super().__init__(**kwargs)

    @Service.task
    async def _deadman_switch(self) -> None:
        try:
            while not self.should_stop:
                self._reset_signal()
                await self.sleep(self.timeout * 0.96)
        finally:
            self._clear_signal()

    def _reset_signal(self) -> None:
        signal.signal(signal.SIGALRM, self._on_alarm)
        self._arm(self.timeout)

    def _clear_signal(self) -> None:
        self._arm(0)

    def _arm(self, timeout: float) -> None:
        arm_alarm(timeout)

    def _on_alarm(self, signum: int, frame: FrameType) -> None:
        msg = f"Blocking detected (timeout={self.timeout})"
        stack = "".join(traceback.format_stack(frame))
        self.log.warning("Blocking detected (timeout=%r) %s", self.timeout, stack)
        self._reset_signal()
        raise self.raises(msg)
