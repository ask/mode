import os
os.environ['GEVENT_LOOP'] = 'mode.loop._gevent_loop.Loop'
try:
    import eventlet
except ImportError:
    raise ImportError(
        'Eventlet loop requires the eventlet library: '
        'pip install eventlet') from None
eventlet.monkey_patch()

try:
    import aioeventlet
except ImportError:
    raise
    raise ImportError(
        'Eventlet loop requires the aioeventlet library: '
        'pip install aioeventlet') from None

import asyncio  # noqa: E402,I100,I202
if asyncio._get_running_loop() is not None:
    raise RuntimeError('Event loop created before importing eventlet loop!')

Policy = aioeventlet.EventLoopPolicy
policy = Policy()
asyncio.set_event_loop_policy(policy)
