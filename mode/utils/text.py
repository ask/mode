"""Text and string manipulation utilities."""
from difflib import SequenceMatcher
from typing import AnyStr, Iterable, Iterator, NamedTuple, Optional

from .compat import want_str

__all__ = [
    "FuzzyMatch",
    "title",
    "didyoumean",
    "fuzzymatch_choices",
    "fuzzymatch_iter",
    "fuzzymatch_best",
    "abbr",
    "abbr_fqdn",
    "enumeration",
    "shorten_fqdn",
    "pluralize",
    "maybecat",
]


class FuzzyMatch(NamedTuple):
    """Fuzzy match resut."""

    ratio: float
    value: str


def title(s: str) -> str:
    """Capitalize sentence.

    ``"foo bar" -> "Foo Bar"``

    ``"foo-bar" -> "Foo Bar"``
    """
    return " ".join(
        p.capitalize() for p in s.replace("-", " ").replace("_", " ").split()
    )


def didyoumean(
    haystack: Iterable[str],
    needle: str,
    *,
    fmt_many: str = "Did you mean one of {alt}?",
    fmt_one: str = "Did you mean {alt}?",
    fmt_none: str = "",
    min_ratio: float = 0.6,
) -> str:
    """Generate message with helpful list of alternatives.

    Examples:
        >>> raise Exception(f'Unknown mode: {mode}! {didyoumean(modes, mode)}')

        >>> didyoumean(['foo', 'bar', 'baz'], 'boo')
        'Did you mean foo?'

        >>> didyoumean(['foo', 'moo', 'bar'], 'boo')
        'Did you mean one of foo, moo?'

        >>> didyoumean(['foo', 'moo', 'bar'], 'xxx')
        ''

    Arguments:
        haystack: List of all available choices.
        needle: What the user provided.

        fmt_many: String format returned when there are more than one
            alternative.  Default is: ``"Did you mean one of {alt}?"``.
        fmt_one: String format returned when there's a single fuzzy match.
            Default is: ``"Did you mean {alt}?"``.
        fmt_none: String format returned when there are no fuzzy matches.
            Default is: ``""`` (empty string, error message is usually printed
            before the alternatives so user has context).
        min_ratio: Minimum fuzzy ratio before word is considered a match.
            Default is 0.6.
    """
    return fuzzymatch_choices(
        list(haystack),
        needle,
        fmt_many=fmt_many,
        fmt_one=fmt_one,
        fmt_none=fmt_none,
        min_ratio=min_ratio,
    )


def enumeration(
    items: Iterable[str],
    *,
    start: int = 1,
    sep: str = "\n",
    template: str = "{index}) {item}",
) -> str:
    r"""Enumerate list of strings.

    Example:
        >>> enumeration(['x', 'y', '...'])
        "1) x\n2) y\n3) ..."
    """
    return sep.join(
        template.format(index=index, item=item)
        for index, item in enumerate(items, start=start)
    )


def fuzzymatch_choices(
    haystack: Iterable[str],
    needle: str,
    *,
    fmt_many: str = "one of {alt}",
    fmt_one: str = "{alt}",
    fmt_none: str = "",
    min_ratio: float = 0.6,
) -> str:
    """Fuzzy match reducing to error message suggesting an alternative."""
    alt = list(fuzzymatch(haystack, needle, min_ratio=min_ratio))
    if not alt:
        return fmt_none
    return (fmt_many if len(alt) > 1 else fmt_one).format(
        alt=", ".join(alt),
    )


def fuzzymatch(
    haystack: Iterable[str], needle: str, *, min_ratio: float = 0.6
) -> Iterator[str]:
    for match in fuzzymatch_iter(haystack, needle, min_ratio=min_ratio):
        yield match.value


def fuzzymatch_iter(
    haystack: Iterable[str], needle: str, *, min_ratio: float = 0.6
) -> Iterator[FuzzyMatch]:
    """Fuzzy Match: Including actual ratio.

    Yields:
        FuzzyMatch: tuples of ``(ratio, value)``.
    """
    for key in iter(haystack):
        ratio = SequenceMatcher(None, needle, key).ratio()
        if ratio >= min_ratio:
            yield FuzzyMatch(ratio, key)


def fuzzymatch_best(
    haystack: Iterable[str], needle: str, *, min_ratio: float = 0.6
) -> Optional[str]:
    """Fuzzy Match - Return best match only (single scalar value)."""
    try:
        return sorted(
            fuzzymatch_iter(haystack, needle, min_ratio=min_ratio),
            reverse=True,
        )[0].value
    except IndexError:
        return None


def abbr(s: str, max: int, suffix: str = "...", words: bool = False) -> str:
    """Abbreviate word."""
    if words:
        return _abbr_word_boundary(s, max, suffix)
    return _abbr_abrupt(s, max, suffix)


def _abbr_word_boundary(s: str, max: int, suffix: str) -> str:
    # Do not cut-off any words, but means the limit is even harder
    # and we won't include any partial words.
    if len(s) > max:
        return suffix and (s[: max - len(suffix)] + suffix) or s[:max]
    return s


def _abbr_abrupt(s: str, max: int, suffix: str = "...") -> str:
    # hard limit (can cut off in the middle of a word).
    if max and len(s) >= max:
        return s[:max].rsplit(" ", 1)[0] + suffix
    return s


def abbr_fqdn(origin: str, name: str, *, prefix: str = "") -> str:
    """Abbreviate fully-qualified Python name, by removing origin.

    ``app.origin`` is the package where the app is defined,
    so if this is ``examples.simple``::

        >>> app.origin
        'examples.simple'
        >>> abbr_fqdn(app.origin, 'examples.simple.Withdrawal', prefix='[...]')
        '[...]Withdrawal'

        >>> abbr_fqdn(app.origin, 'examples.other.Foo', prefix='[...]')
        'examples.other.foo'

    :func:`shorten_fqdn` is similar, but will always shorten a too long name,
    abbr_fqdn will only remove the origin portion of the name.
    """
    if name.startswith(origin):
        name = name[len(origin) + 1 :]
        return f"{prefix}{name}"
    return name


def shorten_fqdn(s: str, max: int = 32) -> str:
    """Shorten fully-qualified Python name (like "os.path.isdir")."""
    if len(s) > max:
        module, sep, cls = s.rpartition(".")
        if sep:
            module = abbr(module, max - len(cls) - 3, "", words=True)
            return module + "[.]" + cls
    return s


def pluralize(n: int, text: str, suffix: str = "s") -> str:
    """Pluralize term when n is greater than one."""
    if n != 1:
        return text + suffix
    return text


def maybecat(
    s: Optional[AnyStr], suffix: str = "", *, prefix: str = ""
) -> Optional[str]:
    """Concatenate string only if existing string s' is defined.

    Keyword Arguments:
        suffix: add suffix if string s' is defined.
        prefix: add prefix is string s' is defined.
    """
    if s is not None:
        return prefix + want_str(s) + suffix
    return s
