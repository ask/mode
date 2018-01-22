# -*- coding: utf-8 -*-
"""AsyncIO Service-based programming."""
# :copyright: (c) 2017, Robinhood Markets
#             All rights reserved.
# :license:   BSD (3 Clause), see LICENSE for more details.
import importlib
import re
import sys
import typing
from typing import Any, Mapping, NamedTuple, Sequence

__version__ = '1.5.0'
__author__ = 'Robinhood Markets'
__contact__ = 'opensource@robinhood.com'
__homepage__ = 'https://github.com/fauststream/mode'
__docformat__ = 'restructuredtext'

# -eof meta-


class version_info_t(NamedTuple):
    major: int
    minor: int
    micro: int
    releaselevel: str
    serial: str


# bumpversion can only search for {current_version}
# so we have to parse the version here.
_temp = re.match(
    r'(\d+)\.(\d+).(\d+)(.+)?', __version__).groups()
VERSION = version_info = version_info_t(
    int(_temp[0]), int(_temp[1]), int(_temp[2]), _temp[3] or '', '')
del(_temp)
del(re)

if typing.TYPE_CHECKING:
    # These imports are here for static analyzers: It will not execute
    # when `faust` is imported, so none of these are actually imported.

    # We instead load these attributes lazily (below), so users only need to
    # import what they need, not the whole library.
    from .services import Service                         # noqa: E402
    from .signals import Signal                           # noqa: E402
    from .supervisors import (                            # noqa: E402
        OneForAllSupervisor,
        OneForOneSupervisor,
        SupervisorStrategy,
        CrashingSupervisor,
    )
    from .types import ServiceT, SignalT, SupervisorStrategyT  # noqa: E402
    from .utils.times import Seconds, want_seconds        # noqa: E402
    from .utils.logging import get_logger, setup_logging  # noqa: E402
    from .utils.objects import label, shortlabel          # noqa: E402
    from .worker import Worker                            # noqa: E402

__all__ = [
    'Service',
    'Signal',
    'SignalT',
    'OneForAllSupervisor',
    'OneForOneSupervisor',
    'SupervisorStrategy',
    'CrashingSupervisor',
    'ServiceT', 'SupervisorStrategyT',
    'Seconds', 'want_seconds',
    'get_logger', 'setup_logging',
    'label', 'shortlabel',
    'Worker',
]


# Lazy loading.
# - See werkzeug/__init__.py for the rationale behind this.

__all_by_module__: Mapping[str, Sequence[str]] = {
    'mode.services': ['Service'],
    'mode.signals': ['Signal'],
    'mode.supervisors': [
        'OneForAllSupervisor',
        'OneForOneSupervisor',
        'SupervisorStrategy',
        'CrashingSupervisor',
    ],
    'mode.types': ['ServiceT', 'SignalT', 'SupervisorStrategyT'],
    'mode.utils.times': ['Seconds', 'want_seconds'],
    'mode.utils.logging': ['get_logger', 'setup_logging'],
    'mode.utils.objects': ['label', 'shortlabel'],
    'mode.worker': ['Worker'],
}

__origin__: Mapping[str, str] = {}
for module, items in __all_by_module__.items():
    for item in items:
        __origin__[item] = module


def _get_mode_attribute(
        name: str,
        obj: Any,
        *,
        symbols: Mapping[str, Sequence[str]] = __all_by_module__,
        origins: Mapping[str, str] = __origin__) -> Any:
    if name in origins:
        module = importlib.import_module(origins[name])
        for extra_name in symbols[module.__name__]:
            setattr(obj, extra_name, getattr(module, extra_name))
        return getattr(module, name)
    raise AttributeError(f'module {__name__!r} has no attribute {name!r}')


def _get_mode_attributes() -> Sequence[str]:
    return sorted(list(__all__) + [
        '__file__', '__path__', '__doc__', '__all__',
        '__docformat__', '__name__', 'VERSION', 'version_info_t',
        'version_info', '__package__', '__version__', '__author__',
        '__contact__', '__homepage__', '__docformat__',
    ])


if sys.version_info >= (3, 7):

    def __getattr__(name: str) -> Any:
        print('_GETATTR: %r' % (name,))
        return _get_mode_attribute(name, sys.modules[__name__])

    def __dir__() -> Sequence[str]:
        return _get_mode_attributes()

else:

    from types import ModuleType  # noqa

    class _module(ModuleType):
        """Customized Python module."""

        def __getattr__(self, name: str) -> Any:
            try:
                return _get_mode_attribute(name, self)
            except AttributeError:
                return ModuleType.__getattribute__(self, name)

        def __dir__(self) -> Sequence[str]:
            return _get_mode_attributes()

    # keep a reference to this module so that it's not garbage collected
    old_module = sys.modules[__name__]
    new_module = sys.modules[__name__] = _module(__name__)
    new_module.__dict__.update({
        '__file__': __file__,
        '__path__': __path__,  # type: ignore
        '__doc__': __doc__,
        '__all__': tuple(__origin__),
        '__version__': __version__,
        '__author__': __author__,
        '__contact__': __contact__,
        '__homepage__': __homepage__,
        '__docformat__': __docformat__,
        '__package__': __package__,
        'version_info_t': version_info_t,
        'version_info': version_info,
        'VERSION': VERSION,
    })
