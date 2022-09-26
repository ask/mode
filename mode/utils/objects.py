"""Object utilities."""
import abc
import collections.abc
import sys
import typing
from contextlib import suppress
from decimal import Decimal
from functools import total_ordering
from pathlib import Path
from typing import (
    AbstractSet,
    Any,
    Callable,
    ClassVar,
    Dict,
    FrozenSet,
    Generic,
    Iterable,
    List,
    Mapping,
    MutableMapping,
    MutableSequence,
    MutableSet,
    Optional,
    Sequence,
    Set,
    Tuple,
    Type,
    TypeVar,
    cast,
)

try:
    from typing import _eval_type  # type: ignore
except ImportError:

    def _eval_type(t, globalns, localns, recursive_guard=frozenset()):  # type: ignore
        return t


try:
    from typing import _type_check  # type: ignore
except ImportError:

    def _type_check(arg, msg, is_argument=True, module=None):  # type: ignore
        return arg


try:
    from typing import _ClassVar  # type: ignore
except ImportError:  # pragma: no cover
    # CPython 3.7
    from typing import _GenericAlias  # type: ignore

    def _is_class_var(x: Any) -> bool:  # noqa
        return isinstance(x, _GenericAlias) and x.__origin__ is ClassVar


else:  # pragma: no cover
    # CPython 3.6
    def _is_class_var(x: Any) -> bool:
        return type(x) is _ClassVar


if typing.TYPE_CHECKING:

    class ForwardRef:  # noqa
        __forward_arg__: str
        __forward_evaluated__: bool
        __forward_value__: Type
        __forward_code__: Any

        def __init__(self, arg: str, is_argument: bool = True) -> None:
            ...


else:
    try:
        # CPython 3.7
        from typing import ForwardRef
    except ImportError:  # pragma: no cover
        # CPython 3.6
        from typing import _ForwardRef as ForwardRef

__all__ = [
    "FieldMapping",
    "DefaultsMapping",
    "Unordered",
    "KeywordReduce",
    "InvalidAnnotation",
    "abc_compatible_with_init_subclass",
    "qualname",
    "shortname",
    "canoname",
    "canonshortname",
    "annotations",
    "eval_type",
    "iter_mro_reversed",
    "guess_polymorphic_type",
    "cached_property",
    "label",
    "shortlabel",
]

# Workaround for https://bugs.python.org/issue29581
try:

    @typing.no_type_check  # type: ignore
    class _InitSubclassCheck(metaclass=abc.ABCMeta):
        ident: int

        def __init_subclass__(
            self, *args: Any, ident: int = 808, **kwargs: Any
        ) -> None:
            self.ident = ident
            super().__init__(*args, **kwargs)

    @typing.no_type_check  # type: ignore
    class _UsingKwargsInNew(_InitSubclassCheck, ident=909):
        ...


except TypeError:
    abc_compatible_with_init_subclass = False
else:
    abc_compatible_with_init_subclass = True

_T = TypeVar("_T")
RT = TypeVar("RT")

#: Mapping of attribute name to attribute type.
FieldMapping = Mapping[str, Type]

#: Mapping of attribute name to attributes default value.
DefaultsMapping = Mapping[str, Any]

SET_TYPES: Tuple[Type, ...] = (
    AbstractSet,
    FrozenSet,
    MutableSet,
    Set,
    collections.abc.Set,
)
LIST_TYPES: Tuple[Type, ...] = (
    List,
    Sequence,
    MutableSequence,
    collections.abc.Sequence,
)
DICT_TYPES: Tuple[Type, ...] = (
    Dict,
    Mapping,
    MutableMapping,
    collections.abc.Mapping,
)
# XXX cast required for mypy bug
# "expression has type Tuple[_SpecialForm]"
TUPLE_TYPES: Tuple[Type, ...] = cast(Tuple[Type, ...], (Tuple,))


class InvalidAnnotation(Exception):
    """Raised by :func:`annotations` when encountering an invalid type."""


