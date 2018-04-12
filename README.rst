=====================================================================
 Mode: AsyncIO Services
=====================================================================

|build-status| |license| |wheel| |pyversion| |pyimp|

:Version: 1.10.3
:Web: http://mode.readthedocs.org/
:Download: http://pypi.python.org/pypi/mode
:Source: http://github.com/fauststream/mode
:Keywords: async, service, framework, actors, bootsteps, graph

What is Mode?
=============

Mode is a library for Python AsyncIO, using the new ``async/await`` syntax
in Python 3.6 to define your program as a set of services.

When writing projects using ``asyncio``, a pattern emerged where we'd base
our program on one or more services. These behave much like actors in Erlang,
but implemented as classes:

A service is just a class::

    class PageViewCache(Service):
        redis: Redis = None

        async def on_start(self) -> None:
            self.redis = connect_to_redis()

        async def update(self, url: str, n: int = 1) -> int:
            return await self.redis.incr(url, n)

        async def get(self, url: str) -> int:
            return await self.redis.get(url)


Services are started, stopped and restarted; and they can
start other services, define background tasks, timers, and more::

    class App(Service):
        page_view_cache: PageViewCache = None

        async def on_start(self) -> None:
            await self.add_runtime_dependency(self.page_view_cache)

        @cached_property
        def page_view_cache(self) -> PageViewCache:
            return PageViewCache()


Services
    can depend on other services::

        class App(Service):

            def on_init_dependencies(self) -> None:
                return [
                    self.websockets,
                    self.webserver,
                    self.user_cache,
                ]

            async def on_start(self) -> None:
                print('App is starting')

Graph
    If we fill out the rest of this code to implement the additional
    services.

    A service managing our websocket server:

        class Websockets(Service):

            def __init__(self, port: int = 8081, **kwargs: Any) -> None:
                self.port = 8081
                self._server = None
                super().__init__(**kwargs)

            async def on_start(self) -> None:
                self._server = websockets.run()

            async def on_stop(self) -> None:
                if self._server is not None:
                    self._server.close()

    Then a web server, run in a separate thread using ``ServiceThread``::

        from aiohttp.web import Application
        from mode.threads import ServiceThread

        class Webserver(ServiceThread):

            def __init__(self,
                         port: int = 8000,
                         bind: str = None,
                         **kwargs: Any) -> None:
                self._app = Application()
                self.port = port
                self.bind = bind
                self._handler = None
                self._srv = None
                super().__init__(**kwargs)

            async def on_start(self) -> None:
                handler = self._handler = self._app.make_handler()
                # self.loop is the event loop in this thread
                #   self.parent_loop is the loop that created this thread.
                self._srv = await self.loop.create_server(
                    handler, self.bind, self.port)
                self.log.info('Serving on port %s', self.port)

            async def on_thread_stop(self) -> None:
                # see examples/tutorial.py for an actual example
                self._srv.stop()

    Third, our user cache, which has a background coroutine used to
    remove old expired items from the cache::

        class UserCache(Service):
            _cache: MutableMapping[str, User]

            def on_init(self):
                self._cache = {}

            async def lookup(self, user_id: str) -> User:
                try:
                    return self._cache[user_id]
                except KeyError:
                    user = self._cache[user_id] = await User.objects.get(user_id)
                    return user

            @Service.timer(10)  # execute every 10 seconds.
            def _remove_expired(self):
                remove_expired_users(self._cache)

Proxy
    Now we just need to create these services in our "App" class.

    In our little tutorial example the "app" is the entrypoint for
    our program.  Mode does not have a concept of apps, so we don't
    subclass anything, but we want the app to be reusable in projects
    and keep it possible to start multiple apps at the same time.

    If we create apps at module scope, for example::

        # example/app.py
        from our_library import App
        app = App(web_port=6066)

    It is very important to instantiate services lazily, otherwise
    the ``asyncio`` event loop is created too early.

    For services that are defined at module level we can create a
    ``ServiceProxy``::

        from typing import Any

        from mode import Service, ServiceProxy, ServiceT
        from mode.utils.objects import cached_property

        class AppService(Service):
            # the "real" service that App.start() will run

            def __init__(self, app: 'App', **kwargs: Any) -> None:
                self.app = app
                super().__init__(**kwargs)

            def on_init_dependencies(self) -> None:
                return [
                    self.app.websockets,
                    self.app.webserver,
                    self.app.user_cache,
                ]

            async def on_start(self) -> None:
                print('App is starting')

        class App(ServiceProxy):

            def __init__(self,
                         web_port: int = 8000,
                         web_bind: str = None,
                         websocket_port: int = 8001,
                         **kwargs: Any) -> None:
                self.web_port = web_port
                self.web_bind = web_bind
                self.websocket_port = websocket_port

            @cached_property
            def _service(self) -> ServiceT:
                return AppService(self)

            @cached_property
            def websockets(self) -> Websockets:
                return Websockets(
                    port=self.websocket_port,
                    loop=self.loop,
                    beacon=self.beacon,
                )

            @cached_property
            def webserver(self) -> Webserver:
                return Webserver(
                    port=self.web_port,
                    bind=self.web_bind,
                    loop=self.loop,
                    beacon=self.beacon,
                )

            @cached_property
            def user_cache(self) -> UserCache:
                return UserCache(loop=self.loop, beacon=self.beacon)

