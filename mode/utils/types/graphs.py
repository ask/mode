import abc
from typing import (
    Any, Generic, IO, Iterable, Mapping, MutableMapping, Sequence, TypeVar,
)

__all__ = ['GraphFormatterT', 'DependencyGraphT']

_T = TypeVar('_T')


class GraphFormatterT(Generic[_T]):

    scheme: Mapping[str, Any]
    edge_scheme: Mapping[str, Any]
    node_scheme: Mapping[str, Any]
    term_scheme: Mapping[str, Any]
    graph_scheme: Mapping[str, Any]

    @abc.abstractmethod
    def __init__(self,
                 root: Any = None,
                 type: str = None,
                 id: str = None,
                 indent: int = 0,
                 inw: str = ' ' * 4,
                 **scheme: Any) -> None:
        ...

    @abc.abstractmethod
    def attr(self, name: str, value: Any) -> str:
        ...

    @abc.abstractmethod
    def attrs(self, d: Mapping = None, scheme: Mapping = None) -> str:
        ...

    @abc.abstractmethod
    def head(self, **attrs: Any) -> str:
        ...

    @abc.abstractmethod
    def tail(self) -> str:
        ...

    @abc.abstractmethod
    def label(self, obj: _T) -> str:
        ...

    @abc.abstractmethod
    def node(self, obj: _T, **attrs: Any) -> str:
        ...

    @abc.abstractmethod
    def terminal_node(self, obj: _T, **attrs: Any) -> str:
        ...

    @abc.abstractmethod
    def edge(self, a: _T, b: _T, **attrs: Any) -> str:
        ...

    @abc.abstractmethod
    def FMT(self, fmt: str, *args: Any, **kwargs: Any) -> str:
        ...

    @abc.abstractmethod
    def draw_edge(self, a: _T, b: _T,
                  scheme: Mapping = None,
                  attrs: Mapping = None) -> str:
        ...

    @abc.abstractmethod
    def draw_node(self, obj: _T,
                  scheme: Mapping = None,
                  attrs: Mapping = None) -> str:
        ...


class DependencyGraphT(Generic[_T], Mapping[_T, _T]):

    adjacent: MutableMapping[_T, _T]

    @abc.abstractmethod
    def __init__(self,
                 it: Iterable[_T] = None,
                 formatter: GraphFormatterT[_T] = None) -> None:
        ...

    @abc.abstractmethod
    def add_arc(self, obj: _T) -> None:
        ...

    @abc.abstractmethod
    def add_edge(self, A: _T, B: _T) -> None:
        ...

    @abc.abstractmethod
    def connect(self, graph: 'DependencyGraphT') -> None:
        ...

    @abc.abstractmethod
    def topsort(self) -> Sequence:
        ...

    @abc.abstractmethod
    def valency_of(self, obj: _T) -> int:
        ...

    @abc.abstractmethod
    def update(self, it: Iterable) -> None:
        ...

    @abc.abstractmethod
    def edges(self) -> Iterable:
        ...

    @abc.abstractmethod
    def to_dot(self, fh: IO, *, formatter: GraphFormatterT[_T] = None) -> None:
        ...
