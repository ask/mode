"""Async I/O services that can be started/stopped/shutdown."""
import asyncio
import logging
import sys
from functools import wraps
from time import monotonic
from types import TracebackType
from typing import (
    Any, Awaitable, Callable, ClassVar, Dict, Generator, Iterable, List,
    MutableSequence, NamedTuple, Optional, Sequence, Set, Type, Union, cast,
)

from .types import DiagT, ServiceT
from .utils.compat import AsyncContextManager, ContextManager
from .utils.contexts import AsyncExitStack, ExitStack
from .utils.logging import CompositeLogger, get_logger
from .utils.objects import iter_mro_reversed
from .utils.text import maybecat
from .utils.times import Seconds, want_seconds
from .utils.trees import Node
from .utils.types.trees import NodeT

__all__ = [
    'ServiceBase',
    'Service',
    'Diag',
]

FutureT = Union[asyncio.Future, Generator[Any, None, Any], Awaitable]

WaitArgT = Union[FutureT, asyncio.Event]


class WaitResult(NamedTuple):
    result: Any
    stopped: bool


class ServiceBase(ServiceT):
    """Base class for services."""

    abstract: ClassVar[bool] = True

    log: CompositeLogger

    #: Logger used by this service.
    #: IF not explicitly set this will be based on get_logger(cls.__name__)
    logger: logging.Logger = None

    def __init_subclass__(self) -> None:
        if self.abstract:
            self.abstract = False
        self._init_subclass_logger()

    @classmethod
    def _init_subclass_logger(cls) -> None:
        if cls.logger is None or getattr(cls.logger, '__modex__', False):
            cls.logger = get_logger(cls.__module__)
            cls.logger.__modex__ = True

    # This contains the common methods for Service and ServiceProxy

    def __init__(self) -> None:
        self.log = CompositeLogger(self)

    def _format_log(self, severity: int, msg: str,
                    *args: Any, **kwargs: Any) -> str:
        return f'[^{"-" * (self.beacon.depth - 1)}{self.shortlabel}]: {msg}'

    def _log(self, severity: int, msg: str, *args: Any, **kwargs: Any) -> None:
        self.logger.log(severity, msg, *args, **kwargs)

    async def __aenter__(self) -> ServiceT:
        await self.start()
        return self

    async def __aexit__(self,
                        exc_type: Type[BaseException] = None,
                        exc_val: BaseException = None,
                        exc_tb: TracebackType = None) -> Optional[bool]:
        await self.stop()
        return None

    def __repr__(self) -> str:
        return '<{name}: {self.state}{info}>'.format(
            name=type(self).__name__,
            self=self,
            info=maybecat(self._repr_info(), prefix=' ') or '',
        )

    def _repr_info(self) -> str:
        return ''


class Diag(DiagT):

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

    def __init__(self, fun: Callable[..., Awaitable]) -> None:
        self.fun: Callable[..., Awaitable] = fun

    async def __call__(self, obj: Any) -> Any:
        return await self.fun(obj)

    def __repr__(self) -> str:
        return repr(self.fun)


class ServiceCallbacks:

    async def on_first_start(self) -> None:
        """Callback to be called the first time the service is started."""
        ...

    async def on_start(self) -> None:
        """Callback to be called every time the service is started."""
        ...

    async def on_started(self) -> None:
        """Callback to be called once the service is started/restarted."""
        ...

    async def on_stop(self) -> None:
        """Callback to be called when the service is signalled to stop."""
        ...

    async def on_shutdown(self) -> None:
        """Callback to be called when the service is shut down."""
        ...

    async def on_restart(self) -> None:
        """Callback to be called when the service is restarted."""
        ...


