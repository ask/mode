import abc
import typing
from typing import Any, Awaitable, Callable, Optional, Type
from mode.utils.times import Seconds

if typing.TYPE_CHECKING:
    from .services import ServiceT
else:
    class ServiceT: ...  # noqa: E701

__all__ = ['SupervisorStrategyT']

ReplacementT = Callable[[ServiceT, int], Awaitable[ServiceT]]


class SupervisorStrategyT(ServiceT):
    max_restarts: float
    over: float
    raises: Type[BaseException]

    @abc.abstractmethod
    def __init__(self,
                 *services: ServiceT,
                 max_restarts: Seconds = 100.0,
                 over: Seconds = 1.0,
                 raises: Type[BaseException] = None,
                 replacement: ReplacementT = None,
                 **kwargs: Any) -> None:
        self.replacement: Optional[ReplacementT] = replacement

    @abc.abstractmethod
    def wakeup(self) -> None:
        ...

    @abc.abstractmethod
    def add(self, *services: ServiceT) -> None:
        ...

    @abc.abstractmethod
    def discard(self, *services: ServiceT) -> None:
        ...

    @abc.abstractmethod
    def service_operational(self, service: ServiceT) -> bool:
        ...

    @abc.abstractmethod
    async def restart_service(self, service: ServiceT) -> None:
        ...
