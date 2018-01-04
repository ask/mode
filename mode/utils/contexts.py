import sys
from collections import deque
from functools import singledispatch
from typing import Any, Awaitable, Callable, Tuple, Union
from .compat import AsyncContextManager, ContextManager, Deque

ContextManagerArg = Union[AsyncContextManager, ContextManager]
PushArg = Union[ContextManagerArg, Callable]


@singledispatch
async def maybe_async(res: Any) -> Any:
    """Await future if argument is Awaitable.

    Examples:
        >>> await maybe_async(regular_function(arg))
        >>> await maybe_async(async_function(arg))
    """
    return res


@maybe_async.register(Awaitable)
async def _(res: Awaitable) -> Any:
    return await res


class AsyncExitStack(AsyncContextManager):
    """Context manager for dynamic management of a stack of exit callbacks.

    Differs from :class:`contextlib.ExitStack` in that it supports
    both :class:`typing.ContextManager` and
    :class:`typing.AsyncContextManager`.

    For example:

        async with AsyncExitStack() as stack:
            files = [await stack.enter_context(open(fname))
                     for fname in filenames]
            # All opened files will automatically be closed at the end of
            # the with statement, even if attempts to open files later
            # in the list raise an exception

    """
    _exit_callbacks: Deque[Callable]

    def __init__(self) -> None:
        self._exit_callbacks = deque()

    def pop_all(self) -> 'AsyncExitStack':
        """Preserve the context stack by transferring it to a new instance"""
        new_stack = type(self)()
        new_stack._exit_callbacks = self._exit_callbacks
        self._exit_callbacks = deque()
        return new_stack

    def _push_cm_exit(self, cm: ContextManager, cm_exit: Callable) -> None:
        """Helper to correctly register callbacks to __exit__ methods"""
        async def _exit_wrapper(*exc_details):
            return cm_exit(cm, *exc_details)
        _exit_wrapper.__self__ = cm
        self.push(_exit_wrapper)

    def _push_async_cm_exit(
            self, cm: AsyncContextManager, cm_exit: Callable) -> None:
        async def _exit_wrapper(*exc_details):
            return await cm_exit(cm, *exc_details)
        _exit_wrapper.__self__ = cm
        self.push(_exit_wrapper)

    def push(self, exit: PushArg) -> PushArg:
        """Registers a callback with the standard __exit__ method signature

        Can suppress exceptions the same way __exit__ methods can.

        Also accepts any object with an __exit__ method (registering a call
        to the method instead of the object itself)
        """
        # We use an unbound method rather than a bound method to follow
        # the standard lookup behaviour for special methods
        _cb_type = type(exit)
        try:
            exit_method = _cb_type.__aexit__
        except AttributeError:
            try:
                exit_method = _cb_type.__exit__
            except AttributeError:
                # Not a context manager, so assume its a callable
                self._exit_callbacks.append(exit)
            else:
                self._push_cm_exit(exit, exit_method)
        else:
            self._push_async_cm_exit(exit, exit_method)
        return exit  # Allow use as a decorator

    def callback(self,
                 callback: Callable,
                 *args: Any, **kwds: Any) -> Callable:
        """Registers an arbitrary callback and arguments.

        Cannot suppress exceptions.
        """
        async def _exit_wrapper(exc_type, exc, tb):
            await maybe_async(callback(*args, **kwds))
        # We changed the signature, so using @wraps is not appropriate, but
        # setting __wrapped__ may still help with introspection
        _exit_wrapper.__wrapped__ = callback
        self.push(_exit_wrapper)
        return callback  # Allow use as a decorator

    async def enter_context(self, cm: ContextManagerArg) -> Any:
        """Enters the supplied context manager

        If successful, also pushes its __exit__ method as a callback and
        returns the result of the __enter__ method.
        """
        # We look up the special methods on the type to match
        # the with statement
        _cm_type = type(cm)
        try:
            _exit = _cm_type.__aexit__
        except AttributeError:
            _exit = _cm_type.__exit__
            result = _cm_type.__enter__(cm)
            self._push_cm_exit(cm, _exit)
        else:
            result = await _cm_type.__aenter__(cm)
            self._push_async_cm_exit(cm, _exit)
        return result

    async def close(self) -> None:
        """Immediately unwind the context stack"""
        await self.__aexit__(None, None, None)

    async def __aenter__(self) -> 'AsyncExitStack':
        return self

    async def __aexit__(self, *exc_details: Tuple) -> Any:
        received_exc = exc_details[0] is not None

        # We manipulate the exception state so it behaves as though
        # we were actually nesting multiple with statements
        frame_exc = sys.exc_info()[1]

        def _fix_exception_context(new_exc, old_exc):
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
            cb = self._exit_callbacks.pop()
            try:
                if await maybe_async(cb(*exc_details)):
                    suppressed_exc = True
                    pending_raise = False
                    exc_details = (None, None, None)
            except BaseException:
                new_exc_details = sys.exc_info()
                # simulate the stack of exceptions by setting the context
                _fix_exception_context(new_exc_details[1], exc_details[1])
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
