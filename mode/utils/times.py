"""Time, date and timezone related utilities."""
import abc
import asyncio
import sys
import time
from datetime import timedelta
from functools import singledispatch
from types import TracebackType
from typing import Callable, List, Mapping, NamedTuple, Optional, Type, Union

from .text import pluralize
from .typing import AsyncContextManager

__all__ = [
    "Bucket",
    "Seconds",
    "TokenBucket",
    "rate",
    "rate_limit",
    "want_seconds",
    "humanize_seconds",
    "humanize_seconds_ago",
]

TIME_MONOTONIC: Callable[[], float]
if sys.platform == "win32":
    TIME_MONOTONIC = time.time
else:
    TIME_MONOTONIC = time.monotonic

#: Seconds can be expressed as float or :class:`~datetime.timedelta`,
Seconds = Union[timedelta, float, str]


class Unit(NamedTuple):
    name: str
    value: float
    format: Callable[[float], str]  # noqa: E701


TIME_UNITS: List[Unit] = [
    Unit("day", 60 * 60 * 24.0, lambda n: format(n, ".2f")),
    Unit("hour", 60 * 60.0, lambda n: format(n, ".2f")),
    Unit("minute", 60.0, lambda n: format(n, ".2f")),
    Unit("second", 1.0, lambda n: format(n, ".2f")),
]

#: What the characters in a "rate" string means.
#: E.g. 8/s is "eight in one second"
RATE_MODIFIER_MAP: Mapping[str, Callable[[float], float]] = {
    "s": lambda n: n,
    "m": lambda n: n / 60.0,
    "h": lambda n: n / 60.0 / 60.0,
    "d": lambda n: n / 60.0 / 60.0 / 24,
}


class Bucket(AsyncContextManager):
    """Rate limiting state.

    A bucket "pours" tokens at a rate of ``rate`` per second (or over').

    Calling `bucket.pour()`, pours one token by default, and returns
    :const:`True` if that amount can be poured now, or :const:`False` if the
    caller has to wait.

    If this returns :const:`False`, it's prudent to either sleep or raise
    an exception::

        if not bucket.pour():
            await asyncio.sleep(bucket.expected_time())

    If you want to consume multiple tokens in one go then specify the number::

        if not bucket.pour(10):
            await asyncio.sleep(bucket.expected_time(10))

    This class can also be used as an async. context manager, but in that case
    can only consume one tokens at a time::

        async with bucket:
            # do something

    By default the async. context manager will suspend the current coroutine
    and sleep until as soon as the time that a token can be consumed.

    If you wish you can also raise an exception, instead of sleeping, by
    providing the ``raises`` keyword argument::

        # hundred tokens in one second, and async with: raises TimeoutError

        class MyError(Exception):
            pass

        bucket = Bucket(100, over=1.0, raises=MyError)

        async with bucket:
            # do something

    """

    rate: float
    capacity: float

    _tokens: float

    def __init__(
        self,
        rate: Seconds,
        over: Seconds = 1.0,
        *,
        fill_rate: Seconds = None,
        capacity: Seconds = None,
        raises: Type[BaseException] = None,
        loop: asyncio.AbstractEventLoop = None
    ) -> None:
        self.rate = want_seconds(rate)
        self.capacity = want_seconds(over)
        self.raises = raises
        self.loop = loop
        self._tokens = self.capacity
        self.__post_init__()

    def __post_init__(self) -> None:
        ...

    @abc.abstractmethod
    def pour(self, tokens: int = 1) -> bool:
        ...

    @abc.abstractmethod
    def expected_time(self, tokens: int = 1) -> float:
        ...

    @property
    @abc.abstractmethod
    def tokens(self) -> float:
        ...

    @property
    def fill_rate(self) -> float:
        #: Defaults to rate! If you want the bucket to fill up
        #: faster/slower, then just override this.
        return self.rate

    async def __aenter__(self) -> "Bucket":
        if not self.pour():
            if self.raises:
                raise self.raises()
            expected_time = self.expected_time()
            await asyncio.sleep(expected_time)
        return self

    async def __aexit__(
        self,
        exc_type: Type[BaseException] = None,
        exc_val: BaseException = None,
        exc_tb: TracebackType = None,
    ) -> Optional[bool]:
        return None


