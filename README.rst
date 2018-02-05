=====================================================================
 Mode: AsyncIO Services
=====================================================================

|build-status| |license| |wheel| |pyversion| |pyimp|

:Version: 1.7.0
:Web: http://mode.readthedocs.org/
:Download: http://pypi.python.org/pypi/mode
:Source: http://github.com/fauststream/mode
:Keywords: async, service, framework, actors, bootsteps, graph

What is Mode?
=============

Mode is a library for Python AsyncIO, using the new ``async/await`` syntax
in Python 3.6 to define your program as a set of services.

When starting a larger project using ``asyncio``, it immediately became
apparent that we needed a way to manage the different services running in the
program.  Questions such as "how do we shutdown the event loop" is frequently
answered by telling users to "wait for all coroutines in
asyncio.Task.all_tasks", but we needed more control over what services
where stopped, in what order and what services can we safely shutdown without
waiting for current operations to complete.

So for us the answer was to create a generic ``Service`` class that handles
this for us, including creating pretty graphs of active services in the
system, and what they are currently doing.

Heavily inspired by Celery/RabbitMQ bootsteps, you could say it's a less
formal version of that, where the graph is built at runtime.

Creating a Service
==================

To define a service, simply subclass and fill in the methods
to do stuff as the service is started/stopped etc.::

    class MyService(Service):

        async def on_start(self) -> None:
            print('Im starting now')

        async def on_started(self) -> None:
            print('Im ready')

        async def on_stop(self) -> None:
            print('Im stopping now')

To start the service, call ``await service.start()``::

    await service.start()

Or you can use ``mode.Worker`` (or a subclass of this) to start your
services-based asyncio program from the console::

    if __name__ == '__main__':
        imoport mode
        worker = mode.Worker(MyService(), loglevel='INFO', logfile=None)
        worker.execute_from_commandline()

It's a Graph!
=============

Services can start other services, coroutines, and background tasks.

1) Starting other services using ``add_depenency``::

    class MyService(Service):

        def on_init(self) -> None:
           self.add_dependency(OtherService(loop=self.loop))

2) Start a list of services using ``on_init_dependencies``::

    class MyService(Service):

        def on_init_dependencies(self) -> None:
            return [
                ServiceA(loop=self.loop),
                ServiceB(loop=self.loop),
                ServiceC(loop=self.loop),
            ]

3) Start a future/coroutine (that will be waited on to complete on stop)::

    class MyService(Service):

        async def on_start(self) -> None:
            self.add_future(self.my_coro())

        async def my_coro(self) -> None:
            print('Executing coroutine')

4) Start a background task::

    class MyService(Service):

        @Service.task
        async def _my_coro(self) -> None:
            print('Executing coroutine')


5) Start a background task that keeps running::

    class MyService(Service):

        @Service.task
        async def _my_coro(self) -> None:
            while not self.should_stop:
                # NOTE: self.sleep will wait for one second, or
                #       until service stopped/crashed.
                await self.sleep(1.0)
                print('Background thread waking up')

.. _installation:

Installation
============

You can install Mode either via the Python Package Index (PyPI)
or from source.

To install using `pip`::

    $ pip install -U mode

.. _installing-from-source:

Downloading and installing from source
--------------------------------------

Download the latest version of Mode from
http://pypi.python.org/pypi/mode

You can install it by doing the following::

    $ tar xvfz mode-0.0.0.tar.gz
    $ cd mode-0.0.0
    $ python setup.py build
    # python setup.py install

The last command must be executed as a privileged user if
you are not currently using a virtualenv.

.. _installing-from-git:

Using the development version
-----------------------------

With pip
~~~~~~~~

You can install the latest snapshot of Mode using the following
pip command::

    $ pip install https://github.com/fauststream/Mode/zipball/master#egg=mode

FAQ
===

Can I use Mode with Django/Flask/etc.?
--------------------------------------

Yes! Use gevent/eventlet as a bridge to integrate with asyncio.

Using ``gevent``
~~~~~~~~~~~~~~~~

This works with any blocking Python library that can work with gevent.

Using gevent requires you to install the ``aiogevent`` module,
and you can install this as a bundle with Mode:

.. sourcecode:: console

    $ pip install -U mode[gevent]

Then to actually use gevent as the event loop you have to
execute the following in your entrypoint module (usually where you
start the worker), before any other third party libraries are imported::

    #!/usr/bin/env python3
    import mode.loop
    mode.loop.use('gevent')
    # execute program

