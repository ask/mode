"""Traceback utilities."""
import asyncio
import inspect
import io
import sys
from traceback import StackSummary, print_list, walk_tb
from types import FrameType
from typing import (
    Any,
    Coroutine,
    Generator,
    IO,
    Mapping,
    Optional,
    Union,
)

__all__ = [
    'Traceback',
    'format_task_stack',
    'print_task_stack',
]

DEFAULT_MAX_FRAMES = sys.getrecursionlimit() // 8


def print_task_stack(task: asyncio.Task, *,
                     file: IO = sys.stderr,
                     limit: int = DEFAULT_MAX_FRAMES,
                     capture_locals: bool = False) -> None:
    """Print the stack trace for an :class:`asyncio.Task`."""
    print(f'Stack for {task!r} (most recent call last):', file=file)
    tb = Traceback.from_task(task, limit=limit)
    print_list(
        StackSummary.extract(
            walk_tb(tb),
            limit=limit,
            capture_locals=capture_locals,
        ),
        file=file,
    )


def format_task_stack(task: asyncio.Task, *,
                      limit: int = DEFAULT_MAX_FRAMES) -> None:
    """Format :class:`asyncio.Task` stack trace as a string."""
    f = io.StringIO()
    print_task_stack(task, file=f, limit=limit)
    return f.getvalue()


class _CustomCode:
    co_filename: str
    co_name: str

    def __init__(self, filename: str, name: str) -> None:
        self.co_filename = filename
        self.co_name = name


class _CustomFrame:
    f_globals: Mapping[str, Any]
    f_fileno: int
    f_code: _CustomCode

    def __init__(self,
                 globals: Mapping[str, Any],
                 fileno: int,
                 code: _CustomCode) -> None:
        self.f_globals = globals
        self.f_fileno = fileno
        self.f_code = code
        self.f_locals = {}


class _BaseTraceback:
    tb_frame: FrameType
    tb_lineno: int
    tb_lasti: int
    tb_next: Optional['Traceback']


class _Truncated(_BaseTraceback):

    def __init__(self, filename='...', name='[rest of traceback truncated]'):
        self.tb_lineno = -1
        self.tb_frame = _CustomFrame(
            globals={
                '__file__': '',
                '__name__': '',
                '__loader__': None,
            },
            fileno=-1,
            code=_CustomCode(
                filename=filename,
                name=name,
            ),
        )
        self.tb_next = None
        self.tb_lasti = -1


class Traceback(_BaseTraceback):
    """Traceback object with truncated frames."""

    def __init__(self,
                 frame: FrameType,
                 lineno: int = None,
                 lasti: int = None) -> None:
        self.tb_frame = frame
        self.tb_lineno = lineno if lineno is not None else frame.f_lineno
        self.tb_lasti = lasti if lasti is not None else frame.f_lasti
        self.tb_next = None

    @classmethod
    def from_task(cls, task: asyncio.Task, *,
                  limit: int = DEFAULT_MAX_FRAMES) -> 'Traceback':
        coro = task._coro  # type: ignore
        return cls.from_coroutine(coro, limit=limit)

    @classmethod
    def from_coroutine(cls, coro: Union[Coroutine, Generator], *,
                       depth: int = 0,
                       limit: int = DEFAULT_MAX_FRAMES) -> 'Traceback':
        try:
            frame = cls._get_coroutine_frame(coro)
        except AttributeError:
            if type(coro).__name__ == 'async_generator_asend':
                return _Truncated(filename='async_generator_asend')
            raise
        frames = []
        f = frame
        while f is not None:
            if limit is not None:
                if limit <= 0:
                    break
                limit -= 1
                frames.append(f)
                f = f.f_back
        frames.reverse()
        prev = None
        for f in frames:
            tb = cls(f)
            if prev is not None:
                prev.tb_next = tb
            prev = tb
        cr_await = cls._get_coroutine_next(coro)
        if limit is None:
            limit = getattr(sys, 'tracebacklimit', None)
            if limit is not None and limit < 0:
                limit = 0
        if cr_await is not None and asyncio.iscoroutine(cr_await):
            if depth <= limit:
                tb.tb_next = cls.from_coroutine(cr_await, depth=depth + 1)
            else:
                tb.tb_next = _Truncated()
        return tb

    @staticmethod
    def _get_coroutine_frame(coro: Union[Coroutine, Generator]) -> FrameType:
        try:
            if inspect.isgenerator(coro):
                # is a @asyncio.coroutine wrapped generator
                return coro.gi_frame
            else:
                # is an async def function
                return coro.cr_frame
        except AttributeError as exc:
            raise AttributeError(
                'WHAT IS THIS? str={0} repr={1!r} typ={2!r} dir={3}'.format(
                    coro, coro, type(coro), dir(coro))) from exc

    @staticmethod
    def _get_coroutine_next(coro: Union[Coroutine, Generator]) -> Any:
        if inspect.isgenerator(coro):
            # is a @asyncio.coroutine wrapped generator
            return coro.gi_yieldfrom
        else:
            # is an async def function
            return coro.cr_await
