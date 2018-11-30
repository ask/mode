import asyncio
from typing import Any, Callable

__all__ = ['clone_loop', 'call_asap']


def _is_unix_loop(loop: asyncio.AbstractEventLoop) -> bool:
    try:
        from asyncio import unix_events
    except ImportError:
        return False
    else:
        return isinstance(loop, unix_events._UnixSelectorEventLoop)


def clone_loop(loop: asyncio.AbstractEventLoop) -> asyncio.AbstractEventLoop:
    new_loop = asyncio.new_event_loop()
    if _is_unix_loop(loop):
        for signum, handle in loop._signal_handlers.items():
            new_loop.add_signal_handler(
                signum, _appropriate_signal_handler(loop, handle))
    return new_loop


def _appropriate_signal_handler(
        parent_loop: asyncio.AbstractEventLoop,
        handle: asyncio.Handle) -> Callable:
    callback = handle._callback
    context = getattr(handle, '_context', None)  # CPython 3.7+
    callback_args = handle._args

    def _call_using_parent_loop() -> None:
        _call_asap(parent_loop, callback, *callback_args, context=context)
    return _call_using_parent_loop


def call_asap(callback: Callable,
              *args: Any,
              context: Any = None,
              loop: asyncio.AbstractEventLoop = None) -> asyncio.Handle:
    assert loop
    if _is_unix_loop(loop):
        return _call_asap(loop, callback, *args, context=context)
    if context is not None:
        return loop.call_soon_threadsafe(callback, *args, context=context)
    return loop.call_soon_threadsafe(callback, *args)


def _call_asap(loop: Any,
               callback: Callable,
               *args: Any,
               context: Any = None) -> asyncio.Handle:
    loop._check_closed()
    if loop._debug:
        loop._check_callback(callback, 'call_soon_threadsafe')
    handle = loop._call_soon(callback, args, context)
    if context is not None:
        handle = asyncio.Handle(callback, args, loop, context)
    else:
        handle = asyncio.Handle(callback, args, loop)
    if handle._source_traceback:
        del handle._source_traceback[-1]

    loop._ready.insert(0, handle)

    if handle._source_traceback:
        del handle._source_traceback[-1]
    loop._write_to_self()
    return handle
