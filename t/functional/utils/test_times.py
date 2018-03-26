from datetime import timedelta
from time import monotonic
import pytest
from mode.utils.times import rate_limit, want_seconds


@pytest.mark.parametrize('input,expected', [
    (1.234, 1.234),
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
    for _ in range(20):
        async with rate_limit(10, 1.0):
            x += 1
    spent = monotonic() - time_start
    assert spent > 1.8
