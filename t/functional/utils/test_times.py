import asyncio
from datetime import timedelta
from time import monotonic
import pytest
from mode.utils.times import humanize_seconds, rate_limit, want_seconds


@pytest.mark.parametrize('input,expected', [
    (1.234, 1.234),
    ('1.234', 1.234),
    ('10/s', 10.0),
    ('10/m', 0.16666666666666666),
    ('8.3/m', 0.13833333333333334),
    ('100/h', 0.02777777777777778),
    ('1333/d', 0.01542824074074074),
    (1, 1),
    (timedelta(seconds=1.234), 1.234),
    (None, None),
])
def test_want_seconds(input, expected):
    assert want_seconds(input) == expected


@pytest.mark.asyncio
async def test_rate_limit():
    time_start = monotonic()
    x = 0
    bucket = rate_limit(10, 1.0)
    for _ in range(20):
        async with bucket:
            x += 1
    spent = monotonic() - time_start
    assert spent > 1.0


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


@pytest.mark.parametrize('seconds,expected', [
    (4 * 60 * 60 * 24, '4.00 days'),
    (1 * 60 * 60 * 24, '1.00 day'),
    (4 * 60 * 60, '4.00 hours'),
    (1 * 60 * 60, '1.00 hour'),
    (4 * 60, '4.00 minutes'),
    (1 * 60, '1.00 minute'),
    (4, '4.00 seconds'),
    (1, '1.00 second'),
    (4.3567631221, '4.36 seconds'),
    (0, 'now'),
])
def test_humanize_seconds(seconds, expected):
    assert humanize_seconds(seconds) == expected


def test_humanize_seconds__prefix():
    assert humanize_seconds(4, prefix='about ') == 'about 4.00 seconds'
