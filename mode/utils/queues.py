import asyncio
import typing
from collections import deque
from typing import Any, TypeVar
from weakref import WeakSet
from .compat import Deque
from .locks import Event

_T = TypeVar('_T')


class FlowControlEvent:
    """Manage flow control :class:`FlowControlQueue` instances.

    The FlowControlEvent manages flow in one or many queue instances
    at the same time.

    To flow control queues, first create the shared event::

        >>> flow_control = FlowControlEvent()

    Then pass that shared event to the queues that should be managed by it::

        >>> q1 = FlowControlQueue(maxsize=1, flow_control=flow_control)
        >>> q2 = FlowControlQueue(flow_control=flow_control)

    If you want the contents of the queue to be cleared when flow is resumed,
    then specify that by using the ``clear_on_resume`` flag::

        >>> q3 = FlowControlQueue(clear_on_resume=True,
        ...                       flow_control=flow_control)

    To suspend production into queues, use ``flow_control.suspend``::

        >>> flow_control.suspend()

    While the queues are suspend, any producer attempting to send something
    to the queue will hang until flow is resumed.

    To resume production into queues, use ``flow_control.resume``::

        >>> flow_control.resume()

    Notes:
        In Faust queues are managed by the ``app.flow_control`` event.
    """

    if typing.TYPE_CHECKING:
        _queues: WeakSet['FlowControlQueue']
    _queues = None

    def __init__(self, *,
                 initially_suspended: bool = True,
                 loop: asyncio.AbstractEventLoop = None) -> None:
        self.loop = loop
        self._resume = Event(loop=self.loop)
        self._suspend = Event(loop=self.loop)
        if initially_suspended:
            self._suspend.set()
        self._queues = WeakSet()

    def manage_queue(self, queue: 'FlowControlQueue') -> None:
        """Add :class:`FlowControlQueue` to be cleared on resume."""
        self._queues.add(queue)

    def suspend(self) -> None:
        """Suspend production into queues managed by this event."""
        self._resume.clear()
        self._suspend.set()

    def resume(self) -> None:
        """Resume production into queues managed by this event."""
        self._suspend.clear()
        self._resume.set()
        self.clear()

    def is_active(self) -> bool:
        return not self._suspend.is_set()

    def clear(self) -> None:
        for queue in self._queues:
            queue.clear()

    async def acquire(self) -> None:
        """Wait until flow control is resumed."""
        if self._suspend.is_set():
            await self._resume.wait()


class FlowControlQueue(asyncio.Queue):
    """:class:`asyncio.Queue` managed by :class:`FlowControlEvent`.

    See Also:
        :class:`FlowControlEvent`.
    """

    def __init__(self, maxsize: int = 0,
                 *,
                 flow_control: FlowControlEvent = None,
                 clear_on_resume: bool = False,
                 **kwargs: Any) -> None:
        self._flow_control = flow_control
        self._clear_on_resume = clear_on_resume
        if self._clear_on_resume:
            self._flow_control.manage_queue(self)
        super().__init__(maxsize, **kwargs)

    def clear(self) -> None:
        self._queue.clear()  # type: ignore

    async def put(self, value: _T) -> None:  # type: ignore
        await self._flow_control.acquire()
        await super().put(value)


class ThrowableQueue(FlowControlQueue):

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._errors: Deque[BaseException] = deque()

    @typing.no_type_check
    async def get(self) -> _T:
        if self._errors:
            raise self._errors.popleft()
        return await super().get()

    def empty(self) -> bool:
        return super().empty() and not self._errors

    def clear(self) -> None:
        self._queue.clear()  # type: ignore
        self._errors.clear()
        for putter in self._putters:
            putter.cancel()
        self._putters.clear()

    def get_nowait(self) -> _T:
        if self._errors:
            raise self._errors.popleft()
        return super().get_nowait()

    async def throw(self, exc: BaseException) -> None:
        waiters = self._getters  # type: ignore
        while waiters:
            waiter = waiters.popleft()
            if not waiter.done():
                waiter.set_exception(exc)
                break
        else:
            self._errors.append(exc)
