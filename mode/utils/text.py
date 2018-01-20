from typing import AnyStr, Optional, cast

__all__ = ['maybecat']


def maybecat(s: Optional[AnyStr], suffix: str = '',
             *,
             prefix: str = '') -> AnyStr:
    if s is not None:
        return prefix + cast(AnyStr, s) + suffix
    return s
