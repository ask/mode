import os
import sys
from contextlib import contextmanager
from unittest.mock import Mock, call, patch

import pytest

from mode.utils.imports import (
    EntrypointExtension,
    FactoryMapping,
    RawEntrypointExtension,
    _ensure_identifier,
    cwd_in_path,
    import_from_cwd,
    load_extension_class_names,
    load_extension_classes,
    smart_import,
    symbol_by_name,
)
from mode.utils.mocks import mask_module


class test_FactoryMapping:
    @pytest.fixture()
    def map(self):
        return FactoryMapping(
            {
                "redis": "my.drivers.RedisDriver",
                "rabbitmq": "my.drivers.RabbitDriver",
            }
        )

    def test_constructor(self, *, map):
        assert map.aliases["redis"]
        assert map.aliases["rabbitmq"]

    def test_iterate(self, *, map):
        map.by_name = Mock(name="by_name")
        map._maybe_finalize = Mock()
        classes = list(map.iterate())
        map._maybe_finalize.assert_called_once_with()
        map.by_name.assert_has_calls([call("redis"), call("rabbitmq")])
        assert classes == [map.by_name(), map.by_name()]

    def test_by_url(self, *, map):
        map.by_name = Mock(name="by_name")
        cls = map.by_url("redis://localhost:6379//1")
        assert cls is map.by_name.return_value
        map.by_name.assert_called_once_with("redis")

    def test_by_name(self, *, map):
        map._maybe_finalize = Mock()
        with patch("mode.utils.imports.symbol_by_name") as sbn:
            cls = map.by_name("redis")
            assert cls is sbn.return_value
            sbn.assert_called_once_with("redis", aliases=map.aliases)
        map._maybe_finalize.assert_called_once_with()

    def test_by_name__ModuleNotFound(self, *, map):
        map._maybe_finalize = Mock()
        with patch("mode.utils.imports.symbol_by_name") as sbn:
            sbn.side_effect = ModuleNotFoundError()
            with pytest.raises(ModuleNotFoundError):
                map.by_name("redis")
        map._maybe_finalize.assert_called_once_with()

    def test_by_name__ModuleNotFound_dotname(self, *, map):
        map._maybe_finalize = Mock()
        with patch("mode.utils.imports.symbol_by_name") as sbn:
            sbn.side_effect = ModuleNotFoundError()
            with pytest.raises(ModuleNotFoundError):
                map.by_name("redis.foo")
        map._maybe_finalize.assert_called_once_with()

    def test_get_alias(self, *, map):
        map._maybe_finalize = Mock()
        assert map.get_alias("redis") == "my.drivers.RedisDriver"
        map._maybe_finalize.assert_called_once_with()

    def test_include_setuptools_namespace(self, *, map):
        map.include_setuptools_namespace("foo.bar.baz")
        assert "foo.bar.baz" in map.namespaces

    def test__maybe_finalize(self, *, map):
        map._finalize = Mock()
        map._finalized = True
        map._maybe_finalize()
        map._finalize.assert_not_called()
        map._finalized = False
        map._maybe_finalize()
        map._finalize.assert_called_once_with()

    def test__finalize(self, *, map):
        map.namespaces = {"foo"}
        with patch_iter_entry_points():
            map._finalize()
        assert map.aliases["ep1"] == "foo:a"
        assert map.aliases["ep2"] == "bar:c"

    def test_data(self, *, map):
        assert map.data is map.aliases


def test__ensure_identifier():
    with pytest.raises(ValueError):
        _ensure_identifier("foo.bar.{baz}", "full")


