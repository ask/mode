import abc
import asyncio
import typing
from weakref import ReferenceType
from typing import (
    Any,
    Awaitable,
    Callable,
    Generic,
    MutableMapping,
    MutableSet,
    Optional,
    Type,
    TypeVar,
    Union,
)
from mypy_extensions import KwArg, NamedArg, VarArg

__all__ = [
    'BaseSignalT',
    'FilterReceiverMapping',
    'SignalHandlerT',
    'SignalHandlerRefT',
    'SignalT',
    'SyncSignalT',
    'T',
    'T_contra',
]

T = TypeVar('T')
T_contra = TypeVar('T_contra', contravariant=True)

SignalHandlerT = Union[
    Callable[
        [T, VarArg(), NamedArg('BaseSignalT', name='signal'), KwArg()],
        None,
    ],
    Callable[
        [T, VarArg(), NamedArg('BaseSignalT', name='signal'), KwArg()],
        Awaitable[None],
    ],
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
    owner: Optional[Type]

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

    @typing.no_type_check
    @abc.abstractmethod
    def clone(self, **kwargs: Any) -> 'SignalT':
        ...

    @typing.no_type_check
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

    @typing.no_type_check
    @abc.abstractmethod
    def clone(self, **kwargs: Any) -> 'SyncSignalT':
        ...

    @typing.no_type_check
    @abc.abstractmethod
    def with_default_sender(self, sender: Any = None) -> 'SyncSignalT':
        ...
