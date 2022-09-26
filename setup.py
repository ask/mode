#!/usr/bin/env python
# -*- coding: utf-8 -*-

import re
import sys

try:
    import platform

    _pyimp = platform.python_implementation
except (AttributeError, ImportError):

    def _pyimp():
        return "Python"


from setuptools import find_packages, setup

NAME = "mode-streaming"
EXTENSIONS = {"eventlet", "gevent", "uvloop"}
E_UNSUPPORTED_PYTHON = "%s 1.0 requires %%s %%s or later!" % (NAME,)  # noqa: S001

PYIMP = _pyimp()
if sys.version_info < (3, 6):
    raise Exception(E_UNSUPPORTED_PYTHON % (PYIMP, "3.6"))  # noqa: S001

from pathlib import Path  # noqa

README = Path("README.rst")

# -*- Classifiers -*-

classes = """
    Development Status :: 4 - Beta
    License :: OSI Approved :: BSD License
    Programming Language :: Python :: 3 :: Only
    Programming Language :: Python :: 3.6
    Programming Language :: Python :: 3.7
    Programming Language :: Python :: 3.8
    Programming Language :: Python :: 3.9
    Programming Language :: Python :: 3.10
    Programming Language :: Python :: Implementation :: CPython
    Operating System :: POSIX
    Operating System :: Microsoft :: Windows
    Operating System :: MacOS :: MacOS X
    Operating System :: Unix
    Environment :: No Input/Output (Daemon)
    Framework :: AsyncIO
    Intended Audience :: Developers
"""
classifiers = [s.strip() for s in classes.split("\n") if s]

# -*- Distribution Meta -*-

re_meta = re.compile(r"__(\w+?)__\s*=\s*(.*)")
re_doc = re.compile(r'^"""(.+?)"""')


def add_default(m):
    attr_name, attr_value = m.groups()
    return ((attr_name, attr_value.strip("\"'")),)


def add_doc(m):
    return (("doc", m.groups()[0]),)


pats = {re_meta: add_default, re_doc: add_doc}
here = Path(__file__).parent.absolute()
with open(here / "mode" / "__init__.py") as meta_fh:
    meta = {}
    for line in meta_fh:
        if line.strip() == "# -eof meta-":
            break
        for pattern, handler in pats.items():
            m = pattern.match(line.strip())
            if m:
                meta.update(handler(m))

# -*- Installation Requires -*-


def strip_comments(line):
    return line.split("#", 1)[0].strip()


def _pip_requirement(req):
    if req.startswith("-r "):
        _, path = req.split()
        return reqs(*path.split("/"))
    return [req]


def _reqs(*f):
    path = (Path.cwd() / "requirements").joinpath(*f)
    reqs = (strip_comments(line) for line in path.open().readlines())
    return [_pip_requirement(r) for r in reqs if r]


def reqs(*f):
    return [req for subreq in _reqs(*f) for req in subreq]


def extras(*p):
    """Parse requirement in the requirements/extras/ directory."""
    return reqs("extras", *p)


def extras_require():
    """Get map of all extra requirements."""
    return {x: extras(x + ".txt") for x in EXTENSIONS}


# -*- Long Description -*-


if README.exists():
    long_description = README.read_text(encoding="utf-8")
else:
    long_description = "See http://pypi.org/project/{}".format(NAME)

# -*- %%% -*-

packages = find_packages(
    exclude=["t", "t.*", "docs", "docs.*", "examples", "examples.*"],
)
assert not any(package.startswith("t.") for package in packages)


setup(
    name=NAME,
    version=meta["version"],
    description=meta["doc"],
    author=meta["author"],
    author_email=meta["contact"],
    url=meta["homepage"],
    platforms=["any"],
    license="BSD",
    keywords="asyncio service bootsteps graph coroutine",
    packages=packages,
    include_package_data=True,
    # PEP-561: https://www.python.org/dev/peps/pep-0561/
    package_data={"mode": ["py.typed"]},
    zip_safe=False,
    install_requires=reqs("default.txt"),
    tests_require=reqs("test.txt"),
    extras_require=extras_require(),
    python_requires="~=3.6",
    classifiers=classifiers,
    long_description=long_description,
    long_description_content_type="text/x-rst",
)
