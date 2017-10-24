import importlib
from typing import Mapping

__all__ = ['LOOPS', 'use']

LOOPS: Mapping[str, str] = {
    'aio': None,
    'gevent': 'mode.loop.gevent',
    'uvloop': 'mode.loop.uvloop',
}


def use(loop: str) -> None:
    mod = LOOPS.get(loop, loop)
    if mod is not None:
        importlib.import_module(mod)
