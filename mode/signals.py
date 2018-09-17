import asyncio
from collections import defaultdict
from functools import partial
from types import MethodType
from typing import (
    Any,
    Callable,
    Iterable,
    Mapping,
    MutableSet,
    Optional,
    Set,
    Tuple,
    Type,
    cast,
    no_type_check,
)
from weakref import ReferenceType, WeakMethod, ref

from .types.signals import (
    BaseSignalT,
    FilterReceiverMapping,
    SignalHandlerRefT,
    SignalHandlerT,
    SignalT,
    SyncSignalT,
    T,
    T_contra,
)
from .utils.futures import maybe_async

__all__ = ['BaseSignal', 'Signal', 'SyncSignal']


class BaseSignal(BaseSignalT[T]):
    _receivers: MutableSet[SignalHandlerRefT]
    _filter_receivers: FilterReceiverMapping

    def __init__(self, *,
                 name: str = None,
                 owner: Type = None,
                 loop: asyncio.AbstractEventLoop = None,
                 default_sender: Any = None,
                 receivers: MutableSet[SignalHandlerRefT] = None,
                 filter_receivers: FilterReceiverMapping = None) -> None:
        self.name = name or ''
        self.owner = owner
        self.loop = loop
        self.default_sender = default_sender
        self._receivers = receivers if receivers is not None else set()
        if filter_receivers is None:
            filter_receivers = defaultdict(set)
        self._filter_receivers = filter_receivers

    def asdict(self) -> Mapping[str, Any]:
        return {
            'name': self.name,
            'owner': self.owner,
            'loop': self.loop,
            'default_sender': self.default_sender,
        }

    def clone(self, **kwargs: Any) -> BaseSignalT:
        return self._clone(**kwargs)

    def with_default_sender(self, sender: Any = None) -> BaseSignalT:
        return self._with_default_sender(sender)

    def _clone(self, **kwargs: Any) -> BaseSignalT:
        return type(self)(**{**self.asdict(), **kwargs})

    def _with_default_sender(self, sender: Any = None) -> BaseSignalT:
        if sender is None:
            sender = self.default_sender
        return self.clone(
            default_sender=sender,
            receivers=self._receivers,
            filter_receivers=self._filter_receivers,
        )

    def __set_name__(self, owner: Type, name: str) -> None:
        # If signal is an attribute of a class, we use __set_name__
        # to show the location of the signal in __repr__.
        # E.g.::
        #    >>> class X(Service):
        #    ...   starting = Signal()
        #
        #    >>> X.starting
        #    <Signal: X.starting>
        if self.name is None:
            self.name = name
        if self.owner is None:
            self.owner = owner

    def unpack_sender_from_args(self, *args: Any) -> Tuple[T, Tuple[Any, ...]]:
        sender = self.default_sender
        if sender is None:
            if not args:
                raise TypeError('Signal.send requires at least one argument')
            if len(args) > 1:
                sender, *args = args  # type: ignore
            else:
                sender, args = args[0], ()
        return sender, args

    def connect(self, fun: SignalHandlerT = None, **kwargs: Any) -> Callable:
        if fun is not None:
            return self._connect(fun, **kwargs)
        return partial(self._connect(cast(SignalHandlerT, fun)))

    def _connect(self, fun: SignalHandlerT,
                 *,
                 weak: bool = True,
                 sender: Any = None) -> SignalHandlerT:
            ref: SignalHandlerRefT
            ref = self._create_ref(fun) if weak else lambda: fun
            if self.default_sender is not None:
                sender = self.default_sender
            if sender is None:
                self._receivers.add(ref)
            else:
                self._filter_receivers[self._create_id(sender)].add(ref)
            return fun

    def disconnect(self, fun: SignalHandlerT,
                   *,
                   weak: bool = True,
                   sender: Any = None) -> None:
        ref: SignalHandlerRefT = self._create_ref(fun) if weak else lambda: fun
        if self.default_sender is not None:
            sender = self.default_sender
        if sender is None:
            self._receivers.discard(ref)
        else:
            try:
                self._filter_receivers[self._create_id(sender)].remove(ref)
            except ValueError:
                pass

    def iter_receivers(self, sender: T_contra) -> Iterable[SignalHandlerT]:
        if self._receivers or self._filter_receivers:
            r = self._update_receivers(self._receivers)
            if sender is not None:
                sender_id = self._create_id(sender)
                r.update(self._update_receivers(
                    self._filter_receivers[sender_id]))
            for receiver in r:
                yield receiver

    def _update_receivers(
            self, r: MutableSet[SignalHandlerRefT]) -> Set[SignalHandlerT]:
        live_receivers, dead_refs = self._get_live_receivers(r)
        for href in dead_refs:
            r.discard(href)
        return live_receivers

    def _get_live_receivers(
            self, r: MutableSet[SignalHandlerRefT]) -> Tuple[
                Set[SignalHandlerT], Set[SignalHandlerRefT]]:
        live_receivers: Set[SignalHandlerT] = set()
        dead_refs: Set[SignalHandlerRefT] = set()
        for href in r:
            alive, value = self._is_alive(href)
            if alive and value is not None:
                live_receivers.add(value)
            else:
                dead_refs.add(href)
        return live_receivers, dead_refs

    def _is_alive(
            self,
            ref: SignalHandlerRefT) -> Tuple[bool, Optional[SignalHandlerT]]:
        if isinstance(ref, ReferenceType):
            value = ref()
            return value is not None, value
        return True, ref()

    def _create_ref(self, fun: SignalHandlerT) -> SignalHandlerRefT:
        if hasattr(fun, '__func__') and hasattr(fun, '__self__'):
            return cast(SignalHandlerRefT, WeakMethod(cast(MethodType, fun)))
        else:
            return ref(fun)

    def _create_id(self, sender: Any) -> int:
        try:
            return hash((sender.__func__, sender.__self__))
        except AttributeError:
            return hash(sender)

    @property
    def ident(self) -> str:
        if self.owner:
            return f'{self.owner.__qualname__}.{self.name}'
        return self.name

    def __repr__(self) -> str:
        info = ''
        if self.default_sender:
            info = f' sender={self.default_sender!r}'
        return f'<{type(self).__name__}: {self.ident}{info}>'