class Service(ServiceBase, ServiceCallbacks):
    """An asyncio service that can be started/stopped/restarted.

    Notes:
        Instantiating a service will create the asyncio event loop.
        If your object is created as a side effect of importing a module,
        then you should use :class:`mode.proxy.ServiceProxy`.

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

    _started: asyncio.Event
    _stopped: asyncio.Event
    _shutdown: asyncio.Event
    _crashed: asyncio.Event
    _crash_reason: BaseException

    #: The beacon is used to track the graph of services.
    _beacon: NodeT

    #: .add_dependency adds subservices to this list.
    #: They are started/stopped with the service.
    _children: MutableSequence[ServiceT]

    #: .add_future adds futures to this list
    #: They are started/stopped with the service.
    _futures: List[asyncio.Future]

    #: The ``@Service.task`` decorator adds names of attributes
    #: that are ServiceTasks to this list (which is a class variable).
    _tasks: ClassVar[Dict[str, Set[str]]] = None

    @classmethod
    def task(cls, fun: Callable[[Any], Awaitable[None]]) -> ServiceTask:
        """Decorator used to define a service background task.

        Example:
            >>> class S(Service):
            ...
            ... @Service.task
            ... async def background_task(self):
            ...     while not self.should_stop:
            ...         print('Waking up')
            ...         await self.sleep(1.0)
        """
        return ServiceTask(fun)

    @classmethod
    def timer(cls, interval: Seconds) -> Callable[
            [Callable[[ServiceT], Awaitable[None]]], ServiceTask]:
        _interval = want_seconds(interval)

        def _decorate(
                fun: Callable[[ServiceT], Awaitable[None]]) -> ServiceTask:
            @wraps(fun)
            async def _repeater(self: ServiceT) -> None:
                while not self.should_stop:
                    await self.sleep(_interval)
                    await fun(self)
            return cls.task(_repeater)
        return _decorate

    @classmethod
    def transitions_to(cls, flag: str) -> Callable:
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
        self.loop = loop or asyncio.get_event_loop()
        self._started = self._new_started_event()
        self._stopped = self._new_stopped_event()
        self._shutdown = self._new_shutdown_event()
        self._crashed = self._new_crashed_event()
        self._crash_reason = None
        self._beacon = Node(self) if beacon is None else beacon.new(self)
        self._children = []
        self._futures = []
        self.async_exit_stack = AsyncExitStack()
        self.exit_stack = ExitStack()
        self.on_init()
        super().__init__()

    def _new_started_event(self) -> asyncio.Event:
        return asyncio.Event(loop=self.loop)

    def _new_stopped_event(self) -> asyncio.Event:
        return asyncio.Event(loop=self.loop)

    def _new_shutdown_event(self) -> asyncio.Event:
        return asyncio.Event(loop=self.loop)

    def _new_crashed_event(self) -> asyncio.Event:
        return asyncio.Event(loop=self.loop)

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

    async def add_context(
            self, context: Union[AsyncContextManager, ContextManager]) -> Any:
        if isinstance(context, AsyncContextManager):
            await self.async_exit_stack.enter_async_context(context)
        elif isinstance(context, ContextManager):
            return self.exit_stack.enter_context(context)
        raise TypeError(f'Not a context/async context: {type(context)!r}')

    def add_future(self, coro: Awaitable) -> asyncio.Future:
        """Add relationship to asyncio.Future.

        The future will be joined when this service is stopped.
        """
        fut = asyncio.ensure_future(self._execute_task(coro), loop=self.loop)
        self._futures.append(fut)
        return fut

    def on_init(self) -> None:
        """Callback to be called on instantiation."""
        ...

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
        except (asyncio.CancelledError, asyncio.TimeoutError):
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

    async def _wait_one(self, coro: WaitArgT,
                        *,
                        timeout: Seconds = None) -> WaitResult:
        fut: FutureT
        timeout = want_seconds(timeout) if timeout is not None else None
        stopped = self._stopped.wait()
        crashed = self._crashed.wait()

        fut = coro.wait() if isinstance(coro, asyncio.Event) else coro
        fut = asyncio.ensure_future(fut, loop=self.loop)
        try:
            done, pending = await asyncio.wait(
                (fut, stopped, crashed),
                return_when=asyncio.FIRST_COMPLETED,
                timeout=timeout,
                loop=self.loop,
            )
            for f in done:
                f.result()  # propagate exceptions
            for f in pending:
                f.cancel()
            if fut.done():
                return WaitResult(fut.result(), False)
            else:
                assert self._crashed.is_set() or self._stopped.is_set()
                return WaitResult(None, True)
        finally:
            if not fut.done():
                fut.cancel()

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
        """Start the service."""
        assert not self._started.is_set()
        self._started.set()
        if not self.restart_count:
            self._children.extend(self.on_init_dependencies())
            await self.on_first_start()
        self.exit_stack.__enter__()
        await self.async_exit_stack.__aenter__()
        try:
            self.log.info('Starting...')
            await self.on_start()
            for task in self._get_tasks():
                self.add_future(task(self))
            for child in self._children:
                if child is not None:
                    await child.maybe_start()
            self.log.debug('Started.')
            await self.on_started()
        except BaseException as exc:
            self.exit_stack.__exit__(*sys.exc_info())
            await self.async_exit_stack.__aexit__(*sys.exc_info())
            raise

    async def _execute_task(self, task: Awaitable) -> None:
        try:
            await task
        except asyncio.CancelledError:
            self.log.debug('Terminating cancelled task: %r', task)
        except RuntimeError as exc:
            if 'Event loop is closed' in str(exc):
                self.log.info('Cancelled task %r: %s', task, exc)
        except BaseException as exc:
            # the exception will be reraised by the main thread.
            await self.crash(exc)

    async def maybe_start(self) -> None:
        """Start the service, if it has not already been started."""
        if not self._started.is_set():
            await self.start()

    async def crash(self, reason: BaseException) -> None:
        """Crash the service and all child services."""
        if not self._crashed.is_set():
            # We record the stack by raising the exception.
            self.log.exception('Crashed reason=%r', reason)

            if not self.supervisor:
                # Only if the service has no supervisor do we go ahead
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

    async def stop(self) -> None:
        """Stop the service."""
        if not self._stopped.is_set():
            self.log.info('Stopping...')
            self._stopped.set()
            await self.on_stop()
            await self._stop_children()
            self.log.debug('Shutting down...')
            if self.wait_for_shutdown:
                self.log.debug('Waiting for shutdown')
                await asyncio.wait_for(
                    self._shutdown.wait(), self.shutdown_timeout,
                    loop=self.loop,
                )
                self.log.debug('Shutting down now')
            await self._stop_futures()
            self.exit_stack.__exit__(None, None, None)
            await self.async_exit_stack.__aexit__(None, None, None)
            await self.on_shutdown()
            self.log.info('-Stopped!')

    async def _stop_children(self) -> None:
        for child in reversed(self._children):
            if child is not None:
                await child.stop()

    async def _stop_futures(self) -> None:
        for future in reversed(self._futures):
            future.cancel()
        await self._gather_futures()

    async def _gather_futures(self) -> None:
        while self._futures:
            # Gather all futures added via .add_future
            try:
                await asyncio.shield(asyncio.wait(
                    self._futures,
                    return_when=asyncio.ALL_COMPLETED,
                    loop=self.loop,
                ))
            except asyncio.CancelledError:
                continue
            else:
                break
        self._futures.clear()

    async def restart(self) -> None:
        """Restart this service."""
        self.restart_count += 1
        await self.stop()
        for ev in (self._started,
                   self._stopped,
                   self._shutdown,
                   self._crashed):
            ev.clear()
        self._crash_reason = None
        await self.on_restart()
        await self.start()

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
        return self._started.is_set()

    @property
    def crashed(self) -> bool:
        return self._crashed.is_set()

    @property
    def should_stop(self) -> bool:
        """Should the service stop ASAP?"""
        return self._stopped.is_set()

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
        return type(self).__name__

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


__flake8_Set_is_used: Set  # XXX flake8 bug
