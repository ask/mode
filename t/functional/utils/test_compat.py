from unittest.mock import Mock

import pytest

from mode.utils.compat import isatty, want_bytes, want_str


@pytest.mark.parametrize(
    "input,expected",
    [
        ("foo", b"foo"),
        (b"foo", b"foo"),
    ],
)
def test_want_bytes(input, expected):
    assert want_bytes(input) == expected


@pytest.mark.parametrize(
    "input,expected",
    [
        (b"foo", "foo"),
        ("foo", "foo"),
    ],
)
def test_want_str(input, expected):
    assert want_str(input) == expected


def test_isatty():
    m = Mock()
    m.isatty.return_value = True
    assert isatty(m)
    m.isatty.side_effect = AttributeError()
    assert not isatty(m)
