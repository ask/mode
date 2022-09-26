"""Enable :pypi:`uvloop` as the event loop for :mod:`asyncio`."""
import asyncio

import uvloop

asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())
