# -*- coding: utf-8 -*-
import sys
from contextlib import suppress
from sphinx_celery import conf

sys.path.append('.')

globals().update(conf.build_config(
    'mode', __file__,
    project='Mode',
    # version_dev='2.0',
    # version_stable='1.4',
    canonical_url='http://mode.readthedocs.io',
    webdomain='',
    github_project='fauststream/mode',
    copyright='2017',
    html_logo='images/logo.png',
    html_favicon='images/favicon.ico',
    html_prepend_sidebars=[],
    include_intersphinx={'python', 'sphinx'},
    extra_extensions=[
        'sphinx.ext.napoleon',
        'sphinx_autodoc_annotation',
        'sphinxcontrib.asyncio',
        'alabaster',
    ],
    extra_intersphinx_mapping={
    },
    # django_settings='testproj.settings',
    # from pathlib import Path
    # path_additions=[Path.cwd().parent / 'testproj']
    apicheck_ignore_modules=[
        'mode.loop.eventlet',
        'mode.loop.gevent',
        'mode.loop.uvloop',
        'mode.loop._gevent_loop',
        'mode.utils.graphs.formatter',
        'mode.utils.graphs.graph',
    ],
))

html_theme = 'alabaster'
html_sidebars = {}
templates_path = ['_templates']

autodoc_member_order = 'bysource'

pygments_style = 'sphinx'

# This option is deprecated and raises an error.
with suppress(NameError):
    del(html_use_smartypants)  # noqa
