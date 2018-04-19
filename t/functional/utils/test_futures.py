import asyncio
import pytest
from mode.utils.futures import stampede


class X:
    commit_count = 0

    @stampede
    async def commit(self):
        self.commit_count += 1
        await asyncio.sleep(0.5)
        return self.commit_count


async def call_commit(x):
    return await x.commit()


@pytest.mark.asyncio
async def test_stampede():
    x = X()
    assert all(r == 1 for r in await asyncio.gather(*[
        call_commit(x) for _ in range(100)]))
    assert x.commit_count == 1
    assert all(r == 2 for r in await asyncio.gather(*[
        call_commit(x) for _ in range(100)]))
    assert x.commit_count == 2
    assert await x.commit() == 3
    assert x.commit_count == 3