@total_ordering
class Unordered(Generic[_T]):
    """Shield object from being ordered in heapq/``__le__``/etc."""

    # Used to put anything inside a heapq, even things that cannot be ordered
    # like dicts and lists.

    def __init__(self, value: _T) -> None:
        self.value = value

    def __le__(self, other: Any) -> bool:
        return True

    def __repr__(self) -> str:
        return f"<{type(self).__name__}: {self.value!r}>"


def _restore_from_keywords(typ: Type, kwargs: Dict) -> Any:
    # This function is used to restore pickled KeywordReduce object.
    return typ(**kwargs)


class KeywordReduce:
    """Mixin class for objects that can be "pickled".

    "Pickled" means the object can be serialiazed using the Python binary
    serializer -- the :mod:`pickle` module.

    Python objects are made pickleable through defining the ``__reduce__``
    method, that returns a tuple of:
    ``(restore_function, function_starargs)``::

        class X:

            def __init__(self, arg1, kw1=None):
                self.arg1 = arg1
                self.kw1 = kw1

            def __reduce__(self) -> Tuple[Callable, Tuple[Any, ...]]:
                return type(self), (self.arg1, self.kw1)

    This is *tedious* since this means you cannot accept ``**kwargs`` in the
    constructur, so what we do is define a ``__reduce_keywords__``
    argument that returns a dict instead::

        class X:

            def __init__(self, arg1, kw1=None):
                self.arg1 = arg1
                self.kw1 = kw1

            def __reduce_keywords__(self) -> Mapping[str, Any]:
                return {
                    'arg1': self.arg1,
                    'kw1': self.kw1,
                }
    """

    def __reduce_keywords__(self) -> Mapping:
        raise NotImplementedError()

    def __reduce__(self) -> Tuple:
        return _restore_from_keywords, (type(self), self.__reduce_keywords__())


def qualname(obj: Any) -> str:
    """Get object qualified name."""
    if not hasattr(obj, "__name__") and hasattr(obj, "__class__"):
        obj = obj.__class__
    name = getattr(obj, "__qualname__", obj.__name__)
    return ".".join((obj.__module__, name))


def shortname(obj: Any) -> str:
    """Get object name (non-qualified)."""
    if not hasattr(obj, "__name__") and hasattr(obj, "__class__"):
        obj = obj.__class__
    return ".".join((obj.__module__, obj.__name__))


def canoname(obj: Any, *, main_name: str = None) -> str:
    """Get qualname of obj, trying to resolve the real name of ``__main__``."""
    name = qualname(obj)
    parts = name.split(".")
    if parts[0] == "__main__":
        return ".".join([main_name or _detect_main_name()] + parts[1:])
    return name


def canonshortname(obj: Any, *, main_name: str = None) -> str:
    """Get non-qualified name of obj, resolve real name of ``__main__``."""
    name = shortname(obj)
    parts = name.split(".")
    if parts[0] == "__main__":
        return ".".join([main_name or _detect_main_name()] + parts[1:])
    return name


def _detect_main_name() -> str:  # pragma: no cover
    try:
        filename = sys.modules["__main__"].__file__
    except (AttributeError, KeyError):  # ipython/REPL
        return "__main__"
    else:
        path = Path(filename).absolute()
        node = path.parent
        seen = []
        while node:
            if (node / "__init__.py").exists():
                seen.append(node.stem)
                node = node.parent
            else:
                break
        return ".".join(seen + [path.stem])


