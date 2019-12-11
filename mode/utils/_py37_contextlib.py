"""Backport implementation of Python 3.7 contextlib."""
import abc
import sys
import types
import _collections_abc
from collections import deque
from contextlib import AbstractContextManager
from functools import wraps
from typing import (
    Any,
    Awaitable,
    Callable,
    ContextManager,
    Dict,
    Optional,
    Tuple,
    Type,
    Union,
    cast,
)
from .typing import AsyncContextManager, Deque

__all__ = [
    'AbstractAsyncContextManager',
    'AsyncExitStack',
    'ExitStack',
    'asynccontextmanager',
    'nullcontext',
]

AsyncCallable = Callable[..., Awaitable]
PushArg = Union[ContextManager, Callable]
AsyncPushArg = Union[AsyncContextManager, AsyncCallable]


class AbstractAsyncContextManager(abc.ABC):
    """An abstract base class for asynchronous context managers."""

    async def __aenter__(self) -> 'AbstractAsyncContextManager':
        """Return `self` upon entering the runtime context."""
        return self

    @abc.abstractmethod
    async def __aexit__(self,
                        exc_type: Type[BaseException],
                        exc_value: BaseException,
                        traceback: types.TracebackType) -> None:
        """Raise any exception triggered within the runtime context."""
        return None

    @classmethod
    def __subclasshook__(cls, C: Type) -> bool:
        if cls is AbstractAsyncContextManager:
            return cast(bool, _collections_abc._check_methods(
                C, '__aenter__', '__aexit__'))
        return cast(bool, NotImplemented)


class _AsyncGeneratorContextManager(AbstractAsyncContextManager):
    """Helper for :func:`asynccontextmanager`."""

    # this __init__ is taken from contextlib._GeneratorContextManagerBase
    # in CPython3.7.

    def __init__(self, func: Callable, args: Tuple, kwds: Dict) -> None:
        self.gen = func(*args, **kwds)
        self.func, self.args, self.kwds = func, args, kwds
        # Issue 19330: ensure context manager instances have good docstrings
        doc = getattr(func, '__doc__', None)
        if doc is None:
            doc = type(self).__doc__
        self.__doc__ = doc
        # Unfortunately, this still doesn't provide good help output when
        # inspecting the created context manager instances, since pydoc
        # currently bypasses the instance docstring and shows the docstring
        # for the class instead.
        # See http://bugs.python.org/issue19404 for more details.

    # rest of class is from contextlib._AsyncGeneratorContextManager

    async def __aenter__(self) -> Any:
        try:
            return await self.gen.__anext__()
        except StopAsyncIteration:
            raise RuntimeError("generator didn't yield") from None

    async def __aexit__(self,
                        typ: Optional[Type[BaseException]],
                        value: Optional[BaseException],
                        traceback: Optional[types.TracebackType]) -> None:
        if typ is None:
            try:
                await self.gen.__anext__()
            except StopAsyncIteration:
                return
            else:
                raise RuntimeError("generator didn't stop")
        else:
            if value is None:
                value = typ()
            # See _GeneratorContextManager.__exit__ for comments on subtleties
            # in this implementation
            try:
                await self.gen.athrow(typ, value, traceback)
                raise RuntimeError("generator didn't stop after throw()")
            except StopAsyncIteration as exc:
                return exc is not value  # type: ignore
            except RuntimeError as exc:
                if exc is value:
                    return False  # type: ignore
                # Avoid suppressing if a StopIteration exception
                # was passed to throw() and later wrapped into a RuntimeError
                # (see PEP 479 for sync generators; async generators also
                # have this behavior). But do this only if the exception
                # wrapped by the RuntimeError is actully Stop(Async)Iteration
                # (see issue29692).
                if isinstance(value, (StopIteration, StopAsyncIteration)):
                    if exc.__cause__ is value:
                        return False  # type: ignore
                raise
            except BaseException as exc:
                if exc is not value:
                    raise


