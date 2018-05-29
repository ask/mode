"""AsyncIO event loop implementations.

This contains a registry of different AsyncIO loop implementations
to be used with Mode.

The choices available are:

aio **default**
    Normal :mod:`asyncio` event loop policy.

eventlet
    Use :pypi:`eventlet` as the event loop.

    This uses :pypi:`aioeventlet` and will apply the
    :pypi:`eventlet` monkey-patches.

    To enable execute the following as the first thing that happens
    when your program starts (e.g. add it as the top import of your
    entrypoint module)::

        >>> import mode.loop
        >>> mode.loop.use('eventlet')

gevent
    Use :pypi:`gevent` as the event loop.

    This uses :pypi:`aiogevent` (+modifications) and will apply the
    :pypi:`gevent` monkey-patches.

    This choice enables you to run blocking Python code as if they
    have invisible `async/await` syntax around it (NOTE: C extensions are
    not usually gevent compatible).

    To enable execute the following as the first thing that happens
    when your program starts (e.g. add it as the top import of your
    entrypoint module)::

        >>> import mode.loop
        >>> mode.loop.use('gevent')
uvloop
    Event loop using :pypi:`uvloop`.

    To enable execute the following as the first thing that happens
    when your program starts (e.g. add it as the top import of your
    entrypoint module)::

        >>> import mode.loop
        >>> mode.loop.use('uvloop')
"""

import importlib
from typing import Mapping, Optional

__all__ = ['LOOPS', 'use']

LOOPS: Mapping[str, Optional[str]] = {
    'aio': None,
    'eventlet': 'mode.loop.eventlet',
    'gevent': 'mode.loop.gevent',
    'uvloop': 'mode.loop.uvloop',
}


def use(loop: str) -> None:
    mod = LOOPS.get(loop, loop)
    if mod is not None:
        importlib.import_module(mod)
