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
from concurrent.futures import Executor
from typing import Any, Optional

from .services import Service
from .utils.locks import Event
from .utils.loops import clone_loop

__all__ = ['ServiceThread']


class WorkerThread(threading.Thread):
    service: 'ServiceThread'
    _is_stopped: threading.Event

    def __init__(self, service: 'ServiceThread', **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.service = service
        self.daemon = False
        self._is_stopped = threading.Event()

    def run(self) -> None:
        try:
            self.service._start_thread()
        finally:
            self._set_stopped()

    def _set_stopped(self) -> None:
        try:
            self._is_stopped.set()
        except TypeError:  # pragma: no cover
            # we lost the race at interpreter shutdown,
            # so gc collected built-in modules.
            pass

    def stop(self) -> None:
        self._is_stopped.wait()
        if self.is_alive():
            self.join(threading.TIMEOUT_MAX)


class ServiceThread(Service):
    wait_for_shutdown = True

    _thread: Optional[WorkerThread] = None

    def __init__(self,
                 *,
                 executor: Executor = None,
                 loop: asyncio.AbstractEventLoop = None,
                 thread_loop: asyncio.AbstractEventLoop = None,
                 **kwargs: Any) -> None:
        # cannot share loop between threads, so create a new one
        assert asyncio.get_event_loop()
        if executor is not None:
            raise NotImplementedError('executor is no longer supported')
        self.parent_loop = loop or asyncio.get_event_loop()
        self.thread_loop = thread_loop or clone_loop(self.parent_loop)
        self._thread_started = Event(loop=self.parent_loop)
        super().__init__(loop=self.thread_loop, **kwargs)
        assert self._shutdown.loop is self.parent_loop

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
        return Event(loop=self.parent_loop)


    async def maybe_start(self) -> None:
        if not self._thread_started.is_set():
            await self.start()

    async def start(self) -> None:
        # cannot await the future returned by run_in_executor,
        # as that would make us wait until the webserver exits.
        # Instead we add as Future dependency to this service, so that
        # it is stopped with `await service.stop()`
        assert not self._thread_started.is_set()
        self._thread_started.set()
        self._thread = WorkerThread(self)
        self._thread.start()

    def _start_thread(self) -> None:
        # set the default event loop for this thread
        asyncio.set_event_loop(self.thread_loop)
        self.thread_loop.run_until_complete(self._serve())

    async def _stop_children(self) -> None:
        ...   # called by thread instead of .stop()

    async def _stop_futures(self) -> None:
        ...   # called by thread instead of .stop()

    async def _shutdown_thread(self) -> None:
        await self._default_stop_children()
        await self.on_thread_stop()
        self.set_shutdown()
        await self._default_stop_futures()
        if self._thread is not None:
            self._thread.stop()

    async def _serve(self) -> None:
        try:
            await self._default_start()  # start the service
            await self.wait_until_stopped()
        except asyncio.CancelledError:
            raise
        except BaseException as exc:  # pylint: disable=broad-except
            self.on_crash('{0!r} crashed: {1!r}', self.label, exc)
            await self.crash(exc)
            if self.beacon.root is not None:
                await self.beacon.root.data.crash(exc)
            raise
        finally:
            await self._shutdown_thread()

    def on_crash(self, msg: str, *fmt: Any, **kwargs: Any) -> None:
        print(msg.format(*fmt), file=sys.stderr)
        traceback.print_exc(None, sys.stderr)