def asynccontextmanager(func: Callable) -> Callable[..., AsyncContextManager]:
    """None."""
    @wraps(func)
    def helper(*args: Any, **kwds: Any) -> _AsyncGeneratorContextManager:
        return _AsyncGeneratorContextManager(func, args, kwds)
    return helper


class _BaseExitStack:
    """A base class for ExitStack and AsyncExitStack."""

    _exit_callbacks: Deque[Tuple[bool, Callable]]

    @staticmethod
    def _create_exit_wrapper(cm: ContextManager,
                             cm_exit: Callable) -> Callable:
        def _exit_wrapper(exc_type: Type,
                          exc: BaseException,
                          tb: types.TracebackType) -> Any:
            return cm_exit(cm, exc_type, exc, tb)
        return _exit_wrapper

    @staticmethod
    def _create_cb_wrapper(callback: Callable,
                           *args: Any, **kwds: Any) -> Callable:
        def _exit_wrapper(exc_type: Type,
                          exc: BaseException,
                          tb: types.TracebackType) -> None:
            callback(*args, **kwds)
        return _exit_wrapper

    def __init__(self) -> None:
        self._exit_callbacks = deque()

    def pop_all(self) -> '_BaseExitStack':
        """Preserve the context stack by transferring it to a new instance."""
        new_stack = type(self)()
        new_stack._exit_callbacks = self._exit_callbacks
        self._exit_callbacks = deque()
        return new_stack

    def push(self, exit: PushArg) -> PushArg:
        """Register a callback with the standard __exit__ method signature.

        Can suppress exceptions the same way __exit__ method can.
        Also accepts any object with an __exit__ method (registering a call
        to the method instead of the object itself).
        """
        # We use an unbound method rather than a bound method to follow
        # the standard lookup behaviour for special methods.
        _cb_type = type(exit)

        try:
            exit_method = _cb_type.__exit__  # type: ignore
        except AttributeError:
            # Not a context manager, so assume it's a callable.
            self._push_exit_callback(exit)  # type: ignore
        else:
            self._push_cm_exit(exit, exit_method)  # type: ignore
        return exit  # Allow use as a decorator.

    def enter_context(self, cm: ContextManager) -> Any:
        """Enters the supplied context manager.

        If successful, also pushes its __exit__ method as a callback and
        returns the result of the __enter__ method.
        """
        # We look up the special methods on the type to match the with
        # statement.
        _cm_type = type(cm)
        _exit = _cm_type.__exit__
        result = _cm_type.__enter__(cm)
        self._push_cm_exit(cm, _exit)
        return result

    def callback(self, callback: Callable,
                 *args: Any, **kwds: Any) -> Callable:
        """Register an arbitrary callback and arguments.

        Cannot suppress exceptions.
        """
        _exit_wrapper = self._create_cb_wrapper(callback, *args, **kwds)

        # We changed the signature, so using @wraps is not appropriate, but
        # setting __wrapped__ may still help with introspection.
        _exit_wrapper.__wrapped__ = callback  # type: ignore
        self._push_exit_callback(_exit_wrapper)
        return callback  # Allow use as a decorator

    def _push_cm_exit(self, cm: ContextManager, cm_exit: Callable) -> None:
        # Helper to correctly register callbacks to __exit__ methods.
        _exit_wrapper = self._create_exit_wrapper(cm, cm_exit)
        _exit_wrapper.__self__ = cm  # type: ignore
        self._push_exit_callback(_exit_wrapper, True)

    def _push_exit_callback(self, callback: Callable,
                            is_sync: bool = True) -> None:
        self._exit_callbacks.append((is_sync, callback))


