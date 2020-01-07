"""Backport of :mod:`typing` additions in Python 3.7."""
# pragma: no cover
import typing

__all__ = [
    'AsyncContextManager',
    'AsyncGenerator',
    'ChainMap',
    'Counter',
    'Deque',
    'NoReturn',
    'Protocol',
]

if typing.TYPE_CHECKING:
    from typing import AsyncContextManager
else:
    try:
        from typing import AsyncContextManager  # noqa: F811
    except ImportError:
        from typing_extensions import AsyncContextManager

if typing.TYPE_CHECKING:
    from typing import AsyncGenerator
else:
    try:
        from typing import AsyncGenerator
    except ImportError:  # Python 3.6.0
        from typing_extensions import AsyncGenerator


if typing.TYPE_CHECKING:
    from typing import ChainMap
else:
    try:
        from typing import ChainMap  # noqa: F811
    except ImportError:
        from typing_extensions import ChainMap


if typing.TYPE_CHECKING:
    from typing import Counter
else:
    try:
        from typing import Counter  # noqa: F811
    except ImportError:
        from typing_extensions import Counter


if typing.TYPE_CHECKING:
    from typing import Deque
else:
    try:
        from typing import Deque  # noqa: F811
    except ImportError:
        from typing_extensions import Deque


if typing.TYPE_CHECKING:
    from typing import NoReturn
else:
    try:
        from typing import NoReturn  # noqa: F811
    except ImportError:
        from typing_extensions import NoReturn


if typing.TYPE_CHECKING:
    from typing import Protocol
else:
    try:
        from typing import Protocol  # noqa: F811
    except ImportError:
        from typing_extensions import Protocol
