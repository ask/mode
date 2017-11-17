import abc
from typing import Any, Generic, Iterator, List, TypeVar
from .graphs import DependencyGraphT

__all__ = ['NodeT']

_T = TypeVar('_T')


class NodeT(Generic[_T]):
    root: 'NodeT'
    children: List[Any]
    parent: 'NodeT'
    data: Any

    @classmethod
    @abc.abstractmethod
    def _new_node(cls, data: _T, **kwargs: Any) -> 'NodeT':
        ...

    @abc.abstractmethod
    def new(self, data: _T) -> 'NodeT':
        ...

    @abc.abstractmethod
    def add(self, data: _T) -> None:
        ...

    @abc.abstractmethod
    def discard(self, data: _T) -> None:
        ...

    @abc.abstractmethod
    def reattach(self, parent: 'NodeT') -> 'NodeT':
        ...

    @abc.abstractmethod
    def traverse(self) -> Iterator['NodeT']:
        ...

    @abc.abstractmethod
    def walk(self) -> Iterator['NodeT']:
        ...

    @abc.abstractmethod
    def as_graph(self) -> DependencyGraphT:
        ...

    @property
    @abc.abstractmethod
    def parent(self) -> 'NodeT':
        ...

    @parent.setter
    def parent(self, node: 'NodeT') -> None:
        ...

    @property
    @abc.abstractmethod
    def root(self) -> 'NodeT':
        ...

    @root.setter
    def root(self, node: 'NodeT') -> None:
        ...

    @property
    @abc.abstractmethod
    def depth(self) -> int:
        ...

    @property
    @abc.abstractmethod
    def path(self) -> str:
        ...