# Inspired by discussions on http://bugs.python.org/issue13585
class ExitStack(_BaseExitStack, AbstractContextManager):
    """Context manager for dynamic management of a stack of exit callbacks.

    For example:
        with ExitStack() as stack:
            files = [stack.enter_context(open(fname)) for fname in filenames]
            # All opened files will automatically be closed at the end of
            # the with statement, even if attempts to open files later
            # in the list raise an exception.
    """

    def __enter__(self) -> 'ExitStack':
        return self

    def __exit__(self, *exc_details: Any) -> None:
        received_exc = exc_details[0] is not None

        # We manipulate the exception state so it behaves as though
        # we were actually nesting multiple with statements
        frame_exc = sys.exc_info()[1]

        def _fix_exception_context(new_exc: BaseException,
                                   old_exc: BaseException) -> None:
            # Context may not be correct, so find the end of the chain
            while 1:
                exc_context = new_exc.__context__
                if exc_context is old_exc:
                    # Context is already set correctly (see issue 20317)
                    return
                if exc_context is None or exc_context is frame_exc:
                    break
                new_exc = exc_context
            # Change the end of the chain to point to the exception
            # we expect it to reference
            new_exc.__context__ = old_exc

        # Callbacks are invoked in LIFO order to match the behaviour of
        # nested context managers
        suppressed_exc = False
        pending_raise = False
        while self._exit_callbacks:
            is_sync, cb = self._exit_callbacks.pop()
            assert is_sync
            try:
                if cb(*exc_details):
                    suppressed_exc = True
                    pending_raise = False
                    exc_details = (None, None, None)
            except:  # noqa
                new_exc_details = sys.exc_info()
                # simulate the stack of exceptions by setting the context
                _fix_exception_context(
                    new_exc_details[1],  # type: ignore
                    exc_details[1])
                pending_raise = True
                exc_details = new_exc_details
        if pending_raise:
            try:
                # bare "raise exc_details[1]" replaces our carefully
                # set-up context
                fixed_ctx = exc_details[1].__context__
                raise exc_details[1]
            except BaseException:
                exc_details[1].__context__ = fixed_ctx
                raise
        return received_exc and suppressed_exc  # type: ignore

    def close(self) -> None:
        """Immediately unwind the context stack."""
        self.__exit__(None, None, None)


