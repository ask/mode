"""ServiceThread - Service that starts in a separate thread.

Will use the default thread pool executor (``loop.set_default_executor()``),
unless you specify a specific executor instance.

Note: To stop something using the thread's loop, you have to
use the ``on_thread_stop`` callback instead of the on_stop callback.
"""
import asyncio
import sys
import threading
import traceback
from asyncio.locks import Event
from time import monotonic
from typing import (
    Any,
    Awaitable,
    Callable,
    Dict,
    List,
    NamedTuple,
    Optional,
    Tuple,
    Type,
)

from .services import Service
from .utils.futures import maybe_async, maybe_set_exception, maybe_set_result, notify

__all__ = [
    "QueuedMethod",
    "WorkerThread",
    "ServiceThread",
    "QueueServiceThread",
]


class QueuedMethod(NamedTuple):
    """Describe a method to be called by thread."""

    promise: asyncio.Future
    method: Callable[..., Awaitable[Any]]
    args: Tuple[Any, ...]
    kwargs: Dict[str, Any]


class WorkerThread(threading.Thread):
    """Thread class used for services running in a dedicated thread."""

    service: "ServiceThread"
    is_stopped: threading.Event

    def __init__(self, service: "ServiceThread", **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.service = service
        self.daemon = False
        self.is_stopped = threading.Event()

    def run(self) -> None:
        try:
            self.service._start_thread()
        finally:
            self._set_stopped()

    def _set_stopped(self) -> None:
        try:
            self.is_stopped.set()
        except TypeError:  # pragma: no cover
            # we lost the race at interpreter shutdown,
            # so gc collected built-in modules.
            pass

    def stop(self) -> None:
        self.is_stopped.wait()
        if self.is_alive():
            self.join(threading.TIMEOUT_MAX)


class ServiceThread(Service):
    """Service subclass running within a dedicated thread."""

    Worker: Type[WorkerThread] = WorkerThread

    abstract = True
    wait_for_shutdown = True

    #: Set this to False if s.start() should not wait for the
    #: underlying thread to be fully started.
    wait_for_thread: bool = True

    _thread: Optional["WorkerThread"] = None
    _thread_started: Event
    _thread_running: Optional[asyncio.Future] = None

    last_wakeup_at: float = 0.0

    def __init__(
        self,
        *,
        executor: Any = None,
        loop: asyncio.AbstractEventLoop = None,
        thread_loop: asyncio.AbstractEventLoop = None,
        Worker: Type[WorkerThread] = None,
        **kwargs: Any,
    ) -> None:
        # cannot share loop between threads, so create a new one
        if executor is not None:
            raise NotImplementedError("executor argument no longer supported")
        self.parent_loop = loop or asyncio.get_event_loop_policy().get_event_loop()
        self.thread_loop = (
            thread_loop or asyncio.get_event_loop_policy().new_event_loop()
        )
        self._thread_started = Event()
        if Worker is not None:
            self.Worker = Worker
        super().__init__(loop=self.thread_loop, **kwargs)

    async def on_thread_started(self) -> None:
        ...

    async def on_thread_stop(self) -> None:
        ...

    # The deal with asyncio.Event and threads.
    #
    # Every thread needs a dedicated event loop, but events can actually
    # be shared between threads in some ways:
    #
    #   - Any thread can set/check the flag (.set() / .is_set())
    #   - Only the thread owning the loop can wait for the event
    #     to be set (await .wait())

    # So X(Service) adds dependency Y(ServiceThread)

    # We add a new _thread_started event owned by the parent loop.
    #
    # Original ._started event is owned by parent loop
    #
    #    X calls await Y.start(): this starts a thread running Y._start_thread
    #    Y starts the thread, and the thread calls super().start to start
    #    the ServiceThread inside that thread.
    #    After starting the thread will wait for _stopped to be set.

    # ._stopped is owned by thread loop
    #      parent sets _stopped.set(), thread calls _stopped.wait()
    #      and only wait needs the loop.
    # ._shutdown is owned by parent loop
    #      thread calls _shutdown.set(), parent calls _shutdown.wait()

    def _new_shutdown_event(self) -> Event:
        return Event()

    async def maybe_start(self) -> bool:
        if not self._thread_started.is_set():
            await self.start()
            return True
        return False

    async def start(self) -> None:
        assert not self._thread_started.is_set()
        self._thread_started.set()
        self._thread_running = asyncio.Future(loop=self.parent_loop)
        self.add_future(self._keepalive2())
        try:
            self._thread = self.Worker(self)
            self._thread.start()
            if not self.should_stop and self.wait_for_thread:
                # thread exceptions do not propagate to the main thread,
                # so we need some way to communicate socket open errors,
                # such as "port in use", back to the parent thread.
                # The _thread_running future is set to
                # an exception state when that happens, and awaiting will
                # propagate the error to the parent thread.

                # wait for thread to be fully started
                await self._thread_running
        finally:
            self._thread_running = None

    async def _keepalive2(self) -> None:
        while not self.should_stop:
            await self.sleep(1.1)
            if self.last_wakeup_at:
                if monotonic() - self.last_wakeup_at > 3.0:
                    self.log.error("Thread keepalive is not responding...")
            asyncio.run_coroutine_threadsafe(
                self._wakeup_timer_in_thread(), self.thread_loop
            )

    async def _wakeup_timer_in_thread(self) -> None:
        self.last_wakeup_at = monotonic()
        await self.sleep(0)
        asyncio.run_coroutine_threadsafe(asyncio.sleep(0), self.parent_loop)

    async def crash(self, exc: BaseException) -> None:
        # <- .start() will raise
        if asyncio.get_event_loop_policy().get_event_loop() is self.parent_loop:
            maybe_set_exception(self._thread_running, exc)
        else:
            self.parent_loop.call_soon_threadsafe(
                maybe_set_exception, self._thread_running, exc
            )
        await super().crash(exc)

    def _start_thread(self) -> None:
        # set the default event loop for this thread
        asyncio.set_event_loop(self.thread_loop)
        try:
            self.thread_loop.run_until_complete(self._serve())
        except Exception:
            # if self._serve raises an exception we need to set
            # shutdown here, since _shutdown_thread will not execute.
            self.set_shutdown()
            raise

    async def stop(self) -> None:
        if self._started.is_set():
            await super().stop()
            if self._thread is not None:
                self._thread.stop()

    def _stopped_set(self) -> None:
        self.thread_loop.call_soon_threadsafe(self._stopped.set)

    def set_shutdown(self) -> None:
        self.parent_loop.call_soon_threadsafe(self._shutdown.set)

    async def _stop_children(self) -> None:
        ...  # called by thread instead of .stop()

    async def _stop_futures(self) -> None:
        ...  # called by thread instead of .stop()

    async def _stop_exit_stacks(self) -> None:
        ...  # called by thread instead of .stop()

    async def _shutdown_thread(self) -> None:
        await self.on_thread_stop()
        await self._default_stop_children()
        self.set_shutdown()
        await self._default_stop_futures()
        await self._default_stop_exit_stacks()

    async def _serve(self) -> None:
        try:
            # start the service
            await self._default_start()
            # allow ServiceThread.start() to return
            # when wait_for_thread is enabled.
            await self.on_thread_started()
            self.parent_loop.call_soon_threadsafe(notify, self._thread_running)
            await self.wait_until_stopped()
        except asyncio.CancelledError:
            raise
        except BaseException as exc:  # pylint: disable=broad-except
            self.on_crash("{0!r} crashed: {1!r}", self.label, exc)
            await self.crash(exc)
            if self.beacon.root is not None:
                await self.beacon.root.data.crash(exc)
            raise
        finally:
            await self._shutdown_thread()

    @Service.task
    async def _thread_keepalive(self) -> None:
        async for sleep_time in self.itertimer(
            1.0, name=f"_thread_keepalive-{self.label}", loop=self.thread_loop
        ):  # pragma: no cover
            # The consumer thread will have a separate event loop,
            # and so we use this trick to make sure our loop is
            # being scheduled to run something at all times.
            #
            # If we don't do this, anything waiting for new
            # stuff in the method queue may never get it.
            pass

    def on_crash(self, msg: str, *fmt: Any, **kwargs: Any) -> None:
        print(msg.format(*fmt), file=sys.stderr)
        traceback.print_exc(None, sys.stderr)


class MethodQueueWorker(Service):
    index: int
    method_queue: "MethodQueue"
    mundane_level = "debug"

    def __init__(
        self, method_queue: "MethodQueue", *, index: int, **kwargs: Any
    ) -> None:
        self.method_queue = method_queue
        self.index = index
        super().__init__(**kwargs)

    @Service.task
    async def _method_queue_do_work(self) -> None:
        method_queue = self.method_queue
        queue_ready = method_queue._queue_ready
        wait = method_queue.wait
        get = method_queue._queue.get
        process_enqueued = method_queue._process_enqueued
        while not self.should_stop and not method_queue.should_stop:
            await wait(queue_ready)

            if not method_queue.should_stop:
                item = await get()
                await process_enqueued(item)

    @property
    def label(self) -> str:
        return f"{type(self).__name__}@{id(self):#x} index={self.index}"


class MethodQueue(Service):
    Worker: Type[MethodQueueWorker] = MethodQueueWorker

    _queue: asyncio.Queue
    _queue_ready: Event
    _workers: List[MethodQueueWorker]

    mundane_level = "debug"

    def __init__(self, num_workers: int = 2, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._queue = asyncio.Queue()
        self._queue_ready = Event()
        self.num_workers = num_workers
        self._workers = []

    async def on_start(self) -> None:
        self._workers[:] = [
            self.Worker(self, index=i, loop=self.loop, beacon=self.beacon)
            for i in range(self.num_workers)
        ]
        for worker in self._workers:
            await self.add_runtime_dependency(worker)

    async def on_stop(self) -> None:
        await self.flush()
        self._workers[:] = []

    async def call(
        self,
        promise: asyncio.Future,
        fun: Callable[..., Awaitable],
        *args: Any,
        **kwargs: Any,
    ) -> asyncio.Future:
        method = QueuedMethod(promise, fun, args, kwargs)
        self.loop.call_soon_threadsafe(self._queue_put, method)
        return promise

    def _queue_put(self, method: QueuedMethod) -> None:
        self._queue.put_nowait(method)
        self._queue_ready.set()

    async def cast(
        self, fun: Callable[..., Awaitable], *args: Any, **kwargs: Any
    ) -> None:
        promise = self.loop.create_future()
        method = QueuedMethod(promise, fun, args, kwargs)
        self._queue.put_nowait(method)
        self._queue_ready.set()

    async def flush(self) -> None:
        while 1:
            try:
                p = self._queue.get_nowait()
            except asyncio.QueueEmpty:
                break
            else:
                await self._process_enqueued(p)

    async def _process_enqueued(self, p: QueuedMethod) -> asyncio.Future:
        promise, method, args, kwargs = p
        if not promise.cancelled():
            try:
                result = await maybe_async(method(*args, **kwargs))
            except BaseException as exc:
                promise._loop.call_soon_threadsafe(maybe_set_exception, promise, exc)
            else:
                promise._loop.call_soon_threadsafe(maybe_set_result, promise, result)
        return promise

    @property
    def label(self) -> str:
        return f"{type(self).__name__}@{id(self):#x}"


class QueueServiceThread(ServiceThread):
    """Service running in separate thread.

    Uses a queue to run functions inside the thread,
    so you can delegate calls.
    """

    abstract = True

    _method_queue: Optional[MethodQueue] = None

    @property
    def method_queue(self) -> MethodQueue:
        if self._method_queue is None:
            self._method_queue = MethodQueue(
                loop=self.thread_loop,
                beacon=self.beacon,
            )
        return self._method_queue

    async def on_thread_started(self) -> None:
        await self.method_queue.start()

    async def on_thread_stop(self) -> None:
        if self._method_queue is not None:
            await self._method_queue.stop()

    async def call_thread(
        self, fun: Callable[..., Awaitable], *args: Any, **kwargs: Any
    ) -> Any:
        # Enqueue method to be called by thread (synchronous).

        # We pass a future to the thread, so that when the call is done
        # the thread will call `future.set_result(result)`.
        promise = await self.method_queue.call(
            self.parent_loop.create_future(), fun, *args, **kwargs
        )

        # wait for the promise to be fulfilled
        result = await promise
        return result

    async def cast_thread(
        self, fun: Callable[..., Awaitable], *args: Any, **kwargs: Any
    ) -> None:
        # Enqueue method to be called by thread (asynchronous).
        await self.method_queue.cast(fun, *args, **kwargs)