REMEMBER: This must be located at the very top of the module,
in such a way that it executes before you import other libraries.


Using ``eventlet``
~~~~~~~~~~~~~~~~~~

This works with any blocking Python library that can work with eventlet.

Using eventlet requires you to install the ``aioeventlet`` module,
and you can install this as a bundle with Mode:

.. sourcecode:: console

    $ pip install -U mode[eventlet]

Then to actually use eventlet as the event loop you have to
execute the following in your entrypoint module (usually where you
start the worker), before any other third party libraries are imported::

    #!/usr/bin/env python3
    import mode.loop
    mode.loop.use('eventlet')
    # execute program

REMEMBER: It's very important this is at the very top of the module,
and that it executes before you import libraries.

Can I use Mode with Tornado?
----------------------------

Yes! Use the ``tornado.platform.asyncio`` bridge:
http://www.tornadoweb.org/en/stable/asyncio.html

Can I use Mode with Twisted?
-----------------------------

Yes! Use the asyncio reactor implementation:
https://twistedmatrix.com/documents/17.1.0/api/twisted.internet.asyncioreactor.html

Will you support Python 3.5 or earlier?
---------------------------------------

There are no immediate plans to support Python 3.5, but you are welcome to
contribute to the project.

Here are some of the steps required to accomplish this:

- Source code transformation to rewrite variable annotations to comments

  for example, the code::

        class Point:
            x: int = 0
            y: int = 0

   must be rewritten into::

        class Point:
            x = 0  # type: int
            y = 0  # type: int

- Source code transformation to rewrite async functions

    for example, the code::

        async def foo():
            await asyncio.sleep(1.0)

    must be rewritten into::

        @coroutine
        def foo():
            yield from asyncio.sleep(1.0)

Will you support Python 2?
--------------------------

There are no plans to support Python 2, but you are welcome to contribute to
the project (details in question above is relevant also for Python 2).

Code of Conduct
===============

Everyone interacting in the project's codebases, issue trackers, chat rooms,
and mailing lists is expected to follow the Mode Code of Conduct.

As contributors and maintainers of these projects, and in the interest of fostering
an open and welcoming community, we pledge to respect all people who contribute
through reporting issues, posting feature requests, updating documentation,
submitting pull requests or patches, and other activities.

We are committed to making participation in these projects a harassment-free
experience for everyone, regardless of level of experience, gender,
gender identity and expression, sexual orientation, disability,
personal appearance, body size, race, ethnicity, age,
religion, or nationality.

Examples of unacceptable behavior by participants include:

* The use of sexualized language or imagery
* Personal attacks
* Trolling or insulting/derogatory comments
* Public or private harassment
* Publishing other's private information, such as physical
  or electronic addresses, without explicit permission
* Other unethical or unprofessional conduct.

Project maintainers have the right and responsibility to remove, edit, or reject
comments, commits, code, wiki edits, issues, and other contributions that are
not aligned to this Code of Conduct. By adopting this Code of Conduct,
project maintainers commit themselves to fairly and consistently applying
these principles to every aspect of managing this project. Project maintainers
who do not follow or enforce the Code of Conduct may be permanently removed from
the project team.

This code of conduct applies both within project spaces and in public spaces
when an individual is representing the project or its community.

Instances of abusive, harassing, or otherwise unacceptable behavior may be
reported by opening an issue or contacting one or more of the project maintainers.

This Code of Conduct is adapted from the Contributor Covenant,
version 1.2.0 available at http://contributor-covenant.org/version/1/2/0/.

.. |build-status| image:: https://secure.travis-ci.org/fauststream/mode.png?branch=master
    :alt: Build status
    :target: https://travis-ci.org/fauststream/mode

.. |license| image:: https://img.shields.io/pypi/l/mode.svg
    :alt: BSD License
    :target: https://opensource.org/licenses/BSD-3-Clause

.. |wheel| image:: https://img.shields.io/pypi/wheel/mode.svg
    :alt: Mode can be installed via wheel
    :target: http://pypi.python.org/pypi/mode/

.. |pyversion| image:: https://img.shields.io/pypi/pyversions/mode.svg
    :alt: Supported Python versions.
    :target: http://pypi.python.org/pypi/mode/

.. |pyimp| image:: https://img.shields.io/pypi/implementation/mode.svg
    :alt: Supported Python implementations.
    :target: http://pypi.python.org/pypi/mode/

