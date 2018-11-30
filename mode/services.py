"""Async I/O services that can be started/stopped/shutdown."""
import asyncio
import logging
import sys
from functools import wraps
from time import monotonic
from types import TracebackType
from typing import (
    Any,
    Awaitable,
    Callable,
    ClassVar,
    Dict,
    Generator,
    Iterable,
    List,
    Mapping,
    MutableSequence,
    NamedTuple,
    Optional,
    Sequence,
    Set,
    Type,
    Union,
    cast,
)

from .types import DiagT, ServiceT
from .utils.compat import AsyncContextManager, ContextManager
from .utils.contexts import AsyncExitStack, ExitStack
from .utils.locks import Event
from .utils.logging import CompositeLogger, get_logger, level_number
from .utils.objects import iter_mro_reversed
from .utils.text import maybecat
from .utils.times import Seconds, want_seconds
from .utils.trees import Node
from .utils.types.trees import NodeT

__all__ = [
    'ServiceBase',
    'Service',
    'Diag',
    'task',
    'timer',
]

#: Future type: Different types of awaitables.
FutureT = Union[asyncio.Future, Generator[Any, None, Any], Awaitable]

#: Argument type for ``Service.wait(*events)``
#: Wait can take any number of futures or events to wait for.
WaitArgT = Union[FutureT, asyncio.Event, Event]

EVENT_TYPES = (asyncio.Event, Event)


class WaitResults(NamedTuple):
    done: List[WaitArgT]
    results: List[Any]
    stopped: bool


class WaitResult(NamedTuple):
    """Return value of :meth:`Service.wait`."""

    #: Return value of the future we were waiting for.
    result: Any

    #: Set to :const:`True` if the service was stopped while waiting.
    stopped: bool


class ServiceBase(ServiceT):
    """Base class for services."""

    # This class implements stuff common to Service + ServiceProxy

    #: Set to True if this service class is abstract-only,
    #: meaning it will only be used as a base class.
    abstract: ClassVar[bool] = True

    log: CompositeLogger

    #: Logger used by this service.
    #: If not explicitly set this will be based on get_logger(cls.__name__)
    logger: Optional[logging.Logger] = None

    def __init_subclass__(self) -> None:
        if self.abstract:
            self.abstract = False
        self._init_subclass_logger()

    @classmethod
    def _init_subclass_logger(cls) -> None:
        # make sure class has a logger.
        if cls.logger is None or getattr(cls.logger, '__modex__', False):
            cls.logger = get_logger(cls.__module__)
            cls.logger.__modex__ = True  # type: ignore

    def __init__(self, *, loop: asyncio.AbstractEventLoop = None) -> None:
        self.log = CompositeLogger(self.logger, formatter=self._format_log)
        self._loop = loop

    def _format_log(self, severity: int, msg: str,
                    *args: Any, **kwargs: Any) -> str:
        return f'[^{"-" * (self.beacon.depth - 1)}{self.shortlabel}]: {msg}'

    async def __aenter__(self) -> ServiceT:
        await self.start()
        return self

    async def __aexit__(self,
                        exc_type: Type[BaseException] = None,
                        exc_val: BaseException = None,
                        exc_tb: TracebackType = None) -> Optional[bool]:
        try:
            await self.stop()
        finally:
            self.service_reset()
        return None

    def __repr__(self) -> str:
        # Override _repr_info to add additional text to repr.
        info = maybecat(self._repr_info(), prefix=' ') or ''
        return f'<{self._repr_name()}: {self.state}{info}>'

    def _repr_info(self) -> str:
        return ''

    def _repr_name(self) -> str:
        return type(self).__name__

    @property
    def loop(self) -> asyncio.AbstractEventLoop:
        if self._loop is None:
            self._loop = asyncio.get_event_loop()
        return self._loop

    @loop.setter
    def loop(self, loop: Optional[asyncio.AbstractEventLoop]) -> None:
        self._loop = loop


