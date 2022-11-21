# -*- coding: utf-8 -*-
"""AsyncIO Service-based programming."""
# :copyright: (c) 2017-2020, Robinhood Markets
#             (c) 2020-2022, faust-streaming Org
#             All rights reserved.
# :license:   BSD (3 Clause), see LICENSE for more details.
import re
import sys
from typing import NamedTuple

from .services import Service, task, timer  # noqa: E402
from .signals import BaseSignal, Signal, SyncSignal  # noqa: E402
from .supervisors import CrashingSupervisor  # noqa: E402
from .supervisors import (
    ForfeitOneForAllSupervisor,
    ForfeitOneForOneSupervisor,
    OneForAllSupervisor,
    OneForOneSupervisor,
    SupervisorStrategy,
)
from .types.services import ServiceT  # noqa: E402
from .types.signals import BaseSignalT, SignalT, SyncSignalT  # noqa: E402
from .types.supervisors import SupervisorStrategyT  # noqa: E402
from .utils.logging import flight_recorder, get_logger, setup_logging  # noqa: E402
from .utils.objects import label, shortlabel  # noqa: E402
from .utils.times import Seconds, want_seconds

if sys.version_info < (3, 8):
    from importlib_metadata import version
else:
    from importlib.metadata import version

__version__ = version("mode-streaming")
__author__ = "Faust Streaming"
__contact__ = "vpatki@wayfair.com, williambbarnhart@gmail.com"
__homepage__ = "https://github.com/faust-streaming/mode"
__docformat__ = "restructuredtext"

# -eof meta-


class version_info_t(NamedTuple):
    major: int
    minor: int
    micro: int
    releaselevel: str
    serial: str


# bumpversion can only search for {current_version}
# so we have to parse the version here.
_match = re.match(r"(\d+)\.(\d+).(\d+)(.+)?", __version__)
if _match is None:  # pragma: no cover
    raise RuntimeError("MODE VERSION HAS ILLEGAL FORMAT")
_temp = _match.groups()
VERSION = version_info = version_info_t(
    int(_temp[0]), int(_temp[1]), int(_temp[2]), _temp[3] or "", ""
)
del _match
del _temp
del re
