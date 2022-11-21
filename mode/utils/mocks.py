"""Mocking and testing utilities."""
import builtins
import sys
import types
import unittest.mock
from contextlib import contextmanager
from types import ModuleType
from typing import Any, Iterator, cast
from unittest.mock import MagicMock

__all__ = ["IN", "call", "mask_module", "patch_module"]


class IN:
    """Class used to check for multiple alternatives.

    .. code-block:: python

        assert foo.value IN(a, b)

    """

    def __init__(self, *alternatives: Any) -> None:
        self.alternatives = alternatives

    def __eq__(self, other: Any) -> bool:
        return other in self.alternatives

    def __ne__(self, other: Any) -> bool:
        return other not in self.alternatives

    def __repr__(self) -> str:
        sep = " | "
        return f"<IN: {sep.join(map(str, self.alternatives))}>"


@contextmanager
def patch_module(*names: str, new_callable: Any = MagicMock) -> Iterator:
    """Mock one or modules such that every attribute is a :class:`Mock`."""
    prev = {}

    class MockModule(types.ModuleType):
        def __getattr__(self, attr: str) -> Any:
            setattr(self, attr, new_callable())
            return types.ModuleType.__getattribute__(self, attr)

    mods = []
    for name in names:
        try:
            prev[name] = sys.modules[name]
        except KeyError:
            pass
        mod = sys.modules[name] = MockModule(name)
        mods.append(mod)
    try:
        yield mods
    finally:
        for name in names:
            try:
                sys.modules[name] = prev[name]
            except KeyError:
                try:
                    del sys.modules[name]
                except KeyError:
                    pass


@contextmanager
def mask_module(*modnames: str) -> Iterator:
    """Ban some modules from being importable inside the context.

    For example::

        >>> with mask_module('sys'):
        ...     try:
        ...         import sys
        ...     except ImportError:
        ...         print('sys not found')
        sys not found

        >>> import sys  # noqa
        >>> sys.version
        (2, 5, 2, 'final', 0)

    Taken from
    http://bitbucket.org/runeh/snippets/src/tip/missing_modules.py

    """
    realimport = builtins.__import__

    def myimp(name: str, *args: Any, **kwargs: Any) -> ModuleType:
        if name in modnames:
            raise ImportError(f"No module named {name}")
        else:
            return cast(ModuleType, realimport(name, *args, **kwargs))

    builtins.__import__ = myimp
    try:
        yield
    finally:
        builtins.__import__ = realimport


class _Call(unittest.mock._Call):
    # Fixes bug in Python 3.8 where call is an instance of unittest.mock._Call
    # but call.__doc__ returns a mocked method and not the class attribute.

    def __getattr__(self, attr: str) -> Any:
        if attr == "__doc__":
            return unittest.mock._Call.__doc__
        return super().__getattr__(attr)


call = _Call(from_kall=False)