def annotations(
    cls: Type,
    *,
    stop: Type = object,
    invalid_types: Set = None,
    alias_types: Mapping = None,
    skip_classvar: bool = False,
    globalns: Dict[str, Any] = None,
    localns: Dict[str, Any] = None,
) -> Tuple[FieldMapping, DefaultsMapping]:
    """Get class field definition in MRO order.

    Arguments:
        cls: Class to get field information from.
        stop: Base class to stop at (default is ``object``).
        invalid_types: Set of types that if encountered should raise
          :exc:`InvalidAnnotation` (does not test for subclasses).
        alias_types: Mapping of original type to replacement type.
        skip_classvar: Skip attributes annotated with
            :class:`typing.ClassVar`.
        globalns: Global namespace to use when evaluating forward
            references (see :class:`typing.ForwardRef`).
        localns: Local namespace to use when evaluating forward
            references (see :class:`typing.ForwardRef`).

    Returns:
        Tuple[FieldMapping, DefaultsMapping]: Tuple with two dictionaries,
            the first containing a map of field names to their types,
            the second containing a map of field names to their default
            value.  If a field is not in the second map, it means the field
            is required.

    Raises:
        InvalidAnnotation: if a list of invalid types are provided and an
            invalid type is encountered.

    Examples:
        .. sourcecode:: text

            >>> class Point:
            ...    x: float
            ...    y: float

            >>> class 3DPoint(Point):
            ...     z: float = 0.0

            >>> fields, defaults = annotations(3DPoint)
            >>> fields
            {'x': float, 'y': float, 'z': 'float'}
            >>> defaults
            {'z': 0.0}
    """
    fields: Dict[str, Type] = {}
    defaults: Dict[str, Any] = {}  # noqa: E704 (flake8 bug)
    for subcls in iter_mro_reversed(cls, stop=stop):
        defaults.update(subcls.__dict__)
        with suppress(AttributeError):
            fields.update(
                local_annotations(
                    subcls,
                    invalid_types=invalid_types,
                    alias_types=alias_types,
                    skip_classvar=skip_classvar,
                    globalns=globalns,
                    localns=localns,
                )
            )
    return fields, defaults


def local_annotations(
    cls: Type,
    *,
    invalid_types: Set = None,
    alias_types: Mapping = None,
    skip_classvar: bool = False,
    globalns: Dict[str, Any] = None,
    localns: Dict[str, Any] = None,
) -> Iterable[Tuple[str, Type]]:
    return _resolve_refs(
        cls.__annotations__,
        globalns if globalns is not None else _get_globalns(cls),
        localns,
        invalid_types or set(),
        alias_types or {},
        skip_classvar,
    )


def _resolve_refs(
    d: Dict[str, Any],
    globalns: Dict[str, Any] = None,
    localns: Dict[str, Any] = None,
    invalid_types: Set = None,
    alias_types: Mapping = None,
    skip_classvar: bool = False,
) -> Iterable[Tuple[str, Type]]:
    invalid_types = invalid_types or set()
    alias_types = alias_types or {}
    for k, v in d.items():
        v = eval_type(v, globalns, localns, invalid_types, alias_types)
        if skip_classvar and _is_class_var(v):
            pass
        else:
            yield k, v


def eval_type(
    typ: Any,
    globalns: Dict[str, Any] = None,
    localns: Dict[str, Any] = None,
    invalid_types: Set = None,
    alias_types: Mapping = None,
) -> Type:
    """Convert (possible) string annotation to actual type.

    Examples:
        >>> eval_type('List[int]') == typing.List[int]
    """
    invalid_types = invalid_types or set()
    alias_types = alias_types or {}
    if isinstance(typ, str):
        typ = ForwardRef(typ)
    if isinstance(typ, ForwardRef):
        # On 3.6/3.7 _eval_type crashes if str references ClassVar
        typ = _ForwardRef_safe_eval(typ, globalns, localns)
    typ = _eval_type(typ, globalns, localns)
    if typ in invalid_types:
        raise InvalidAnnotation(typ)
    return alias_types.get(typ, typ)


def _ForwardRef_safe_eval(
    ref: ForwardRef, globalns: Dict[str, Any] = None, localns: Dict[str, Any] = None
) -> Type:
    # On 3.6/3.7 ForwardRef._evaluate crashes if str references ClassVar
    if not ref.__forward_evaluated__:
        if globalns is None and localns is None:
            globalns = localns = {}
        elif globalns is None:
            globalns = localns
        elif localns is None:
            localns = globalns
        val = eval(ref.__forward_code__, globalns, localns)  # noqa: S307
        if not _is_class_var(val):
            val = _type_check(val, "Forward references must evaluate to types.")
        ref.__forward_value__ = val
        ref.__forward_evaluated__ = True
    return ref.__forward_value__


