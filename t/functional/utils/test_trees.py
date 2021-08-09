import pytest

from mode.utils.trees import Node


def test_Node():
    node = Node(303)
    assert node.data == 303
    assert node.parent is None
    assert node.root is None

    node2 = node.new(808)
    assert node2.parent is node
    assert node2.root is node

    node3 = node2.new(909)
    assert node3.parent is node2
    assert node3.parent.parent is node
    assert node3.path == "303/808/909"
    assert repr(node3)

    node3.children.append(10)
    assert list(node.traverse()) == [node, node2, node3, 10]
    node3.children.clear()

    assert node3.root is node

    assert node2 in node.children
    assert node3 in node2.children

    node4 = node.new(606)
    assert len(node.children) == 2

    node.discard(node4)
    assert len(node.children) == 1

    node.add(101)
    assert len(node.children) == 2
    node.discard(101)
    assert len(node.children) == 1

    node5 = Node(202)
    node5.reattach(node4)
    assert node5.parent is node4
    assert node5.root is node
    assert node5 in node4.children

    node5.detach(node4)
    assert node5.parent is None
    assert node5.root is None
    assert node5 not in node4.children

    node.children.append(11)
    assert (
        str(node.as_graph())
        == """\
303(3)
     808(1)
          909(0)
     11(0)
808(1)
     909(0)"""
    )

    with pytest.raises(ValueError):
        node.root = node  # root node cannot be itself
    with pytest.raises(ValueError):
        node.parent = node  # parent node cannot be itself
