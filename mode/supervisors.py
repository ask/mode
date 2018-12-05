"""Supervisors.

Naming here is taken from Erlang ;-)

Don't know supervisors? Read about them them here:
http://learnyousomeerlang.com/supervisors

"""
import asyncio
from typing import Any, Awaitable, Callable, Dict, List, Optional, Type, cast

from .exceptions import MaxRestartsExceeded
from .services import Service
from .types import ServiceT, SupervisorStrategyT
from .utils.futures import notify
from .utils.logging import get_logger
from .utils.times import Bucket, Seconds, rate_limit, want_seconds

__all__ = [
    'ForfeitOneForAllSupervisor',
    'ForfeitOneForOneSupervisor',
    'SupervisorStrategy',
    'OneForOneSupervisor',
    'OneForAllSupervisor',
]

logger = get_logger(__name__)


class SupervisorStrategy(Service, SupervisorStrategyT):
    # set this future to wakeup supervisor
    _please_wakeup: Optional[asyncio.Future]

    #: the services we manage
    _services: List[ServiceT]

    # rate limit state
    _bucket: Bucket

    # what index is service at?
    # if we have 10 services for example, and one of the crash,
    #  we want to know the position of the service we are restarting.
    # This is needed for Faust and the @app.agent(concurrency=n) feature.
    _index: Dict[ServiceT, int]

    def __init__(self,
                 *services: ServiceT,
                 max_restarts: Seconds = 100.0,
                 over: Seconds = 1.0,
                 raises: Type[BaseException] = MaxRestartsExceeded,
                 replacement: Callable[[ServiceT, int],
                                       Awaitable[ServiceT]] = None,
                 **kwargs: Any) -> None:
        self.max_restarts = want_seconds(max_restarts)
        self.over = want_seconds(over)
        self.raises = raises
        self._bucket = rate_limit(self.max_restarts, self.over, raises=raises)
        self._services = list(services or [])
        self.replacement = replacement
        self._please_wakeup = None
        self._index = {}
        super().__init__(**kwargs)

    def wakeup(self) -> None:
        notify(self._please_wakeup)

    def add(self, *services: ServiceT) -> None:
        # XXX not thread-safe, but shouldn't have to be.
        size = len(self._services)
        for i, service in enumerate(services):
            if size:
                pos = size + i
            else:
                pos = i
            self._index[service] = pos
            assert service.supervisor is None
            self._contribute_to_service(service)
        self._services.extend(services)

    def _contribute_to_service(self, service: ServiceT) -> None:
        # A "poisonpill" is the default behavior for any service
        # with no supervisor attribute set.
        #
        # Setting the service.supervisor attribute here means calling
        # `await service.crash(exc)` won't traverse the tree, crash
        # every parent of the service, until it hits Worker terminating
        # the running program abruptly.  See :class:`CrashingSupervisor`.
        service.supervisor = self

    def discard(self, *services: ServiceT) -> None:
        for service in services:
            self._index.pop(service, None)
            try:
                self._services.remove(service)
            except ValueError:
                pass

    def insert(self, index: int, service: ServiceT) -> None:
        old_service, self._services[index] = self._services[index], service
        service.supervisor = self
        self._index.pop(old_service, None)
        self._index[service] = index

    def service_operational(self, service: ServiceT) -> bool:
        return not service.crashed

    async def run_until_complete(self) -> None:
        await self.start()
        await self.stop()

    @Service.task
    async def _supervisor(self) -> None:
        services = self._services

        while not self.should_stop:
            # other coroutines may set this future to wake us up using
            # notify(self._please_wakeup)
            self._please_wakeup = asyncio.Future(loop=self.loop)
            try:
                # we'll also timeout after five seconds,
                # just in case nobody wakes us up.
                await asyncio.wait_for(self._please_wakeup, timeout=5.0)
            except asyncio.TimeoutError:
                pass
            finally:
                self._please_wakeup = None
            if not self.should_stop:
                to_start: List[ServiceT] = []
                to_restart: List[ServiceT] = []
                for service in services:
                    if service.started:
                        if not self.service_operational(service):
                            to_restart.append(service)
                    else:
                        to_start.append(service)

                await self.start_services(to_start)
                await self.restart_services(to_restart)

    async def on_start(self) -> None:
        await self.start_services(self._services)

    async def on_stop(self) -> None:
        for service in self._services:
            if service.started:
                try:
                    await service.stop()
                except MemoryError:
                    raise
                except Exception as exc:
                    self.log.exception(
                        'Unable to stop service %r: %r', service, exc)

    async def start_services(self, services: List[ServiceT]) -> None:
        for service in services:
            await self.start_service(service)

    async def start_service(self, service: ServiceT) -> None:
        await service.maybe_start()

    async def restart_services(self, services: List[ServiceT]) -> None:
        for service in services:
            await self.restart_service(service)

    async def stop_services(self, services: List[ServiceT]) -> None:
        # Stop them all simultaneously.
        await asyncio.gather(
            *[service.stop() for service in services],
            loop=self.loop,
        )

    async def restart_service(self, service: ServiceT) -> None:
        self.log.info('Restarting dead %r! Last crash reason: %r',
                      service, cast(Service, service)._crash_reason,
                      exc_info=1)
        try:
            async with self._bucket:
                if self.replacement:
                    index = self._index[service]
                    new_service = await self.replacement(service, index)
                    new_service.supervisor = self
                    self.insert(index, new_service)
                else:
                    await service.restart()
        except MaxRestartsExceeded as exc:
            self.log.warn('Max restarts exceeded: %r', exc, exc_info=1)


class OneForOneSupervisor(SupervisorStrategy):
    ...


class OneForAllSupervisor(SupervisorStrategy):

    async def restart_services(self, services: List[ServiceT]) -> None:
        # we ignore the list of actual crashed services,
        # and restart all of them
        if services:
            # Stop them all, and wait for all of them to stop (concurrently).
            await self.stop_services(self._services)
            # Then restart them one by one.
            for service in self._services:
                await self.restart_service(service)


class ForfeitOneForOneSupervisor(SupervisorStrategy):
    """Supervisor that if a service crashes, we do not restart it."""

    async def restart_services(self, services: List[ServiceT]) -> None:
        if services:
            self.log.critical('Giving up on crashed services: %r', services)
            await self.stop_services(services)


class ForfeitOneForAllSupervisor(SupervisorStrategy):
    """If one service in the group crashes, we give up on all of them."""

    async def restart_services(self, services: List[ServiceT]) -> None:
        if services:
            self.log.critical(
                'Giving up on all services in group because %r crashed',
                services,
            )
            await self.stop_services(self._services)


class CrashingSupervisor(SupervisorStrategy):

    def _contribute_to_service(self, service: ServiceT) -> None:
        # The service.crash() method will wakeup service.supervisor if it has
        # one, but if it does not have one the exception will propagate.
        # Doing nothing here, means service.supervisor will not be set.
        #
        # A crashing supervisor will propagate by reraising the exception.
        #   - if that means the process exits:
        #       the operating system supervisor will have to take over
        #       (systemd/supervisord/etc.)
        #   - if the exception is handled by another supervisor
        #       that supervisor decides what to do with it.
        pass

    def wakeup(self) -> None:
        self._stopped.set()
        super().wakeup()