def _get_globalns(typ: Type) -> Dict[str, Any]:
    return sys.modules[typ.__module__].__dict__


def iter_mro_reversed(cls: Type, stop: Type) -> Iterable[Type]:
    """Iterate over superclasses, in reverse Method Resolution Order.

    The stop argument specifies a base class that when seen will
    stop iterating (well actually start, since this is in reverse, see Example
    for demonstration).

    Arguments:
        cls (Type): Target class.
        stop (Type): A base class in which we stop iteration.

    Notes:
        The last item produced will be the class itself (`cls`).

    Examples:
        >>> class A: ...
        >>> class B(A): ...
        >>> class C(B): ...

        >>> list(iter_mro_reverse(C, object))
        [A, B, C]

        >>> list(iter_mro_reverse(C, A))
        [B, C]

    Yields:
        Iterable[Type]: every class.
    """
    wanted = False
    for subcls in reversed(cls.__mro__):
        if wanted:
            yield cast(Type, subcls)
        else:
            wanted = subcls == stop


def remove_optional(typ: Type) -> Type:
    _, typ = _remove_optional(typ)
    return typ


def is_union(typ: Type) -> bool:
    name = typ.__class__.__name__
    return any(
        [
            name == "_UnionGenericAlias",  # 3.9
            name == "_GenericAlias" and typ.__origin__ is typing.Union,  # 3.7
            name == "_Union",  # 3.6
        ],
    )


def is_optional(typ: Type) -> bool:
    if is_union(typ):
        args = getattr(typ, "__args__", ())
        return any([True for arg in args if arg is None or arg is type(None)])  # noqa
    return False


def _remove_optional(typ: Type, *, find_origin: bool = False) -> Tuple[List[Any], Type]:
    args = getattr(typ, "__args__", ())
    if is_union(typ):
        # 3.7+: Optional[List[int]] -> Union[List[int], NoneType]
        # 3.6:  Optional[List[int]] -> Union[List[int], type(None)]
        # returns: ((int,), list)
        found_None = False
        union_type_args: Optional[List] = None
        union_type: Optional[Type] = None
        for arg in args:
            if arg is None or arg is type(None):  # noqa
                found_None = True
            else:
                union_type_args = getattr(arg, "__args__", ())
                union_type = arg
                if find_origin:
                    if union_type is not None and sys.version_info.minor == 6:
                        union_type = _py36_maybe_unwrap_GenericMeta(union_type)
                    else:
                        union_type = getattr(arg, "__origin__", arg)
        if union_type is not None and found_None:
            return cast(List, union_type_args), union_type
    if find_origin:
        if hasattr(typ, "__origin__"):
            # List[int] -> ((int,), list)
            typ = _py36_maybe_unwrap_GenericMeta(typ)

    return args, typ


def _py36_maybe_unwrap_GenericMeta(typ: Type) -> Type:
    if typ.__class__.__name__ == "GenericMeta":  # Py3.6
        orig_bases = typ.__orig_bases__
        if orig_bases and orig_bases[0] in (list, tuple, dict, set):
            return cast(Type, orig_bases[0])
    return cast(Type, getattr(typ, "__origin__", typ))