Worker
    To start your service on the command-line, add an
    entrypoint for a ``Worker`` to start it::

        app = App()

        if __name__ == '__main__':
            from mode import Worker
            Worker(app, loglevel="info").execute_from_commandline()

    Then execute your program to start the worker::

        $ python examples/tutorial.py
        [2018-03-27 15:47:12,159: INFO]: [^Worker]: Starting...
        [2018-03-27 15:47:12,160: INFO]: [^-AppService]: Starting...
        [2018-03-27 15:47:12,160: INFO]: [^--Websockets]: Starting...
        STARTING WEBSOCKET SERVER
        [2018-03-27 15:47:12,161: INFO]: [^--UserCache]: Starting...
        [2018-03-27 15:47:12,161: INFO]: [^--Webserver]: Starting...
        [2018-03-27 15:47:12,164: INFO]: [^--Webserver]: Serving on port 8000
        REMOVING EXPIRED USERS
        REMOVING EXPIRED USERS

    To stop it hit ``Control-c``::

        [2018-03-27 15:55:08,084: INFO]: [^Worker]: Stopping on signal received...
        [2018-03-27 15:55:08,084: INFO]: [^Worker]: Stopping...
        [2018-03-27 15:55:08,084: INFO]: [^-AppService]: Stopping...
        [2018-03-27 15:55:08,084: INFO]: [^--UserCache]: Stopping...
        REMOVING EXPIRED USERS
        [2018-03-27 15:55:08,085: INFO]: [^Worker]: Gathering service tasks...
        [2018-03-27 15:55:08,085: INFO]: [^--UserCache]: -Stopped!
        [2018-03-27 15:55:08,085: INFO]: [^--Webserver]: Stopping...
        [2018-03-27 15:55:08,085: INFO]: [^Worker]: Gathering all futures...
        [2018-03-27 15:55:08,085: INFO]: [^--Webserver]: Closing server
        [2018-03-27 15:55:08,086: INFO]: [^--Webserver]: Waiting for server to close handle
        [2018-03-27 15:55:08,086: INFO]: [^--Webserver]: Shutting down web application
        [2018-03-27 15:55:08,086: INFO]: [^--Webserver]: Waiting for handler to shut down
        [2018-03-27 15:55:08,086: INFO]: [^--Webserver]: Cleanup
        [2018-03-27 15:55:08,086: INFO]: [^--Webserver]: -Stopped!
        [2018-03-27 15:55:08,086: INFO]: [^--Websockets]: Stopping...
        [2018-03-27 15:55:08,086: INFO]: [^--Websockets]: -Stopped!
        [2018-03-27 15:55:08,087: INFO]: [^-AppService]: -Stopped!
        [2018-03-27 15:55:08,087: INFO]: [^Worker]: -Stopped!

Beacons
    The ``beacon`` object that we pass to services keeps track of the services
    in a graph.

    They are not stricly required, but can be used to visualize a running
    system, for example we can render it as a pretty graph.

    This requires you to have the ``pydot`` library and GraphViz
    installed::

        $ pip install pydot

    Let's change the app service class to dump the graph to an image
    at startup.

        class AppService(Service):

            async def on_start(self) -> None:
                print('APP STARTING')
                import pydot
                import io
                o = io.StringIO()
                beacon = self.app.beacon.root or self.app.beacon
                beacon.as_graph().to_dot(o)
                graph, = pydot.graph_from_dot_data(o.getvalue())
                print('WRITING GRAPH TO image.png')
                with open('image.png', 'wb') as fh:
                    fh.write(graph.create_png())


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
        import mode
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

