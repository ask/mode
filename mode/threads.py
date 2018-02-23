"""ServiceThread - Service that starts in a separate thread.

Will use the default thread pool executor (``loop.set_default_executor()``),
unless you specify a specific executor instance.

Note: To stop something using the thread's loop, you have to
use the ``on_thread_stop`` callback instead of the on_stop callback.
"""
import asyncio
import sys
import traceback
from concurrent.futures import Executor
from typing import Any

from .services import Service

__all__ = ['ServiceThread']


class ServiceThread(Service):
    wait_for_shutdown = True

    def __init__(self,
                 *,
                 executor: Executor = None,
                 loop: asyncio.AbstractEventLoop = None,
                 thread_loop: asyncio.AbstractEventLoop = None,
                 **kwargs: Any) -> None:
        # cannot share loop between threads, so create a new one
        assert asyncio.get_event_loop()
        self.executor = executor
        self.parent_loop = loop or asyncio.get_event_loop()
        self.thread_loop = thread_loop or asyncio.new_event_loop()
        self._thread_started = asyncio.Event(loop=self.parent_loop)
        super().__init__(loop=thread_loop, **kwargs)

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
    #    X calls await Y.start(): which schedules the thread to be
    #       started in the loop.default_executor ThreadPool.
    #    Y starts the thread, and the thread calls super().start to start
    #    the ServiceThread inside that thread.
    #    After starting the thread will wait for _stopped to be set.

    # ._stopped is owned by thread loop
    #      parent sets _stopped.set(), thread calls _stopped.wait()
    #      and only wait needs the loop.
    # ._shutdown is owned by parent loop
    #      thread calls _shutdown.set(), thread calls _shutdown.wait()

    def _new_shutdown_event(self) -> asyncio.Event:
        return asyncio.Event(loop=self.parent_loop)

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
        self.add_future(self.loop.run_in_executor(
            self.executor, self._start_thread))

    def _start_thread(self) -> None:
        # set the default event loop for this thread
        asyncio.set_event_loop(self.loop)
        self.loop.run_until_complete(self._serve())

    async def _stop_children(self) -> None:
        ...   # called by thread instead of .stop()

    async def _stop_futures(self) -> None:
        ...   # called by thread instead of .stop()

    async def _shutdown_thread(self) -> None:
        await super()._stop_children()
        await self.on_thread_stop()
        self.set_shutdown()
        await super()._stop_futures()

    async def _serve(self) -> None:
        try:
            await super().start()
            await self.wait_until_stopped()
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
