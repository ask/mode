from unittest.mock import Mock

import pytest

from mode.utils import text


@pytest.mark.parametrize(
    "input,expected",
    [
        ("the quick brown fox", "The Quick Brown Fox"),
        ("laZy-doG", "Lazy Dog"),
        ("laZy_DOG-of-t3-moo_era", "Lazy Dog Of T3 Moo Era"),
    ],
)
def test_title(input, expected):
    assert text.title(input) == expected


@pytest.mark.parametrize(
    "choices,choice,expected",
    [
        (["foo", "bar", "baz"], "boo", "Did you mean foo?"),
        (["foo", "moo", "bar"], "boo", "Did you mean one of foo, moo?"),
        (["foo", "moo", "zoo"], "boo", "Did you mean one of foo, moo, zoo?"),
        (["foo", "bar", "baz"], "xxx", ""),
    ],
)
def test_didyoumean(choices, choice, expected):
    assert text.didyoumean(choices, choice) == expected


@pytest.mark.parametrize(
    "s,max,suffix,words,expected",
    [
        (
            "The quick brown hippopotamus jumped over the funny dog",
            27,
            "...",
            False,
            "The quick brown...",
        ),
        (
            "The quick brown hippopotamus jumped over the funny dog",
            27,
            "...",
            True,
            "The quick brown hippopot...",
        ),
        (
            "The quick brown hippopotamus jumped over the funny dog",
            1127,
            "...",
            False,
            "The quick brown hippopotamus jumped over the funny dog",
        ),
        (
            "The quick brown hippopotamus jumped over the funny dog",
            1127,
            "...",
            True,
            "The quick brown hippopotamus jumped over the funny dog",
        ),
    ],
)
def test_abbr(s, max, suffix, words, expected):
    assert text.abbr(s, max, suffix=suffix, words=words) == expected


@pytest.mark.parametrize(
    "choices,choice,expected",
    [
        (["foo", "fop", "mop"], "moo", "mop"),
        (["xab", "mup", "sop"], "yyy", None),
    ],
)
def test_fuzzymatch_best(choices, choice, expected):
    assert text.fuzzymatch_best(choices, choice) == expected


@pytest.mark.parametrize(
    "origin,name,prefix,expected",
    [
        (
            "examples.simple",
            "examples.simple.Withdrawal",
            "[...]",
            "[...]Withdrawal",
        ),
        (
            "examples.other",
            "examples.simple.Withdrawal",
            "[...]",
            "examples.simple.Withdrawal",
        ),
    ],
)
def test_abbr_fqdn(origin, name, prefix, expected):
    assert text.abbr_fqdn(origin, name, prefix=prefix) == expected


@pytest.mark.parametrize(
    "n,s,suffix,expected",
    [
        (-2, "argument", "s", "arguments"),
        (-1, "argument", "s", "arguments"),
        (-0, "argument", "s", "arguments"),
        (0, "argument", "s", "arguments"),
        (1, "argument", "s", "argument"),
        (2, "argument", "s", "arguments"),
    ],
)
def test_pluralize(n, s, suffix, expected):
    assert text.pluralize(n, s, suffix=suffix) == expected


@pytest.mark.parametrize(
    "s,prefix,suffix,expected",
    [
        ("", "b", "c", "bc"),
        (None, "b", "c", None),
        ("a", "b", "c", "bac"),
        ("a", "", "c", "ac"),
        ("a", "b", "", "ba"),
    ],
)
def test_maybecat(s, prefix, suffix, expected):
    assert text.maybecat(s, prefix=prefix, suffix=suffix) == expected


@pytest.mark.parametrize(
    "s,expected",
    [
        (
            "faust.utils.transformators.frobster",
            "faust.utils.transform[.]frobster",
        ),
        ("foo.bar.baz", "foo.bar.baz"),
        (
            "foobarbazdeliciouslybubblyfluffychocolatebar",
            "foobarbazdeliciouslybubblyfluffychocolatebar",
        ),
    ],
)
def test_shorten_fqdn(s, expected):
    assert text.shorten_fqdn(s) == expected


@pytest.mark.parametrize(
    "input,expected",
    [
        ("foo", b"foo"),
        (b"foo", b"foo"),
    ],
)
def test_want_bytes(input, expected):
    assert text.want_bytes(input) == expected


@pytest.mark.parametrize(
    "input,expected",
    [
        (b"foo", "foo"),
        ("foo", "foo"),
    ],
)
def test_want_str(input, expected):
    assert text.want_str(input) == expected


def test_isatty():
    m = Mock()
    m.isatty.return_value = True
    assert text.isatty(m)
    m.isatty.side_effect = AttributeError()
    assert not text.isatty(m)
