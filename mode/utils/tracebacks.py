"""Traceback utilities."""
import asyncio
import inspect
import io
import sys
from traceback import StackSummary, print_list, walk_tb
from types import FrameType, TracebackType
from typing import (
    Any,
    AsyncGenerator,
    Coroutine,
    Generator,
    IO,
    Mapping,
    Optional,
    Union,
    cast,
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
            cast(Generator, walk_tb(cast(TracebackType, tb))),
            limit=limit,
            capture_locals=capture_locals,
        ),
        file=file,
    )


def print_coro_stack(coro: Coroutine, *,
                     file: IO = sys.stderr,
                     limit: int = DEFAULT_MAX_FRAMES,
                     capture_locals: bool = False) -> None:
    """Print the stack trace for a currently running coroutine."""
    print(f'Stack for {coro!r} (most recent call last):', file=file)
    tb = Traceback.from_coroutine(coro, limit=limit)
    print_list(
        StackSummary.extract(
            cast(Generator, walk_tb(cast(TracebackType, tb))),
            limit=limit,
            capture_locals=capture_locals,
        ),
        file=file,
    )


def print_agen_stack(agen: AsyncGenerator, *,
                     file: IO = sys.stderr,
                     limit: int = DEFAULT_MAX_FRAMES,
                     capture_locals: bool = False) -> None:
    """Print the stack trace for a currently running async generator."""
    print(f'Stack for {agen!r} (most recent call last):', file=file)
    tb = Traceback.from_agen(agen, limit=limit)
    print_list(
        StackSummary.extract(
            cast(Generator, walk_tb(cast(TracebackType, tb))),
            limit=limit,
            capture_locals=capture_locals,
        ),
        file=file,
    )


def format_task_stack(task: asyncio.Task, *,
                      limit: int = DEFAULT_MAX_FRAMES,
                      capture_locals: bool = False) -> str:
    """Format :class:`asyncio.Task` stack trace as a string."""
    f = io.StringIO()
    print_task_stack(task, file=f, limit=limit, capture_locals=capture_locals)
    return f.getvalue()


def format_coro_stack(coro: Coroutine, *,
                      limit: int = DEFAULT_MAX_FRAMES,
                      capture_locals: bool = False) -> str:
    """Format coroutine stack trace as a string."""
    f = io.StringIO()
    print_coro_stack(coro, file=f, limit=limit, capture_locals=capture_locals)
    return f.getvalue()


def format_agen_stack(agen: AsyncGenerator, *,
                      limit: int = DEFAULT_MAX_FRAMES,
                      capture_locals: bool = False) -> str:
    f = io.StringIO()
    print_agen_stack(agen, file=f, limit=limit, capture_locals=capture_locals)
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
    f_locals: Mapping[str, Any]

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
    tb_next: Optional['_BaseTraceback']


class _Truncated(_BaseTraceback):

    def __init__(self,
                 filename: str = '...',
                 name: str = '[rest of traceback truncated]') -> None:
        self.tb_lineno = -1
        self.tb_frame = cast(FrameType, _CustomFrame(
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
        ))
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
                  limit: int = DEFAULT_MAX_FRAMES) -> _BaseTraceback:
        coro = task._coro  # type: ignore
        return cls.from_coroutine(coro, limit=limit)

    @classmethod
    def from_agen(cls, agen: AsyncGenerator, *,
                  limit: int = DEFAULT_MAX_FRAMES) -> _BaseTraceback:
        return cls.from_coroutine(agen, limit=limit)

    @classmethod
    def from_coroutine(
            cls, coro: Union[AsyncGenerator, Coroutine, Generator], *,
            depth: int = 0,
            limit: Optional[int] = DEFAULT_MAX_FRAMES) -> _BaseTraceback:
        try:
            frame = cls._detect_frame(coro)
        except AttributeError:
            if type(coro).__name__ == 'async_generator_asend':
                return _Truncated(filename='async_generator_asend')
            raise
        if limit is None:
            limit = getattr(sys, 'tracebacklimit', None)
        if limit is not None and limit < 0:
            limit = 0
        frames = []
        num_frames = 0
        current_frame = frame
        while current_frame is not None:
            if limit is not None:
                if num_frames > limit:
                    break
            frames.append(current_frame)
            num_frames += 1
            current_frame = current_frame.f_back
        frames.reverse()
        prev: Optional[_BaseTraceback] = None
        root: Optional[_BaseTraceback] = None
        for f in frames:
            tb = cls(f)
            if root is None:
                root = tb
            if prev is not None:
                prev.tb_next = tb
            prev = tb
        cr_await = cls._get_coroutine_next(coro)
        if cr_await is not None and asyncio.iscoroutine(cr_await):
            next_node: _BaseTraceback
            if limit is not None and depth > limit:
                next_node = _Truncated()
            else:
                next_node = cls.from_coroutine(
                    cr_await, limit=limit, depth=depth + 1)
            if root is not None:
                root.tb_next = next_node
            else:
                return next_node
        if root is None:
            raise RuntimeError('cannot find stack of coroutine')
        return root

    @classmethod
    def _detect_frame(cls, obj: Any) -> FrameType:
        if inspect.isasyncgen(obj):
            return cls._get_agen_frame(obj)
        return cls._get_coroutine_frame(obj)

    @classmethod
    def _get_coroutine_frame(cls,
                             coro: Union[Coroutine, Generator]) -> FrameType:
        try:
            if inspect.isgenerator(coro):
                # is a @asyncio.coroutine wrapped generator
                return cast(Generator, coro).gi_frame
            else:
                # is an async def function
                return cast(Coroutine, coro).cr_frame
        except AttributeError as exc:
            raise cls._what_is_this(coro) from exc

    @classmethod
    def _what_is_this(cls, obj: Any) -> AttributeError:
        return AttributeError(
            'WHAT IS THIS? str={0} repr={1!r} typ={2!r} dir={3}'.format(
                obj, obj, type(obj), dir(obj)))

    @classmethod
    def _get_agen_frame(cls, agen: AsyncGenerator) -> FrameType:
        try:
            return agen.ag_frame
        except AttributeError as exc:
            raise cls._what_is_this(agen) from exc

    @staticmethod
    def _get_coroutine_next(
            coro: Union[AsyncGenerator, Coroutine, Generator]) -> Any:
        if inspect.isasyncgen(coro):
            # is a async def async-generator
            return cast(AsyncGenerator, coro).ag_await
        elif inspect.isgenerator(coro):
            # is a @asyncio.coroutine wrapped generator
            return cast(Generator, coro).gi_yieldfrom
        else:
            # is an async def function
            return cast(Coroutine, coro).cr_await
