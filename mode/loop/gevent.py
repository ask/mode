import os
os.environ['GEVENT_LOOP'] = 'mode.loop._gevent_loop.Loop'
try:
    import gevent
    import gevent.core
    import gevent.monkey
except ImportError:
    raise ImportError(
        'Gevent loop requires the gevent library: '
        'pip install gevent') from None
gevent.monkey.patch_all()
try:
    import aiogevent
except ImportError:
    raise
    raise ImportError(
        'Gevent loop requires the aiogevent library: '
        'pip install aiogevent') from None
import asyncio  # noqa: E402
if asyncio._get_running_loop() is not None:
    raise RuntimeError('Event loop created before importing gevent loop!')


class Policy(aiogevent.EventLoopPolicy):
    _loop: asyncio.AbstractEventLoop = None

    def get_event_loop(self) -> asyncio.AbstractEventLoop:
        # aiogevent raises an error here current_thread() is not MainThread,
        # but gevent monkey patches current_thread, so it's not a good check.
        if self._loop is None:
            self._loop = self.new_event_loop()
        return self._loop


policy = Policy()
asyncio.set_event_loop_policy(policy)
loop = asyncio.get_event_loop()