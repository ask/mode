"""Proxy to service.

Works like a service, but delegates to underlying service object.
"""
import abc
from typing import Any, ContextManager, Optional

from .services import ServiceBase
from .types import ServiceT
from .utils.types.trees import NodeT
from .utils.typing import AsyncContextManager

__all__ = ["ServiceProxy"]


class ServiceProxy(ServiceBase):
    """A service proxy delegates ServiceT methods to a composite service.

    Example:
        >>> class MyServiceProxy(ServiceProxy):
        ...
        ...     @cached_property
        ...     def _service(self) -> ServiceT:
        ...         return ActualService()

    Notes:
        This is used by Faust, and probably useful elsewhere!
        The Faust App is created at module-level, and it uses service
        proxy to ensure the event loop is not also created just by importing
        a module.
    """

    @property
    @abc.abstractmethod
    def _service(self) -> ServiceT:  # pragma: no cover
        ...

    def add_dependency(self, service: ServiceT) -> ServiceT:
        return self._service.add_dependency(service)

    async def add_runtime_dependency(self, service: ServiceT) -> ServiceT:
        return await self._service.add_runtime_dependency(service)

    async def add_async_context(self, context: AsyncContextManager) -> Any:
        return await self._service.add_async_context(context)

    def add_context(self, context: ContextManager) -> Any:
        return self._service.add_context(context)

    async def start(self) -> None:
        await self._service.start()

    async def maybe_start(self) -> bool:
        return await self._service.maybe_start()

    async def crash(self, reason: BaseException) -> None:
        await self._service.crash(reason)

    def _crash(self, reason: BaseException) -> None:
        self._service._crash(reason)

    async def stop(self) -> None:
        await self._service.stop()

    def service_reset(self) -> None:
        self._service.service_reset()

    async def restart(self) -> None:
        await self._service.restart()

    async def wait_until_stopped(self) -> None:
        await self._service.wait_until_stopped()

    def set_shutdown(self) -> None:
        self._service.set_shutdown()

    @property
    def started(self) -> bool:
        return self._service.started

    @property
    def crashed(self) -> bool:
        return self._service.crashed

    @property
    def should_stop(self) -> bool:
        return self._service.should_stop

    @property
    def state(self) -> str:
        return self._service.state

    @property
    def label(self) -> str:
        return type(self).__name__

    @property
    def shortlabel(self) -> str:
        return type(self).__name__

    @property
    def beacon(self) -> NodeT:
        return self._service.beacon

    @beacon.setter
    def beacon(self, beacon: NodeT) -> None:
        self._service.beacon = beacon

    @property
    def crash_reason(self) -> Optional[BaseException]:
        return self._service.crash_reason

    @crash_reason.setter
    def crash_reason(self, reason: Optional[BaseException]) -> None:
        self._service.crash_reason = reason