class test_symbol_by_name:
    @pytest.fixture()
    def imp(self):
        return Mock(name="imp")

    def test_missing_module(self):
        with pytest.raises(ValueError):
            symbol_by_name(":foo")

    def test_missing_module_but_valid_package(self):
        from mode.utils import logging

        assert symbol_by_name(".logging", package="mode.utils") is logging

    def test_already_object(self):
        obj = object()
        assert symbol_by_name(obj) is obj

    def test_when_ValueError(self, *, imp):
        imp.side_effect = ValueError
        with pytest.raises(ValueError):
            symbol_by_name("foo.bar:Baz", imp=imp)

    @pytest.mark.parametrize("exc", [AttributeError, ImportError])
    def test_when_ImportError(self, exc, *, imp):
        imp.side_effect = exc()
        with pytest.raises(exc):
            symbol_by_name("foo.bar:Baz", imp=imp, default=None)

    @pytest.mark.parametrize("exc", [AttributeError, ImportError])
    def test_when_ImportError__with_default(self, exc, *, imp):
        imp.side_effect = exc()
        assert symbol_by_name("foo.bar:Baz", imp=imp, default="f") == "f"

    def test_module(self):
        assert symbol_by_name("os") is os

    def test_symbol_by_name__module_attr(self):
        assert symbol_by_name("sys.version_info") is sys.version_info
        assert symbol_by_name("sys:version_info") is sys.version_info


def test_smart_import():
    assert smart_import("os") is os
    assert smart_import("sys:version_info") is sys.version_info
    assert smart_import("sys.version_info")

    with pytest.raises(AttributeError):
        smart_import("sys:foobarbazbazasdqwewqrewqfadf")


def test_load_extension_classes():
    with patch_iter_entry_points():
        with patch("mode.utils.imports.symbol_by_name") as sbn:
            assert list(load_extension_classes("foo")) == [
                EntrypointExtension("ep1", sbn.return_value),
                EntrypointExtension("ep2", sbn.return_value),
            ]

            sbn.assert_has_calls([call("foo:a"), call("bar:c")])


def test_load_extension_classes_syntax_error():
    with patch_iter_entry_points():
        with patch("mode.utils.imports.symbol_by_name") as sbn:
            sbn.side_effect = SyntaxError()
            with pytest.warns(UserWarning):
                assert list(load_extension_classes("foo")) == []


def test_load_extension_class_names():
    with patch_iter_entry_points():
        assert list(load_extension_class_names("foo")) == [
            RawEntrypointExtension(
                "ep1",
                "foo:a",
            ),
            RawEntrypointExtension(
                "ep2",
                "bar:c",
            ),
        ]


@contextmanager
def patch_iter_entry_points():
    with patch("pkg_resources.iter_entry_points") as iter_entry_points:
        ep1 = Mock(name="ep1")
        ep1.name = "ep1"
        ep1.module_name = "foo"
        ep1.attrs = ["a", "b"]
        ep2 = Mock(name="ep2")
        ep2.name = "ep2"
        ep2.module_name = "bar"
        ep2.attrs = ["c", "d"]
        iter_entry_points.return_value = [
            ep1,
            ep2,
        ]
        yield


def test_load_extension_class_names__no_pkg_resources():
    with mask_module("pkg_resources"):
        assert list(load_extension_class_names("foo")) == []


def test_cwd_in_path():
    with patch("os.getcwd") as getcwd:
        getcwd.return_value = "bar"
        with patch("sys.path", ["foo", "moo", "baz"]):
            with cwd_in_path():
                assert "bar" in sys.path
            assert "bar" not in sys.path


def test_cwd_in_path__already_in_path():
    with patch("os.getcwd") as getcwd:
        getcwd.return_value = "bar"
        with patch("sys.path", ["foo", "bar", "baz"]):
            with cwd_in_path():
                assert "bar" in sys.path
            assert "bar" in sys.path


def test_import_from_cwd():
    with patch("mode.utils.imports.cwd_in_path"):
        with patch("importlib.import_module") as import_module:
            res = import_from_cwd(".foo", package="baz")
            assert res is import_module.return_value
            import_module.assert_called_once_with(".foo", package="baz")


def test_import_from_cwd__custom_imp():
    imp = Mock(name="imp")
    with patch("importlib.import_module"):
        res = import_from_cwd(".foo", package="baz", imp=imp)
        assert res is imp.return_value
        imp.assert_called_once_with(".foo", package="baz")