class Diag(DiagT):
    """Service diagnostics.

    This can be used to track what your service is doing.
    For example if your service is a Kafka consumer with a background
    thread that commits the offset every 30 seconds, you may want to
    see when this happens::

        DIAG_COMMITTING = 'committing'

        class Consumer(Service):

            @Service.task
            async def _background_commit(self) -> None:
                while not self.should_stop:
                    await self.sleep(30.0)
                    self.diag.set_flag(DIAG_COMITTING)
                    try:
                        await self._consumer.commit()
                    finally:
                        self.diag.unset_flag(DIAG_COMMITTING)

    The above code is setting the flag manually, but you can also use
    a decorator to accomplish the same thing::

        @Service.timer(30.0)
        async def _background_commit(self) -> None:
            await self.commit()

        @Service.transitions_with(DIAG_COMITTING)
        async def commit(self) -> None:
            await self._consumer.commit()
    """

    def __init__(self, service: ServiceT) -> None:
        self.service = service
        self.flags = set()
        self.last_transition = {}

    def set_flag(self, flag: str) -> None:
        self.flags.add(flag)
        self.last_transition[flag] = monotonic()

    def unset_flag(self, flag: str) -> None:
        self.flags.discard(flag)


class ServiceTask:
    """A background task.

    You don't have to use this class directly, instead
    use the ``@Service.task`` decorator::

        class MyService(Service):

            @Service.task
            def _background_task(self):
                while not self.should_stop:
                    print('Hello')
                    await self.sleep(1.0)
    """

    def __init__(self, fun: Callable[..., Awaitable]) -> None:
        self.fun: Callable[..., Awaitable] = fun

    async def __call__(self, obj: Any) -> Any:
        return await self.fun(obj)

    def __repr__(self) -> str:
        return repr(self.fun)


class ServiceCallbacks:
    """Service callback interface.

    When calling ``await service.start()`` this happens:

    .. sourcecode:: text

        +--------------------+
        | INIT (not started) |
        +--------------------+
                V
        .-----------------------.
        / await service.start() |
        `-----------------------'
                V
        +--------------------+
        | on_first_start     |
        +--------------------+
                V
        +--------------------+
        | on_start           |
        +--------------------+
                V
        +--------------------+
        | on_started         |
        +--------------------+

    When stopping and ``wait_for_shutdown`` is unset, this happens:

    .. sourcecode:: text

        .-----------------------.
        / await service.stop()  |
        `-----------------------'
                V
        +--------------------+
        | on_stop             |
        +--------------------+
                V
        +--------------------+
        | on_shutdown        |
        +--------------------+

    When stopping and ``wait_for_shutdown`` is set, the stop operation
    will wait for something to set the shutdown flag ``self.set_shutdown()``:

    .. sourcecode:: text

        .-----------------------.
        / await service.stop()  |
        `-----------------------'
                V
        +--------------------+
        | on_stop             |
        +--------------------+
                V
        .-------------------------.
        / service.set_shutdown()  |
        `-------------------------'
                V
        +--------------------+
        | on_shutdown        |
        +--------------------+

    When restarting the order is as follows (assuming
    ``wait_for_shutdown`` unset):

    .. sourcecode:: text

        .-------------------------.
        / await service.restart() |
        `-------------------------'
                V
        +--------------------+
        | on_stop             |
        +--------------------+
                V
        +--------------------+
        | on_shutdown        |
        +--------------------+
                V
        +--------------------+
        | on_restart         |
        +--------------------+
                V
        +--------------------+
        | on_start           |
        +--------------------+
                V
        +--------------------+
        | on_started         |
        +--------------------+
    """
    async def on_first_start(self) -> None:
        """Called only the first time the service is started."""
        ...

    async def on_start(self) -> None:
        """Called every time before the service is started/restarted."""
        ...

    async def on_started(self) -> None:
        """Called every time after the service is started/restarted."""
        ...

    async def on_stop(self) -> None:
        """Called every time before the service is stopped/restarted."""
        ...

    async def on_shutdown(self) -> None:
        """Called every time after the service is stopped/restarted"""
        ...

    async def on_restart(self) -> None:
        """Called every time when the service is restarted."""
        ...


