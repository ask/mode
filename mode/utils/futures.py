import asyncio
from typing import Any, Optional

__all__ = ['notify']


def notify(fut: Optional[asyncio.Future], result: Any = None) -> None:
    # can be used to turn a Future into a lockless, single-consumer condition,
    # for multi-consumer use asyncio.Condition
    if fut is not None and not fut.done():
        fut.set_result(result)