class TokenBucket(Bucket):
    """Rate limiting using the token bucket algorithm."""

    _tokens: float
    _last_pour: float

    def __post_init__(self) -> None:
        self._last_pour = TIME_MONOTONIC()

    def pour(self, tokens: int = 1) -> bool:
        need = tokens
        have = self.tokens
        if have < need:
            return False
        self._tokens -= tokens
        return True

    def expected_time(self, tokens: int = 1) -> float:
        have = self._tokens
        need = max(tokens, have)
        time_left = (need - have) / self.fill_rate
        return max(time_left, 0.0)

    @property
    def tokens(self) -> float:
        now = TIME_MONOTONIC()
        if now < self._last_pour:
            return self._tokens
        if self._tokens < self.capacity:
            delta = self.fill_rate * (now - self._last_pour)
            self._tokens = min(self.capacity, self._tokens + delta)
            self._last_pour = now
        return self._tokens


@singledispatch
def rate(r: float) -> float:
    """Convert rate string (`"100/m"`, `"2/h"` or `"0.5/s"`) to seconds."""
    return r


@rate.register(str)
def _rate_str(r: str) -> float:  # noqa: F811
    ops, _, modifier = r.partition("/")
    return RATE_MODIFIER_MAP[modifier or "s"](float(ops)) or 0


@rate.register(int)  # noqa: F811
def _rate_int(r: int) -> float:
    return float(r)


@rate.register(type(None))  # noqa: F811
def _rate_None(r: None) -> float:
    return 0.0


def rate_limit(
    rate: float,
    over: Seconds = 1.0,
    *,
    bucket_type: Type[Bucket] = TokenBucket,
    raises: Type[BaseException] = None,
    loop: asyncio.AbstractEventLoop = None
) -> Bucket:
    """Create rate limiting manager."""
    return bucket_type(rate, over, raises=raises, loop=loop)


@singledispatch
def want_seconds(s: float) -> float:
    """Convert :data:`Seconds` to float."""
    return s


@want_seconds.register(str)  # noqa: F811
def _want_seconds_str(s: str) -> float:
    return rate(s)


@want_seconds.register(timedelta)  # noqa: F811
def _want_seconds_timedelta(s: timedelta) -> float:
    return s.total_seconds()


def humanize_seconds(
    secs: float,
    *,
    prefix: str = "",
    suffix: str = "",
    sep: str = "",
    now: str = "now",
    microseconds: bool = False
) -> str:
    """Show seconds in human form.

    For example, 60 becomes "1 minute", and 7200 becomes "2 hours".

    Arguments:
        secs: Seconds to format (as :class:`float` or :class:`int`).
        prefix (str): can be used to add a preposition to the output
            (e.g., 'in' will give 'in 1 second', but add nothing to 'now').
        suffix (str): same as prefix, adds suffix unless 'now'.
        sep (str): separator between prefix and number.
        now (str): Literal 'now'.
        microseconds (bool): Include microseconds.
    """
    secs = float(format(float(secs), ".2f"))
    for unit, divider, formatter in TIME_UNITS:
        if secs >= divider:
            w = secs / float(divider)
            return "{0}{1}{2} {3}{4}".format(
                prefix, sep, formatter(w), pluralize(int(w), unit), suffix
            )
    if microseconds and secs > 0.0:
        return "{prefix}{sep}{0:.2f} seconds{suffix}".format(
            secs, sep=sep, prefix=prefix, suffix=suffix
        )
    return now


def humanize_seconds_ago(
    secs: float,
    *,
    prefix: str = "",
    suffix: str = " ago",
    sep: str = "",
    now: str = "just now",
    microseconds: bool = False
) -> str:
    """Show seconds in "3.33 seconds ago" form.

    If seconds are less than one, returns "just now".
    """
    return humanize_seconds(
        secs,
        prefix=prefix,
        suffix=suffix,
        sep=sep,
        now=now,
        microseconds=microseconds,
    )