def guess_polymorphic_type(
    typ: Type,
    *,
    set_types: Tuple[Type, ...] = SET_TYPES,
    list_types: Tuple[Type, ...] = LIST_TYPES,
    tuple_types: Tuple[Type, ...] = TUPLE_TYPES,
    dict_types: Tuple[Type, ...] = DICT_TYPES,
) -> Tuple[Type, Type]:
    """Try to find the polymorphic and concrete type of an abstract type.

    Returns tuple of ``(polymorphic_type, concrete_type)``.

    Examples:
        >>> guess_polymorphic_type(List[int])
        (list, int)

        >>> guess_polymorphic_type(Optional[List[int]])
        (list, int)

        >>> guess_polymorphic_type(MutableMapping[int, str])
        (dict, str)
    """
    args, typ = _remove_optional(typ, find_origin=True)
    if typ is not str and typ is not bytes:
        if issubclass(typ, tuple_types):
            # Tuple[x]
            return tuple, _unary_type_arg(args)
        elif issubclass(typ, set_types):
            # Set[x]
            return set, _unary_type_arg(args)
        elif issubclass(typ, list_types):
            # List[x]
            return list, _unary_type_arg(args)
        elif issubclass(typ, dict_types):
            # Dict[_, x]
            return dict, args[1] if args and len(args) > 1 else Any
    raise TypeError(f"Not a generic type: {typ!r}")


guess_concrete_type = guess_polymorphic_type  # XXX compat


def _unary_type_arg(args: List[Type]) -> Any:
    return args[0] if args else Any


def label(s: Any) -> str:
    """Return the name of an object as string."""
    return _label("label", s)


def shortlabel(s: Any) -> str:
    """Return the shortened name of an object as string."""
    return _label("shortlabel", s)


def _label(
    label_attr: str,
    s: Any,
    pass_types: Tuple[Type, ...] = (str,),
    str_types: Tuple[Type, ...] = (str, int, float, Decimal),
) -> str:
    if isinstance(s, pass_types):
        return cast(str, s)
    elif isinstance(s, str_types):
        return str(s)
    return str(
        getattr(s, label_attr, None)
        or getattr(s, "name", None)
        or getattr(s, "__qualname__", None)
        or getattr(s, "__name__", None)
        or getattr(type(s), "__qualname__", None)
        or type(s).__name__
    )


class cached_property(Generic[RT]):
    """Cached property.

    A property descriptor that caches the return value
    of the get function.

    Examples:
        .. sourcecode:: python

            @cached_property
            def connection(self):
                return Connection()

            @connection.setter  # Prepares stored value
            def connection(self, value):
                if value is None:
                    raise TypeError('Connection must be a connection')
                return value

            @connection.deleter
            def connection(self, value):
                # Additional action to do at del(self.attr)
                if value is not None:
                    print(f'Connection {value!r} deleted')
    """

    def __init__(
        self,
        fget: Callable[[Any], RT],
        fset: Callable[[Any, RT], RT] = None,
        fdel: Callable[[Any, RT], None] = None,
        doc: str = None,
        class_attribute: str = None,
    ) -> None:
        self.__get: Callable[[Any], RT] = fget
        self.__set: Optional[Callable[[Any, RT], RT]] = fset
        self.__del: Optional[Callable[[Any, RT], None]] = fdel
        self.__doc__ = doc or fget.__doc__
        self.__name__ = fget.__name__
        self.__module__ = fget.__module__
        self.class_attribute: Optional[str] = class_attribute

    def is_set(self, obj: Any) -> bool:
        return self.__name__ in obj.__dict__

    def __get__(self, obj: Any, type: Type = None) -> RT:
        if obj is None:
            if type is not None and self.class_attribute:
                return cast(RT, getattr(type, self.class_attribute))
            return cast(RT, self)  # just have to cast this :-(
        try:
            return cast(RT, obj.__dict__[self.__name__])
        except KeyError:
            value = obj.__dict__[self.__name__] = self.__get(obj)
            return value

    def __set__(self, obj: Any, value: RT) -> None:
        if self.__set is not None:
            value = self.__set(obj, value)
        obj.__dict__[self.__name__] = value

    def __delete__(self, obj: Any, _sentinel: Any = object()) -> None:
        value = obj.__dict__.pop(self.__name__, _sentinel)
        if self.__del is not None and value is not _sentinel:
            self.__del(obj, value)

    def setter(self, fset: Callable[[Any, RT], RT]) -> "cached_property":
        return self.__class__(self.__get, fset, self.__del)

    def deleter(self, fdel: Callable[[Any, RT], None]) -> "cached_property":
        return self.__class__(self.__get, self.__set, fdel)
