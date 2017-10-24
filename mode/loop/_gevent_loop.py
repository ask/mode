import asyncio
from typing import Any
import gevent.core


class Loop(gevent.core.loop):
    _aioloop_loop = None

    def run_callback(self, *args: Any, **kwargs: Any) -> None:
        if self._aioloop_loop is None:
            self._aioloop_loop = asyncio.get_event_loop()
        gevent.spawn_later(0.0, self._aioloop_loop._run_once)  # type: ignore
        super().run_callback(*args, **kwargs)
