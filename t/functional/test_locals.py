import asyncio
import pytest
import time
import threading
from mode.locals import LocalStack


class Request:
    id: int

    def __init__(self, id: int) -> None:
        self.id = id

    def __repr__(self) -> str:
        return f'<{type(self).__name__}: id={self.id!r}>'


def test_typing():
    assert LocalStack[Request]


async def foo(stack, first_req):
    current = stack.top
    assert current is first_req
    new_req = Request(2)
    try:
        with stack.push(new_req):
            assert stack.top is new_req
            await asyncio.sleep(0.01)
            return await bar(stack, new_req)
            time.sleep(0.1)
    finally:
        assert stack.top is current


async def bar(stack, prev_req):
    current = stack.top
    assert current is prev_req
    new_req = Request(3)
    time.sleep(0.01)
    try:
        with stack.push(new_req):
            await asyncio.sleep(0.1)
            assert stack.top is new_req
            return await baz(stack, new_req)
    finally:
        assert stack.top is current
        time.sleep(0.09)


async def baz(stack, prev_req):
    current = stack.top
    assert current is prev_req
    new_req = Request(4)
    try:
        with stack.push(new_req):
            assert stack.top is new_req
            await asyncio.sleep(0.3)
            return 42
    finally:
        assert stack.top is current


@pytest.mark.asyncio
async def test_coroutines():
    stack = LocalStack()
    await assert_stack(stack)


async def assert_stack(stack):
    first_req = Request(1)
    assert stack.top is None
    with stack.push(first_req):
        assert stack.top is first_req
        assert await foo(stack, first_req) == 42
    assert stack.top is None


@pytest.mark.asyncio
@pytest.mark.parametrize('retry', range(3))
async def test_threads(retry):
    stack = LocalStack()

    def thread_enter():
        loop = asyncio.new_event_loop()
        for _ in range(2):
            loop.run_until_complete(assert_stack(stack))

    threads = [
        threading.Thread(target=thread_enter, daemon=False)
        for _ in range(10)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(threading.TIMEOUT_MAX)