class Service(ServiceBase, ServiceCallbacks):
    """An asyncio service that can be started/stopped/restarted.

    Keyword Arguments:
        beacon (NodeT): Beacon used to track services in a graph.
        loop (asyncio.AbstractEventLoop): Event loop object.
    """
    abstract: ClassVar[bool] = True
    Diag: Type[DiagT] = Diag

    #: Set to True if .stop must wait for the shutdown flag to be set.
    wait_for_shutdown = False

    #: Time to wait for shutdown flag set before we give up.
    shutdown_timeout = 60.0

    #: Current number of times this service instance has been restarted.
    restart_count = 0

    #: The log level for mundane info such as `starting`, `stopping`, etc.
    #: Set this to ``"debug"`` for less information.
    mundane_level = 'info'
    _mundane_level: int

    #: Event set when service started.
    _started: Event

    #: Event set when service stopped.
    _stopped: Event

    #: Event set by user to signal service can be shutdown
    #: (see :attr:`wait_for_shutdown)
    _shutdown: Event

    #: Event set when service crashed.
    _crashed: Event

    #: The reason for last crash (an exception instance).
    _crash_reason: Optional[BaseException]

    #: The beacon is used to maintain a graph of services.
    _beacon: NodeT

    #: .add_dependency and friends adds services to this list,
    #: that are started/stopped/restarted with the service.
    _children: MutableSequence[ServiceT]

    #: .add_future adds futures to this list, and when stopping
    #: we will wait for them a bit, then cancel them.
    #: Note: Unlike ``add_dependency`` these futures will not be
    # restarted with the service: if you want that to happen make sure
    # calling service.start() again will add the future again.
    _futures: Set[asyncio.Future]

    #: The ``@Service.task`` decorator adds names of attributes
    #: that are ServiceTasks to this list (which is a class variable).
    _tasks: ClassVar[Optional[Dict[str, Set[str]]]] = None

    @classmethod
    def from_awaitable(cls, coro: Awaitable, *,
                       name: str = None,
                       **kwargs: Any) -> ServiceT:
        return _AwaitableService(coro, name=name)

    @classmethod
    def task(cls, fun: Callable[[Any], Awaitable[None]]) -> ServiceTask:
        """Decorator used to define a service background task.

        Example:
            >>> class S(Service):
            ...
            ...     @Service.task
            ...     async def background_task(self):
            ...         while not self.should_stop:
            ...             await self.sleep(1.0)
            ...             print('Waking up')
        """
        return ServiceTask(fun)

    @classmethod
    def timer(cls, interval: Seconds) -> Callable[
            [Callable[[ServiceT], Awaitable[None]]], ServiceTask]:
        """A background timer that executes every ``n`` seconds.

        Example:
            >>> class S(Service):
            ...
            ...     @Service.timer(1.0)
            ...     async def background_timer(self):
            ...         print('Waking up')
        """
        _interval = want_seconds(interval)

        def _decorate(
                fun: Callable[[ServiceT], Awaitable[None]]) -> ServiceTask:
            @wraps(fun)
            async def _repeater(self: Service) -> None:
                while not self.should_stop:
                    await self.sleep(_interval)
                    await fun(self)
            return cls.task(_repeater)
        return _decorate

    @classmethod
    def transitions_to(cls, flag: str) -> Callable:
        """Decorator that adds diagnostic flag while function is running."""
        def _decorate(
                fun: Callable[..., Awaitable]) -> Callable[..., Awaitable]:
            @wraps(fun)
            async def _and_transition(self: ServiceT,
                                      *args: Any, **kwargs: Any) -> Any:
                self.diag.set_flag(flag)
                try:
                    return await fun(self, *args, **kwargs)
                finally:
                    self.diag.unset_flag(flag)
            return _and_transition
        return _decorate

    def __init_subclass__(self) -> None:
        # Every new subclass adds @Service.task decorated methods
        # to the class-local `_tasks` list.
        if self.abstract:
            self.abstract = False
        self._init_subclass_logger()
        self._init_subclass_tasks()

    @classmethod
    def _init_subclass_tasks(cls) -> None:
        # XXX Python 3.6.3 introduces mysterious bug
        # where the storage for subclasses is always the same,
        # so when we set cls._tasks = [], it will actually clear the
        # tasks for all subclasses.  Hacked around this situation
        # by making _tasks a mapping from classid -> list of tasks,
        # that way all subclasses can share the same attribute.
        clsid = cls._get_class_id()
        if cls._tasks is None:
            cls._tasks = {}
        tasks: Set[str] = set()
        for base in iter_mro_reversed(cls, stop=Service):
            tasks |= {
                attr_name for attr_name, attr_value in vars(base).items()
                if isinstance(attr_value, ServiceTask)
            }
        cls._tasks[clsid] = tasks

    def _get_tasks(self) -> Iterable[ServiceTask]:
        seen: Set[ServiceTask] = set()
        cls = type(self)
        if cls._tasks:
            for attr_name in cls._tasks[cls._get_class_id()]:
                task = getattr(self, attr_name)
                assert isinstance(task, ServiceTask)
                assert task not in seen
                seen.add(task)
                yield task

    @classmethod
    def _get_class_id(cls) -> str:
        return '.'.join([cls.__module__, cls.__qualname__])

    def __init__(self, *,
                 beacon: NodeT = None,
                 loop: asyncio.AbstractEventLoop = None) -> None:
        self.diag = self.Diag(self)
        self._loop = loop
        self._started = self._new_started_event()
        self._stopped = self._new_stopped_event()
        self._shutdown = self._new_shutdown_event()
        self._crashed = self._new_crashed_event()
        self._crash_reason = None
        self._beacon = Node(self) if beacon is None else beacon.new(self)
        self._children = []
        self._futures = set()
        self._mundane_level = level_number(self.mundane_level)
        self.async_exit_stack = AsyncExitStack()
        self.exit_stack = ExitStack()
        self.on_init()
        self.__post_init__()
        super().__init__(loop=self._loop)

    def _new_started_event(self) -> Event:
        return Event(loop=self._loop)

    def _new_stopped_event(self) -> Event:
        return Event(loop=self._loop)

    def _new_shutdown_event(self) -> Event:
        return Event(loop=self._loop)

    def _new_crashed_event(self) -> Event:
        return Event(loop=self._loop)

    async def transition_with(self, flag: str, fut: Awaitable,
                              *args: Any, **kwargs: Any) -> Any:
        self.diag.set_flag(flag)
        try:
            return await fut
        finally:
            self.diag.unset_flag(flag)

    def add_dependency(self, service: ServiceT) -> ServiceT:
        """Add dependency to other service.

        The service will be started/stopped with this service.
        """
        if service.beacon is not None:
            service.beacon.reattach(self.beacon)
        self._children.append(service)
        return service

    async def add_runtime_dependency(self, service: ServiceT) -> ServiceT:
        self.add_dependency(service)
        if self._started.is_set():
            await service.maybe_start()
        return service

    async def add_async_context(self, context: AsyncContextManager) -> Any:
        if isinstance(context, AsyncContextManager):
            return await self.async_exit_stack.enter_async_context(context)
        elif isinstance(context, ContextManager):
            raise TypeError(
                'Use `self.add_context(ctx)` for non-async context')
        raise TypeError(f'Not a context/async context: {type(context)!r}')

    def add_context(self, context: ContextManager) -> Any:
        if isinstance(context, AsyncContextManager):
            raise TypeError(
                'Use `await self.add_async_context(ctx)` for async context')
        elif isinstance(context, ContextManager):
            return self.exit_stack.enter_context(context)
        raise TypeError(f'Not a context/async context: {type(context)!r}')

    def add_future(self, coro: Awaitable) -> asyncio.Future:
        """Add relationship to asyncio.Future.

        The future will be joined when this service is stopped.
        """
        fut = asyncio.ensure_future(self._execute_task(coro), loop=self.loop)
        fut.__wrapped__ = coro  # type: ignore
        fut.add_done_callback(self._on_future_done)
        self._futures.add(fut)
        return fut

    def _on_future_done(self, fut: asyncio.Future) -> None:
        self._futures.discard(fut)

    def __post_init__(self) -> None:
        """Callback to be called on instantiation."""
        ...

    def on_init(self) -> None:
        ...  # deprecated: use __post_init__

    def on_init_dependencies(self) -> Iterable[ServiceT]:
        """Callback to be used to add service dependencies."""
        return []

    async def join_services(self, services: Sequence[ServiceT]) -> None:
        for service in services:
            try:
                await service.maybe_start()
            except BaseException as exc:
                await self.crash(exc)
        for service in reversed(services):
            await service.stop()

    async def sleep(self, n: Seconds) -> None:
        """Sleep for ``n`` seconds, or until service stopped."""
        try:
            await asyncio.wait_for(
                self._stopped.wait(), timeout=want_seconds(n), loop=self.loop)
        except asyncio.TimeoutError:
            pass

    async def wait_for_stopped(self, *coros: WaitArgT,
                               timeout: Seconds = None) -> bool:
        return (await self.wait(*coros, timeout=timeout)).stopped

    async def wait(self, *coros: WaitArgT,
                   timeout: Seconds = None) -> WaitResult:
        """Wait for coroutines to complete, or until the service stops."""
        if coros:
            assert len(coros) == 1
            return await self._wait_one(coros[0], timeout=timeout)
        else:
            await self._wait_stopped(timeout=timeout)
            return WaitResult(None, True)

    async def wait_many(self, coros: Iterable[WaitArgT],
                        *,
                        timeout: Seconds = None) -> WaitResult:
        coro = asyncio.wait(
            cast(Iterable[Awaitable[Any]], coros),
            return_when=asyncio.ALL_COMPLETED,
            timeout=timeout,
            loop=self.loop,
        )
        return await self._wait_one(coro, timeout=timeout)

    async def wait_first(self, *coros: WaitArgT,
                         timeout: Seconds = None) -> WaitResults:
        _coros: Mapping[WaitArgT, FutureT]
        timeout = want_seconds(timeout) if timeout is not None else None
        stopped = self._stopped
        crashed = self._crashed
        loop = self.loop

        # asyncio.wait will also ensure_future, but we need the handle
        # so we can cancel them (if we don't they will leak).
        futures = {
            coro: asyncio.ensure_future(
                (coro.wait() if isinstance(coro, EVENT_TYPES) else coro),
                loop=loop,
            )
            for coro in coros
        }
        futures[stopped] = asyncio.ensure_future(stopped.wait(), loop=loop)
        futures[crashed] = asyncio.ensure_future(crashed.wait(), loop=loop)
        try:
            done, pending = await asyncio.wait(
                futures.values(),
                return_when=asyncio.FIRST_COMPLETED,
                timeout=timeout,
                loop=self.loop,
            )
            for f in done:
                if f.done() and f.exception() is not None:
                    f.result()  # propagate exceptions
            winners: List[WaitArgT] = []
            results: List[Any] = []
            for coro, fut in futures.items():
                if fut.done():
                    winners.append(coro)
                    results.append(fut.result())
                elif fut.cancelled():
                    raise asyncio.CancelledError()
            if winners and not stopped.is_set() and not crashed.is_set():
                return WaitResults(winners, results, False)
            else:
                return WaitResults([], [], True)
        finally:
            # cleanup
            for fut in futures.values():
                if not fut.done():
                    fut.cancel()

    async def _wait_one(self, coro: WaitArgT,
                        *,
                        timeout: Seconds = None) -> WaitResult:
        results = await self.wait_first(coro, timeout=timeout)
        if results.stopped:
            return WaitResult(None, True)
        return WaitResult(results.results[0], False)

    async def _wait_stopped(self, timeout: Seconds = None) -> None:
        timeout = want_seconds(timeout) if timeout is not None else None
        stopped = self._stopped.wait()
        crashed = self._crashed.wait()
        done, pending = await asyncio.wait(
            [stopped, crashed],
            return_when=asyncio.FIRST_COMPLETED,
            timeout=timeout,
            loop=self.loop,
        )
        for fut in done:
            fut.result()  # propagate exceptions
        for fut in pending:
            fut.cancel()
        assert self._crashed.is_set() or self._stopped.is_set()

    async def start(self) -> None:
        await self._default_start()

    async def _default_start(self) -> None:
        loop = self.loop
        assert loop  # make sure loop is set
        assert not self._started.is_set()
        self._started.set()
        await self._actually_start()

    async def _actually_start(self) -> None:
        """Start the service."""
        if not self.restart_count:
            self._children.extend(self.on_init_dependencies())
            await self.on_first_start()
        self.exit_stack.__enter__()
        await self.async_exit_stack.__aenter__()
        try:
            self._log_mundane('Starting...')
            await self.on_start()
            for task in self._get_tasks():
                self.add_future(task.fun(self))
            for child in self._children:
                if child is not None:
                    await child.maybe_start()
            self.log.debug('Started.')
            await self.on_started()
        except BaseException:
            self.exit_stack.__exit__(*sys.exc_info())
            await self.async_exit_stack.__aexit__(*sys.exc_info())
            raise

    async def _execute_task(self, task: Awaitable) -> None:
        try:
            await task
        except asyncio.CancelledError:
            self._log_mundane('Terminating cancelled task: %r', task)
        except RuntimeError as exc:
            if 'Event loop is closed' in str(exc):
                self.log.info('Cancelled task %r: %s', task, exc)
        except BaseException as exc:
            # the exception will be re-raised by the main thread.
            await self.crash(exc)

    async def maybe_start(self) -> None:
        """Start the service, if it has not already been started."""
        if not self._started.is_set():
            await self.start()

    def _log_mundane(self, msg: str, *args: Any, **kwargs: Any) -> None:
        self.log.log(self._mundane_level, msg, *args, **kwargs)

    async def crash(self, reason: BaseException) -> None:
        """Crash the service and all child services."""
        self.log.exception('Crashed reason=%r', reason)
        if not self._crashed.is_set():
            # We record the stack by raising the exception.

            if self.supervisor:
                self.supervisor.wakeup()
            else:
                # if the service has no supervisor we go ahead
                # and mark parent nodes as crashed as well.
                root = self.beacon.root
                seen: Set[NodeT] = set()
                for node in self.beacon.walk():
                    if node in seen:
                        self.log.warn(
                            f'Recursive loop in beacon: {node}: {seen}')
                        if root and root.data is not self:
                            cast(Service, self.beacon.root.data)._crash(reason)
                        break
                    seen.add(node)
                    for child in [node.data] + node.children:
                        if isinstance(child, Service):
                            child._crash(reason)
            self._crash(reason)

    def _crash(self, reason: BaseException) -> None:
        self._crashed.set()
        self._crash_reason = reason
        for node in self._children:
            node._crash(reason)

    async def stop(self) -> None:
        """Stop the service."""
        if not self._stopped.is_set():
            self._log_mundane('Stopping...')
            self._stopped.set()
            await self.on_stop()
            await self._stop_children()
            self.log.debug('Shutting down...')
            if self.wait_for_shutdown:
                self.log.debug('Waiting for shutdown')
                await asyncio.wait_for(
                    self._shutdown.wait(), self.shutdown_timeout,
                )
                self.log.debug('Shutting down now')
            await self._stop_futures()
            await self._stop_exit_stacks()
            await self.on_shutdown()
            self._log_mundane('-Stopped!')

    async def _stop_children(self) -> None:
        await self._default_stop_children()

    async def _default_stop_children(self) -> None:
        for child in reversed(self._children):
            if child is not None:
                await child.stop()

    async def _stop_futures(self) -> None:
        await self._default_stop_futures()

    async def _stop_exit_stacks(self) -> None:
        await self._default_stop_exit_stacks()

    async def _default_stop_exit_stacks(self) -> None:
        self.exit_stack.__exit__(None, None, None)
        await self.async_exit_stack.__aexit__(None, None, None)

    async def _default_stop_futures(self) -> None:
        await self._wait_for_futures(timeout=0)
        for future in self._futures:
            future.cancel()
        await self._gather_futures()

    async def _gather_futures(self, *, timeout: float = None) -> None:
        while self._futures:
            # Gather all futures added via .add_future
            try:
                await self._wait_for_futures(timeout=timeout)
            except asyncio.CancelledError:
                continue
            else:
                break
        self._futures.clear()

    async def _wait_for_futures(self, *, timeout: float = None) -> None:
        if self._futures:
            try:
                await asyncio.shield(asyncio.wait(
                    self._futures,
                    return_when=asyncio.ALL_COMPLETED,
                    loop=self.loop,
                    timeout=timeout,
                ))
            except ValueError:
                if self._futures:
                    raise
                # race condition:
                # _futures non-empty when loop starts,
                # but empty when asyncio.wait receives it.
            except asyncio.CancelledError:
                pass

    async def restart(self) -> None:
        """Restart this service."""
        await self.stop()
        self.service_reset()
        await self.on_restart()
        await self.start()

    def service_reset(self) -> None:
        self.restart_count += 1
        for ev in (self._started,
                   self._stopped,
                   self._shutdown,
                   self._crashed):
            ev.clear()
        self._crash_reason = None
        for child in self._children:
            if child is not None:
                child.service_reset()

    async def wait_until_stopped(self) -> None:
        """Wait until the service is signalled to stop."""
        await self.wait()

    def set_shutdown(self) -> None:
        """Set the shutdown signal.

        Notes:
            If :attr:`wait_for_shutdown` is set, stopping the service
            will wait for this flag to be set.
        """
        self._shutdown.set()

    @property
    def started(self) -> bool:
        """Was the service started?"""
        return bool(self._started.is_set())

    @property
    def crashed(self) -> bool:
        return bool(self._crashed.is_set())

    @property
    def should_stop(self) -> bool:
        """Should the service stop ASAP?"""
        return bool(self._stopped.is_set())

    @property
    def state(self) -> str:
        """Current service state - as a human readable string."""
        if self._crashed.is_set():
            return 'crashed'
        elif not self._started.is_set():
            return 'init'
        elif not self._stopped.is_set():
            return 'running'
        elif not self._shutdown.is_set():
            return 'stopping'
        else:
            return 'shutdown'

    @property
    def label(self) -> str:
        """Label used for graphs."""
        return self._repr_name()

    @property
    def shortlabel(self) -> str:
        """Label used for logging."""
        return self.label

    @property
    def beacon(self) -> NodeT:
        """Beacon used to track services in a dependency graph."""
        return self._beacon

    @beacon.setter
    def beacon(self, beacon: NodeT) -> None:
        self._beacon = beacon


task = Service.task
timer = Service.timer


class _AwaitableService(Service):
    mundane_level = 'debug'

    _fut: Optional[asyncio.Future]

    def __init__(self, coro: Awaitable, *,
                 name: str = None,
                 **kwargs: Any) -> None:
        self.coro = coro
        self._fut = None
        self.name = name
        super().__init__(**kwargs)

    async def on_start(self) -> None:
        # convert to future, so we can cancel on_stop
        self._fut = asyncio.ensure_future(self.coro, loop=self.loop)
        await self._fut

    async def on_stop(self) -> None:
        fut, self._fut = self._fut, None
        if fut is not None:
            if not fut.done():
                fut.cancel()
            else:
                fut.result()

    def _repr_name(self) -> str:
        return self.name or str(self.coro)
