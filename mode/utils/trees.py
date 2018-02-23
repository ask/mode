from contextlib import suppress
from typing import Any, Iterator, List, cast

from .compat import Deque
from .graphs import DependencyGraph
from .objects import shortlabel
from .types.graphs import DependencyGraphT
from .types.trees import NodeT, _T

__all__ = [
    'Node',
]


class Node(NodeT):
    """Tree node.

    Notes:
        Nodes have a link to

            - the ``.root`` node (or None if this is the top-most node)
            - the ``.parent`` node (if this is a child node).
            - a list of children

        A Node may have ``.data`` associated with it, and arbitrary
        data may also be stored in ``.children``.

    Arguments:
        data (Any): Data to associate with node.

    Keyword Arguments:
        root (NodeT): Root node.
        parent (NodeT): Parent node.
        children (List[NodeT]): List of child nodes.
    """

    _root: NodeT = None
    _parent: NodeT = None

    @classmethod
    def _new_node(cls, data: _T, **kwargs: Any) -> NodeT:
        return cls(data, **kwargs)  # type: ignore

    def __init__(self, data: _T,
                 *,
                 root: NodeT = None,
                 parent: NodeT = None,
                 children: List[NodeT] = None) -> None:
        self.data = data
        self.root = root
        self.parent = parent
        self.children = children or []

    def new(self, data: _T) -> NodeT:
        """Create new node from this node."""
        node = self._new_node(
            data,
            root=self.root if self.root is not None else self,
            parent=self,
        )
        self.children.append(node)
        return node

    def reattach(self, parent: NodeT) -> NodeT:
        """Attach this node to `parent` node."""
        self.root = parent.root if parent.root is not None else parent
        self.parent = parent
        parent.add(self)
        return self

    def add(self, data: _T) -> None:
        """Add node as a child node."""
        self.children.append(data)

    def discard(self, data: _T) -> None:
        """Remove node so it's no longer a child of this node."""
        # XXX slow
        with suppress(ValueError):
            self.children.remove(data)

    def traverse(self) -> Iterator[NodeT]:
        """Iterator traversing the tree in BFS order."""
        stack: Deque[NodeT] = Deque([self])
        while stack:
            node = stack.popleft()
            yield node
            for child in node.children:
                if isinstance(child, NodeT):
                    stack.append(child)
                else:
                    yield child

    def walk(self) -> Iterator[NodeT]:
        """Iterate over hierarchy backwards.

        This will yield parent nodes all the way up to the root.
        """
        node: NodeT = self
        while node:
            yield node
            node = node.parent

    def as_graph(self) -> DependencyGraphT:
        """Convert to :class:`~mode.utils.graphs.DependencyGraph`."""
        graph = DependencyGraph()
        stack: Deque[NodeT] = Deque([self])
        while stack:
            node = stack.popleft()
            for child in node.children:
                graph.add_arc(node.data)
                if isinstance(child, NodeT):
                    stack.append(cast(Node, child))
                    graph.add_edge(node.data, child.data)
                else:
                    graph.add_edge(node.data, child)
        return graph

    def __repr__(self) -> str:
        return f'{type(self).__name__}: {self.path}'

    @property
    def depth(self) -> int:
        return self._find_depth()

    def _find_depth(self) -> int:
        return sum(1 for _ in enumerate(self.walk()))

    @property
    def path(self) -> str:
        return '/'.join(reversed([
            shortlabel(node.data) for node in self.walk()
        ]))

    @property
    def parent(self) -> NodeT:
        return self._parent

    @parent.setter
    def parent(self, node: NodeT) -> None:
        if node is self:
            raise ValueError('Parent node cannot be itself.')
        self._parent = node

    @property
    def root(self) -> NodeT:
        return self._root

    @root.setter
    def root(self, node: NodeT) -> None:
        if node is self:
            raise ValueError('Root node cannot be itself.')
        self._root = node