# Inspired by discussions on https://bugs.python.org/issue29302
class AsyncExitStack(_BaseExitStack, AbstractAsyncContextManager):
    """Async :class:`ExitStack`.

    Context manager for dynamic management of a stack of exit callbacks.

    Example:
            >>> async with AsyncExitStack() as stack:
            ...    connections = [
            ...        await stack.enter_async_context(get_connection())
            ...        for i in range(5)
            ...    ]
            >>>    # All opened connections will automatically be released at
            >>>    # the end of the async with statement, even if attempts to
            >>>    # open a connection later in the list raise an exception.
    """

    @staticmethod
    def _create_async_exit_wrapper(
            cm: AsyncContextManager, cm_exit: AsyncCallable) -> AsyncCallable:
        async def _exit_wrapper(exc_type: Type,
                                exc: BaseException,
                                tb: types.TracebackType) -> Any:
            return await cm_exit(cm, exc_type, exc, tb)
        return _exit_wrapper

    @staticmethod
    def _create_async_cb_wrapper(
            callback: AsyncCallable, *args: Any, **kwds: Any) -> AsyncCallable:
        async def _exit_wrapper(exc_type: Type,
                                exc: BaseException,
                                tb: types.TracebackType) -> None:
            await callback(*args, **kwds)
        return _exit_wrapper

    async def enter_async_context(self, cm: AsyncContextManager) -> Any:
        """Enters the supplied async context manager.

        If successful, also pushes its __aexit__ method as a callback and
        returns the result of the __aenter__ method.
        """
        _cm_type = type(cm)
        _exit = _cm_type.__aexit__
        result = await _cm_type.__aenter__(cm)
        self._push_async_cm_exit(cm, _exit)
        return result

    def push_async_exit(self, exit: AsyncPushArg) -> AsyncPushArg:
        """Register coroutine with the standard __aexit__ method signature.

        Can suppress exceptions the same way __aexit__ method can.
        Also accepts any object with an __aexit__ method (registering a call
        to the method instead of the object itself).
        """
        _cb_type = type(exit)
        try:
            exit_method = _cb_type.__aexit__  # type: ignore
        except AttributeError:
            # Not an async context manager, so assume it's a coroutine function
            self._push_exit_callback(exit, False)  # type: ignore
        else:
            self._push_async_cm_exit(exit, exit_method)  # type: ignore
        return exit  # Allow use as a decorator

    def push_async_callback(self, callback: AsyncCallable,
                            *args: Any, **kwds: Any) -> AsyncCallable:
        """Register an arbitrary coroutine function and arguments.

        Cannot suppress exceptions.
        """
        _exit_wrapper = self._create_async_cb_wrapper(callback, *args, **kwds)

        # We changed the signature, so using @wraps is not appropriate, but
        # setting __wrapped__ may still help with introspection.
        _exit_wrapper.__wrapped__ = callback  # type: ignore
        self._push_exit_callback(_exit_wrapper, False)
        return callback  # Allow use as a decorator

    async def aclose(self) -> None:
        """Immediately unwind the context stack."""
        await self.__aexit__(None, None, None)

    def _push_async_cm_exit(
            self, cm: AsyncContextManager, cm_exit: Callable) -> None:
        # Helper to correctly register coroutine function to __aexit__
        # method.
        _exit_wrapper = self._create_async_exit_wrapper(cm, cm_exit)
        _exit_wrapper.__self__ = cm  # type: ignore
        self._push_exit_callback(_exit_wrapper, False)

    async def __aenter__(self) -> 'AsyncExitStack':
        return self

    async def __aexit__(self, *exc_details: Any) -> Any:
        received_exc = exc_details[0] is not None

        # We manipulate the exception state so it behaves as though
        # we were actually nesting multiple with statements
        frame_exc = sys.exc_info()[1]

        def _fix_exception_context(
                new_exc: BaseException, old_exc: BaseException) -> None:
            # Context may not be correct, so find the end of the chain
            while 1:
                exc_context = new_exc.__context__
                if exc_context is old_exc:
                    # Context is already set correctly (see issue 20317)
                    return
                if exc_context is None or exc_context is frame_exc:
                    break
                new_exc = exc_context
            # Change the end of the chain to point to the exception
            # we expect it to reference
            new_exc.__context__ = old_exc

        # Callbacks are invoked in LIFO order to match the behaviour of
        # nested context managers
        suppressed_exc = False
        pending_raise = False
        while self._exit_callbacks:
            is_sync, cb = self._exit_callbacks.pop()
            try:
                if is_sync:
                    cb_suppress = cb(*exc_details)
                else:
                    cb_suppress = await cb(*exc_details)

                if cb_suppress:
                    suppressed_exc = True
                    pending_raise = False
                    exc_details = (None, None, None)
            except:  # noqa
                new_exc_details = sys.exc_info()
                # simulate the stack of exceptions by setting the context
                _fix_exception_context(
                    new_exc_details[1],  # type: ignore
                    exc_details[1])
                pending_raise = True
                exc_details = new_exc_details
        if pending_raise:
            try:
                # bare "raise exc_details[1]" replaces our carefully
                # set-up context
                fixed_ctx = exc_details[1].__context__
                raise exc_details[1]
            except BaseException:
                exc_details[1].__context__ = fixed_ctx
                raise
        return received_exc and suppressed_exc


class nullcontext(AbstractContextManager):
    """Context manager that does no additional processing.

    Used as a stand-in for a normal context manager, when a particular
    block of code is only sometimes used with a normal context manager:

    cm = optional_cm if condition else nullcontext()
    with cm:
        # Perform operation, using optional_cm if condition is True
    """

    def __init__(self, enter_result: Any = None) -> None:
        self.enter_result: Any = enter_result

    def __enter__(self) -> Any:
        return self.enter_result

    def __exit__(self,
                 exc_type: Optional[Type[BaseException]],
                 exc: Optional[BaseException],
                 tb: Optional[types.TracebackType]) -> None:
        pass
