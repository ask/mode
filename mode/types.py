import abc
import asyncio
import typing
from typing import (
    Any, Awaitable, Callable, Generic,
    MutableMapping, MutableSet, Set, Type, TypeVar, Union, no_type_check,
)
from weakref import ReferenceType

from .utils.compat import AsyncContextManager, ContextManager
from .utils.contexts import AsyncExitStack, ExitStack
from .utils.times import Seconds
from .utils.types.trees import NodeT

__all__ = [
    'FilterReceiverMapping',
    'SignalHandlerT',
    'SignalHandlerRefT',
    'SignalT',
    'DiagT',
    'ServiceT',
    'T',
    'T_contra',
]

T = TypeVar('T')
T_contra = TypeVar('T_contra', contravariant=True)

SignalHandlerT = Union[
    Callable[..., None],
    Callable[..., Awaitable[None]],
]

if typing.TYPE_CHECKING:
    SignalHandlerRefT = Union[
        Callable[[], SignalHandlerT],
        ReferenceType[SignalHandlerT]]
else:
    SignalHandlerRefT = Any

FilterReceiverMapping = MutableMapping[Any, MutableSet[SignalHandlerRefT]]


class BaseSignalT(Generic[T]):
    name: str
    owner: Type

    @abc.abstractmethod
    def __init__(self, *,
                 name: str = None,
                 owner: Type = None,
                 loop: asyncio.AbstractEventLoop = None,
                 default_sender: Any = None,
                 receivers: MutableSet[SignalHandlerRefT] = None,
                 filter_receivers: FilterReceiverMapping = None) -> None:
        ...

    @abc.abstractmethod
    def clone(self, **kwargs: Any) -> 'BaseSignalT':
        ...

    @abc.abstractmethod
    def with_default_sender(self, sender: Any = None) -> 'BaseSignalT':
        ...

    @abc.abstractmethod
    def connect(self, fun: SignalHandlerT, **kwargs: Any) -> Callable:
        ...

    @abc.abstractmethod
    def disconnect(self, fun: SignalHandlerT,
                   *,
                   sender: Any = None,
                   weak: bool = True) -> None:
        ...


class SignalT(BaseSignalT[T]):

    @abc.abstractmethod
    async def __call__(self, sender: T_contra,
                       *args: Any, **kwargs: Any) -> None:
        ...

    @abc.abstractmethod
    async def send(self, sender: T_contra, *args: Any, **kwargs: Any) -> None:
        ...

    @no_type_check
    @abc.abstractmethod
    def clone(self, **kwargs: Any) -> 'SignalT':
        ...

    @no_type_check
    @abc.abstractmethod
    def with_default_sender(self, sender: Any = None) -> 'SignalT':
        ...


class SyncSignalT(BaseSignalT[T]):

    @abc.abstractmethod
    def __call__(self, sender: T_contra, *args: Any, **kwargs: Any) -> None:
        ...

    @abc.abstractmethod
    def send(self, sender: T_contra, *args: Any, **kwargs: Any) -> None:
        ...

    @no_type_check
    @abc.abstractmethod
    def clone(self, **kwargs: Any) -> 'SyncSignalT':
        ...

    @no_type_check
    @abc.abstractmethod
    def with_default_sender(self, sender: Any = None) -> 'SyncSignalT':
        ...


class DiagT(abc.ABC):
    """Diag keeps track of a services diagnostic flags."""
    flags: Set[str]
    last_transition: MutableMapping[str, float]

    @abc.abstractmethod
    def __init__(self, service: 'ServiceT') -> None:
        ...

    @abc.abstractmethod
    def set_flag(self, flag: str) -> None:
        ...

    @abc.abstractmethod
    def unset_flag(self, flag: str) -> None:
        ...


class ServiceT(AsyncContextManager):
    """Abstract type for an asynchronous service that can be started/stopped.

    See Also:
        :class:`mode.Service`.
    """

    Diag: Type[DiagT]
    diag: DiagT
    async_exit_stack: AsyncExitStack
    exit_stack: ExitStack

    shutdown_timeout: float
    wait_for_shutdown = False
    loop: asyncio.AbstractEventLoop = None
    restart_count: int = 0
    supervisor: 'SupervisorStrategyT' = None

    @abc.abstractmethod
    def __init__(self, *,
                 beacon: NodeT = None,
                 loop: asyncio.AbstractEventLoop = None) -> None:
        ...

    @abc.abstractmethod
    def add_dependency(self, service: 'ServiceT') -> 'ServiceT':
        ...

    @abc.abstractmethod
    async def add_runtime_dependency(self, service: 'ServiceT') -> 'ServiceT':
        ...

    @abc.abstractmethod
    async def add_context(
            self, context: Union[AsyncContextManager, ContextManager]) -> Any:
        ...

    @abc.abstractmethod
    async def start(self) -> None:
        ...

    @abc.abstractmethod
    async def maybe_start(self) -> None:
        ...

    @abc.abstractmethod
    async def crash(self, reason: BaseException) -> None:
        ...

    @abc.abstractmethod
    async def stop(self) -> None:
        ...

    @abc.abstractmethod
    async def restart(self) -> None:
        ...

    @abc.abstractmethod
    async def wait_until_stopped(self) -> None:
        ...

    @abc.abstractmethod
    def set_shutdown(self) -> None:
        ...

    @abc.abstractmethod
    def _repr_info(self) -> str:
        ...

    @property
    @abc.abstractmethod
    def started(self) -> bool:
        ...

    @property
    @abc.abstractmethod
    def crashed(self) -> bool:
        ...

    @property
    @abc.abstractmethod
    def should_stop(self) -> bool:
        ...

    @property
    @abc.abstractmethod
    def state(self) -> str:
        ...

    @property
    @abc.abstractmethod
    def label(self) -> str:
        ...

    @property
    @abc.abstractmethod
    def shortlabel(self) -> str:
        ...

    @property
    def beacon(self) -> NodeT:
        ...

    @beacon.setter
    def beacon(self, beacon: NodeT) -> None:
        ...


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
                 replacement: Callable[[ServiceT, int],
                                       Awaitable[ServiceT]] = None,
                 **kwargs: Any) -> None:
        self.replacement: Callable[[ServiceT, int], Awaitable[ServiceT]]

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
