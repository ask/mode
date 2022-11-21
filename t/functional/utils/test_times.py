import asyncio
from datetime import timedelta
from time import monotonic

import pytest

from mode.utils.times import (
    TIME_MONOTONIC,
    Bucket,
    TokenBucket,
    humanize_seconds,
    rate,
    rate_limit,
    want_seconds,
)


@pytest.mark.parametrize(
    "input,expected",
    [
        (1.234, 1.234),
        ("1.234", 1.234),
        ("10/s", 10.0),
        ("10/m", 0.16666666666666666),
        ("8.3/m", 0.13833333333333334),
        ("100/h", 0.02777777777777778),
        ("1333/d", 0.01542824074074074),
        (1, 1),
        (timedelta(seconds=1.234), 1.234),
    ],
)
def test_want_seconds(input, expected):
    assert want_seconds(input) == expected


@pytest.mark.parametrize(
    "input,expected",
    [
        (10.1, 10.1),
        ("1/s", 1.0),
        ("10/s", 10.0),
        ("10/m", pytest.approx(0.16666666666666666, 1e-1)),
        ("10/h", pytest.approx(0.0027777777777777775, 1e-1)),
        ("10/d", pytest.approx(0.00011574074074074073, 1e-1)),
        (19, 19.0),
        (None, 0.0),
    ],
)
def test_rate(input, expected):
    assert rate(input) == expected


def test_Bucket():
    bucket = TokenBucket(10, 1.0)
    assert bucket
    Bucket.__post_init__(bucket)
    bucket._last_pour = monotonic() + 100
    assert bucket.tokens


@pytest.mark.asyncio
async def test_rate_limit():
    time_start = TIME_MONOTONIC()
    x = 0
    bucket = rate_limit(10, 1.0)
    for _ in range(20):
        async with bucket:
            x += 1
    spent = TIME_MONOTONIC() - time_start
    assert spent > 0.9


@pytest.mark.asyncio
async def test_pour():
    bucket = rate_limit(10, 1.0, raises=None)
    for _x in range(10):
        assert bucket.pour()
        await asyncio.sleep(0.1)
    assert any(not bucket.pour() for i in range(10))
    assert any(not bucket.pour() for i in range(10))
    assert any(not bucket.pour() for i in range(10))
    await asyncio.sleep(0.4)
    assert bucket.pour()


@pytest.mark.asyncio
async def test_rate_limit_raising():
    bucket = rate_limit(10, 1.0, raises=KeyError)

    for _ in range(10):
        async with bucket:
            await asyncio.sleep(0.1)

    with pytest.raises(KeyError):
        for _ in range(20):
            async with bucket:
                pass


@pytest.mark.parametrize(
    "seconds,microseconds,now,expected",
    [
        (4 * 60 * 60 * 24, False, None, "4.00 days"),
        (1 * 60 * 60 * 24, False, None, "1.00 day"),
        (4 * 60 * 60, False, None, "4.00 hours"),
        (1 * 60 * 60, False, None, "1.00 hour"),
        (4 * 60, False, None, "4.00 minutes"),
        (1 * 60, False, None, "1.00 minute"),
        (4, False, None, "4.00 seconds"),
        (1, False, None, "1.00 second"),
        (4.3567631221, False, None, "4.36 seconds"),
        (4.3567631221, True, None, "4.36 seconds"),
        (0.36, False, None, "now"),
        (0.36, False, "0 seconds", "0 seconds"),
        (0.36, True, None, "0.36 seconds"),
        (0, False, None, "now"),
        (0, False, None, "now"),
        (0, False, "0 seconds", "0 seconds"),
    ],
)
def test_humanize_seconds(seconds, expected, now, microseconds):
    now = now or "now"
    secs = humanize_seconds(seconds, microseconds=microseconds, now=now)
    assert secs == expected


def test_humanize_seconds__prefix():
    assert humanize_seconds(4, prefix="about ") == "about 4.00 seconds"
