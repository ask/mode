try:
    from contextlib import AbstractAsyncContextManager
    from contextlib import AsyncExitStack, ExitStack
    from contextlib import asynccontextmanager
except ImportError:
    from ._py37_contextlib import AbstractAsyncContextManager
    from ._py37_contextlib import AsyncExitStack, ExitStack
    from ._py37_contextlib import asynccontextmanager

__all__ = [
    'AbstractAsyncContextManager',
    'AsyncExitStack',
    'ExitStack',
    'asynccontextmanager',
]
