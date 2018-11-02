# This is code for the tutorial in README.rst
from typing import Any, MutableMapping

from aiohttp.web import Application
from mode import Service
from mode.threads import ServiceThread
from mode.utils.objects import cached_property


class User:
    ...  # implement yourself


def remove_expired_users(d):
    print('REMOVING EXPIRED USERS')
    ...  # implement yourself


async def run_websocket_server():
    print('STARTING WEBSOCKET SERVER')
    ...  # implement yourself


class Websockets(Service):

    def __init__(self, port: int = 8081, **kwargs: Any) -> None:
        self.port = 8081
        self._server = None
        super().__init__(**kwargs)

    async def on_start(self) -> None:
        self._server = await run_websocket_server()

    async def on_stop(self) -> None:
        if self._server is not None:
            self._server.close()


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
        # on_thread_stop() executes in the thread.
        # on_stop() executes in parent thread.

        # quite a few steps required to stop the aiohttp server:
        if self._srv is not None:
            self.log.info('Closing server')
            self._srv.close()
            self.log.info('Waiting for server to close handle')
            await self._srv.wait_closed()
        if self._app is not None:
            self.log.info('Shutting down web application')
            await self._app.shutdown()
        if self._handler is not None:
            self.log.info('Waiting for handler to shut down')
            await self._handler.shutdown(60.0)
        if self._app is not None:
            self.log.info('Cleanup')
            await self._app.cleanup()


class UserCache(Service):
    _cache: MutableMapping[str, User]

    def __post_init__(self):
        self._cache = {}

    async def lookup(self, user_id: str) -> User:
        try:
            return self._cache[user_id]
        except KeyError:
            user = self._cache[user_id] = await User.objects.get(user_id)
            return user

    @Service.timer(10)  # execute every 10 seconds.
    async def _remove_expired(self):
        remove_expired_users(self._cache)


class App(Service):

    def __init__(self,
                 web_port: int = 8000,
                 web_bind: str = None,
                 websocket_port: int = 8001,
                 **kwargs: Any) -> None:
        self.web_port = web_port
        self.web_bind = web_bind
        self.websocket_port = websocket_port
        super().__init__(**kwargs)

    def on_init_dependencies(self) -> None:
        return [
            self.app.websockets,
            self.app.webserver,
            self.app.user_cache,
        ]

    async def on_start(self) -> None:
        import pydot
        import io
        o = io.StringIO()
        beacon = self.app.beacon.root or self.app.beacon
        beacon.as_graph().to_dot(o)
        graph, = pydot.graph_from_dot_data(o.getvalue())
        print('WRITING GRAPH TO image.png')
        with open('image.png', 'wb') as fh:
            fh.write(graph.create_png())

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


app = App()

if __name__ == '__main__':
    from mode.worker import Worker
    Worker(app, loglevel='info', daemon=True).execute_from_commandline()
