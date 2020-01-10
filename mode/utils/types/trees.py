"""Type classes for :mod:`mode.utils.trees`."""
import abc
from typing import Any, Generic, Iterator, List, Optional, TypeVar, Union
from .graphs import DependencyGraphT

__all__ = ['NodeT']

_T = TypeVar('_T')


class NodeT(Generic[_T]):
    """Node in a tree data structure."""

    children: List[Any]
    data: Any = None

    @classmethod
    @abc.abstractmethod
    def _new_node(cls, data: _T, **kwargs: Any) -> 'NodeT':
        ...

    @abc.abstractmethod
    def new(self, data: _T) -> 'NodeT':
        ...

    @abc.abstractmethod
    def add(self, data: Union[_T, 'NodeT[_T]']) -> None:
        ...

    @abc.abstractmethod
    def add_deduplicate(self, data: Union[_T, 'NodeT[_T]']) -> None:
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

    @abc.abstractmethod
    def detach(self, parent: 'NodeT') -> 'NodeT':
        ...

    @property
    @abc.abstractmethod
    def parent(self) -> Optional['NodeT']:
        ...

    @parent.setter
    def parent(self, node: 'NodeT') -> None:
        ...

    @property
    @abc.abstractmethod
    def root(self) -> Optional['NodeT']:
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
