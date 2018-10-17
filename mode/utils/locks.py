# Modern versions of asyncio.locks.

# asyncio primitives call get_event_loop() in __init__,
# which makes them unsuitable for use in programs that don't
# want to pass the loop around.
import asyncio
from collections import deque
from typing import Optional
from .compat import Deque


class Event:
    """Asynchronous equivalent to threading.Event.

    Class implementing event objects. An event manages a flag that can be set
    to true with the set() method and reset to false with the clear() method.
    The wait() method blocks until the flag is true. The flag is initially
    false.
    """
    _waiters: Deque[asyncio.Future]
    _value: bool
    _loop: Optional[asyncio.AbstractEventLoop]

    def __init__(self, *, loop: asyncio.AbstractEventLoop = None) -> None:
        self._waiters = deque()
        self._value = False
        self._loop = loop

    def __repr__(self) -> str:
        res = super().__repr__()
        extra = 'set' if self._value else 'unset'
        if self._waiters:
            extra = f'{extra}, waiters:{len(self._waiters)}'
        return f'<{res[1:-1]} [{extra}]>'

    def is_set(self) -> bool:
        """Return True if and only if the internal flag is true."""
        return self._value

    def set(self):
        """Set the internal flag to true.

        All coroutines waiting for it to become true are awakened.
        Coroutine that call wait() once the flag is true will not block at all.
        """
        if not self._value:
            self._value = True

            for fut in self._waiters:
                if not fut.done():
                    fut.set_result(True)

    def clear(self):
        """Reset the internal flag to false.

        Subsequently, coroutines calling wait() will block until set()
        is called to set the internal flag to true again.
        """
        self._value = False

    async def wait(self):
        """Block until the internal flag is true.

        If the internal flag is true on entry, return True
        immediately.  Otherwise, block until another coroutine calls
        set() to set the flag to true, then return True.
        """
        if self._value:
            return True

        fut = self.loop.create_future()
        self._waiters.append(fut)
        try:
            await fut
            return True
        finally:
            self._waiters.remove(fut)

    @property
    def loop(self) -> asyncio.AbstractEventLoop:
        if self._loop is None:
            self._loop = asyncio.get_event_loop()
        return self._loop