class Signal(BaseSignal[T], SignalT[T]):

    async def __call__(self, sender: T_contra = None,
                       *args: Any, **kwargs: Any) -> None:
        await self.send(sender, *args, **kwargs)

    async def send(self, *args: Any, **kwargs: Any) -> None:
        sender, args = self.unpack_sender_from_args(*args)
        for receiver in self.iter_receivers(sender):
            await maybe_async(receiver(sender, *args, signal=self, **kwargs))

    @no_type_check
    def clone(self, **kwargs: Any) -> SignalT:
        return cast(Signal, self._clone(**kwargs))

    @no_type_check
    def with_default_sender(self, sender: Any = None) -> SignalT:
        return cast(Signal, self._with_default_sender(sender))


class SyncSignal(BaseSignal[T], SyncSignalT[T]):

    def __call__(self, sender: T_contra = None,
                 *args: Any, **kwargs: Any) -> None:
        self.send(sender, *args, **kwargs)

    def send(self, *args: Any, **kwargs: Any) -> None:
        sender, args = self.unpack_sender_from_args(*args)
        for receiver in self.iter_receivers(sender):
            receiver(sender, *args, signal=self, **kwargs)

    @no_type_check
    def clone(self, **kwargs: Any) -> SyncSignalT:
        return cast(SyncSignal, self._clone(**kwargs))

    @no_type_check
    def with_default_sender(self, sender: Any = None) -> SyncSignalT:
        return cast(SyncSignal, self._with_default_sender(sender))
