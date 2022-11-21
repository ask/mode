import asyncio
import sys
from functools import partial
from typing import AsyncContextManager, ContextManager
from unittest.mock import ANY, MagicMock, Mock, call, patch

if sys.version_info < (3, 8):
    from mock.mock import AsyncMock
else:
    from unittest.mock import AsyncMock

import pytest

from mode import Service
from mode.services import Diag, ServiceTask, WaitResult
from mode.utils.logging import get_logger


class S(Service):
    def __post_init__(self):
        self.on_started_log = Mock()
        self.on_stopped_log = Mock()
        self.on_shutdown_log = Mock()

    async def on_start(self):
        self.on_started_log()

    async def on_stop(self):
        self.on_stopped_log()

    async def on_shutdown(self):
        self.on_shutdown_log()


class test_Diag:
    @pytest.fixture()
    def diag(self):
        service = Mock()
        return Diag(service)

    def test_set_unset_flag(self, *, diag):
        diag.set_flag("FOO")
        assert "FOO" in diag.flags
        assert diag.last_transition["FOO"]
        diag.unset_flag("FOO")
        assert "FOO" not in diag.flags


class test_ServiceTask:
    @pytest.fixture()
    def task(self):
        fun = AsyncMock()
        return ServiceTask(fun)

    @pytest.mark.asyncio
    async def test_call(self, *, task):
        obj = Mock()
        ret = await task(obj)
        assert ret is task.fun.return_value
        task.fun.assert_awaited_once_with(obj)

    def test_repr(self, *, task):
        assert repr(task) == repr(task.fun)


@pytest.mark.asyncio
async def test_start_stop():
    s = S()
    assert s.state == "init"
    assert await s.maybe_start()
    assert not await s.maybe_start()
    assert s.state == "running"
    s.on_started_log.assert_called_with()
    await s.stop()
    s.on_stopped_log.assert_called_with()
    s.on_shutdown_log.assert_called_with()
    assert s.state == "stopping"


def test_state_stopped():
    s = S()
    s._started.set()
    s._stopped.set()
    s._shutdown.set()
    assert s.state == "shutdown"


def test_should_stop_returns_true_if_crashed():
    s = S()
    s._crashed.set()
    assert s.should_stop


@pytest.mark.asyncio
async def test_aenter():
    s = S()
    async with s:
        s.on_started_log.assert_called_with()
    s.on_stopped_log.assert_called_with()
    s.on_shutdown_log.assert_called_with()


@pytest.mark.asyncio
async def test_interface():
    s = Service()
    s.__post_init__()
    await s.on_start()
    await s.on_stop()
    await s.on_shutdown()


def test_repr():
    assert repr(S())


@pytest.mark.asyncio
async def test_subclass_can_override_Service_task():
    class ATaskService(Service):
        values = []

        def __post_init__(self):
            self.event = asyncio.Event()

        @Service.task
        async def _background_task(self):
            self.values.append(1)
            self.event.set()

    class BTaskService(ATaskService):
        @Service.task
        async def _background_task(self):
            self.values.append(2)
            self.event.set()

    async with BTaskService() as service:
        await service.event.wait()

    assert ATaskService.values == [2]


class test_Service:
    @pytest.fixture()
    def service(self):
        return S()

    @pytest.mark.asyncio
    async def test_from_awaitable(self, *, service):
        foo = Mock()

        async def mywait():
            foo()

        s = service.from_awaitable(mywait())
        async with s:
            pass
        foo.assert_called_once_with()
        await s.on_stop()

    @pytest.mark.asyncio
    async def test_from_awaitable__sleeping_is_cancelled(self, *, service):
        foo = Mock()

        async def mywait():
            foo()
            asyncio.ensure_future(s.stop())
            await asyncio.sleep(10.0)

        s = service.from_awaitable(mywait())
        async with s:
            await s.stop()
            await asyncio.sleep(0)
            await asyncio.sleep(0)
        foo.assert_called_once_with()

    @pytest.mark.asyncio
    async def test_from_awaitable__raises_cancel(self, *, service):
        foo = Mock()

        async def mywait():
            foo()
            raise asyncio.CancelledError()

        s = service.from_awaitable(mywait())
        with pytest.raises(asyncio.CancelledError):
            async with s:
                pass
        foo.assert_called_once_with()

    @pytest.mark.asyncio
    async def test_timer(self):
        m = Mock()

        class Foo(Service):
            @Service.timer(1.0)
            async def foo(self):
                m()
                if m.call_count >= 3:
                    self._stopped.set()

        async def itertimer(*args, **kwargs):
            yield 0.1
            yield 0.2
            yield 0.3
            yield 0.4

        foo = Foo()
        foo.sleep = AsyncMock()
        foo.itertimer = itertimer
        async with foo:
            pass
        assert m.call_count == 4

    @pytest.mark.asyncio
    async def test_timer__not_to_wait_twice(self) -> None:
        m = Mock()

        class Foo(Service):
            @Service.timer(0.1)
            async def foo(self) -> None:
                m()
                if m.call_count >= 3:
                    self._stopped.set()

        async def itertimer(self, t, *args, **kwargs):
            for i in range(4):
                await self.sleep(t)
                yield

        foo = Foo()
        foo.sleep = AsyncMock()
        foo.itertimer = partial(itertimer, foo)
        async with foo:
            pass

        assert foo.sleep.call_count == 4
        assert m.call_count == 4

    @pytest.mark.asyncio
    async def test_timer__exec_first(self) -> None:
        m = Mock()

        class Foo(Service):
            @Service.timer(1.0, exec_first=True)
            async def foo(self) -> None:
                m()
                if m.call_count >= 3:
                    self._stopped.set()

        async def itertimer(*args, **kwargs):
            yield 0.1
            yield 0.2
            yield 0.3

        foo = Foo()
        foo.sleep = AsyncMock()
        foo.itertimer = itertimer
        async with foo:
            pass
        assert m.call_count == 4

    @pytest.mark.asyncio
    async def test_crontab(self):
        m = Mock()

        with patch("mode.services.secs_for_next") as secs_for_next:
            secs_for_next.secs_for_next.return_value = 0.1

            class Foo(Service):
                @Service.crontab("* * * * *")
                async def foo(self):
                    m()
                    self._stopped.set()

            foo = Foo()
            foo.sleep = AsyncMock()
            async with foo:
                await asyncio.sleep(0)

            m.assert_called_once_with()

    @pytest.mark.asyncio
    async def test_transitions_to(self, *, service):
        @service.transitions_to("FLAG")
        async def foo(self, arg, kw=1):
            assert "FLAG" in service.diag.flags
            assert arg == 1
            assert kw == 2

        await foo(service, 1, kw=2)
        assert "FLAG" not in service.diag.flags

    @pytest.mark.asyncio
    async def test_transition_with(self, *, service):
        called = Mock()

        async def outer():
            assert "FLAG" in service.diag.flags
            called()

        await service.transition_with("FLAG", outer())
        called.assert_called_once_with()

    def test_add_dependency__no_beacon(self, *, service):
        m = Mock()
        m.beacon = None
        service.add_dependency(m)

    @pytest.mark.asyncio
    async def test_add_runtime_dependency__when_started(self, *, service):
        s2 = Mock(maybe_start=AsyncMock())
        service.add_dependency = Mock()
        service._started.set()
        await service.add_runtime_dependency(s2)
        service.add_dependency.assert_called_once_with(s2)
        s2.maybe_start.assert_awaited_once_with()

    @pytest.mark.asyncio
    async def test_add_runtime_dependency__not_started(self, *, service):
        s2 = Mock(maybe_start=AsyncMock())
        service.add_dependency = Mock()
        service._started.clear()
        await service.add_runtime_dependency(s2)
        service.add_dependency.assert_called_once_with(s2)
        s2.maybe_start.assert_not_called()

    @pytest.mark.asyncio
    async def test_remove_dependency(self, *, service):
        s2 = Mock(stop=AsyncMock())
        service.add_dependency(s2)
        service._started.set()
        await service.remove_dependency(s2)
        s2.stop.assert_awaited_once_with()

    @pytest.mark.asyncio
    async def test_remove_dependency__no_beacon(self, *, service):
        s2 = Mock(stop=AsyncMock())
        s2.beacon = None
        service.add_dependency(s2)
        await service.remove_dependency(s2)

    @pytest.mark.asyncio
    async def test_add_async_context__non_async(self, *, service):
        class Cx(ContextManager):
            def __exit__(self, *args):
                return None

        assert isinstance(Cx(), ContextManager)

        with pytest.raises(TypeError):
            await service.add_async_context(Cx())

    @pytest.mark.asyncio
    async def test_add_async_context__not_context(self, *, service):
        with pytest.raises(TypeError):
            await service.add_async_context(object())

    def test_add_context__is_async(self, *, service):
        class Cx(AsyncContextManager):
            async def __aexit__(self, *args):
                return None

        assert isinstance(Cx(), AsyncContextManager)

        with pytest.raises(TypeError):
            service.add_context(Cx())

    def test_add_context__not_context(self, *, service):
        with pytest.raises(TypeError):
            service.add_context(object())

    @pytest.mark.asyncio
    async def test__wait_stopped(self, *, service):
        service._stopped = Mock()
        service._crashed = Mock()

        with patch("asyncio.wait", AsyncMock()) as wait, patch(
            "asyncio.ensure_future", Mock()
        ) as ensure_future:
            f1 = Mock()
            f2 = Mock()
            f3 = Mock()
            done, pending = wait.return_value = ((f1,), (f2, f3))

            await service._wait_stopped(timeout=1.0)

            service._stopped.wait.assert_called_once()
            service._crashed.wait.assert_called_once()

            ensure_future.assert_has_calls(
                [
                    call(service._stopped.wait.return_value, loop=service.loop),
                    call(service._crashed.wait.return_value, loop=service.loop),
                ]
            )

            stopped = ensure_future.return_value
            crashed = ensure_future.return_value
            wait.assert_called_once_with(
                [stopped, crashed],
                return_when=asyncio.FIRST_COMPLETED,
                timeout=1.0,
            )

            for fut in done:
                fut.result.assert_called_once_with()
            for fut in pending:
                fut.cancel.assert_called_once_with()

        service._crashed.is_set.assert_called_once_with()

    @pytest.mark.asyncio
    async def test__actually_start__add_dependencies(self, *, service):
        s1 = Mock()
        s2 = Mock()
        self._mock_for_start(service, init_deps=[s1, s2])
        service.on_first_start.side_effect = service._stopped.set
        await service._actually_start()
        service.add_dependency.assert_has_calls([call(s1), call(s2)])

    @pytest.mark.asyncio
    async def test__actually_start__second_stop(self, *, service):
        s1 = Mock()
        self._mock_for_start(
            service,
            init_deps=[s1],
            on_async_enter=service._stopped.set,
        )
        service.restart_count = 1
        await service._actually_start()

    @pytest.mark.asyncio
    async def test__actually_start__third_stop(self, *, service):
        s1 = Mock()
        self._mock_for_start(
            service,
            init_deps=[s1],
        )
        service.on_start.side_effect = service._stopped.set
        service.restart_count = 1
        await service._actually_start()

    @pytest.mark.asyncio
    async def test__actually_start__rasies_exc(self, *, service):
        s1 = Mock()
        self._mock_for_start(
            service,
            init_deps=[s1],
        )
        service.on_start.side_effect = KeyError("foo")
        service.restart_count = 1
        with pytest.raises(KeyError):
            await service._actually_start()

    @pytest.mark.asyncio
    async def test__actually_start__fourth_stop(self, *, service):
        s1 = Mock(maybe_start=AsyncMock())
        self._mock_for_start(
            service,
        )
        service._children = [s1]
        s1.maybe_start.side_effect = service._stopped.set
        service.restart_count = 1
        await service._actually_start()

    @pytest.mark.asyncio
    async def test__actually_start__child_is_None(self, *, service):
        s1 = Mock(maybe_start=AsyncMock())
        self._mock_for_start(
            service,
        )
        service._children = [None, s1]
        s1.maybe_start.side_effect = service._stopped.set
        service.restart_count = 1
        await service._actually_start()

    def _mock_for_start(
        self, service, init_deps=None, tasks=None, children=None, on_async_enter=None
    ):
        service.on_init_dependencies = Mock(return_value=init_deps or [])
        service.add_dependency = Mock()
        service.on_first_start = AsyncMock()
        service.exit_stack = MagicMock()
        service.async_exit_stack = AsyncMock(
            side_effect=on_async_enter,
        )
        service.on_start = AsyncMock()
        service._get_tasks = Mock(return_value=tasks or [])
        service._children = children or []

    @pytest.mark.asyncio
    async def test_join_services(self, *, service):
        s1 = Mock(maybe_start=AsyncMock(), stop=AsyncMock())
        s2 = Mock(maybe_start=AsyncMock(), stop=AsyncMock())
        await service.join_services([s1, s2])
        s1.maybe_start.assert_awaited_once_with()
        s2.maybe_start.assert_awaited_once_with()
        s1.stop.assert_awaited_once_with()
        s2.stop.assert_awaited_once_with()

    @pytest.mark.asyncio
    async def test_join_services_raises(self, *, service):
        s1 = Mock(maybe_start=AsyncMock(), stop=AsyncMock())
        s1.maybe_start.side_effect = KeyError()
        service.crash = AsyncMock()
        s2 = Mock(maybe_start=AsyncMock(), stop=AsyncMock())
        await service.join_services([s1, s2])
        s1.maybe_start.assert_awaited_once_with()
        s2.maybe_start.assert_awaited_once_with()
        s1.stop.assert_awaited_once_with()
        s2.stop.assert_awaited_once_with()

    def test_init_subclass_logger(self, *, service):
        class X(Service):
            logger = None

        class Y(X):
            logger = get_logger(__name__)
            logger.__modex__ = False

        assert Y.logger
        Y._init_subclass_logger()
        type(service).logger = None
        service._init_subclass_logger()
        assert type(service).logger.__modex__
        service._init_subclass_logger()

    def test_get_set_loop(self, *, service):
        m = Mock()
        service.loop = m
        assert service.loop is m

    def test__get_tasks__no_tasks(self, *, service):
        class X(type(service)):
            ...

        X._tasks = []
        assert list(X()._get_tasks()) == []

    @pytest.mark.asyncio
    async def test__execute_task__loop_is_closed(self, *, service):
        async def raises():
            raise RuntimeError("Event loop is closed because blah")

        await service._execute_task(raises())

    @pytest.mark.asyncio
    async def test__execute_task__exception(self, *, service):
        service.crash = AsyncMock()
        exc = KeyError("foo bah bar")

        async def raises():
            raise exc

        await service._execute_task(raises())
        service.crash.assert_awaited_once_with(exc)

    @pytest.mark.asyncio
    async def test__execute_task__RuntimeError(self, *, service):
        service.crash = AsyncMock()
        exc = RuntimeError("foo bah bar")

        async def raises():
            raise exc

        await service._execute_task(raises())
        service.crash.assert_awaited_once_with(exc)

    @pytest.mark.asyncio
    async def test__execute_task__CancelledError(self, *, service):
        async def raises():
            raise asyncio.CancelledError()

        await service._execute_task(raises())

    @pytest.mark.asyncio
    async def test__execute_task__CancelledError_stopped(self, *, service):
        service._stopped.set()

        async def raises():
            raise asyncio.CancelledError()

        await service._execute_task(raises())

    @pytest.mark.asyncio
    async def test_wait__no_args(self, *, service):
        service._wait_stopped = AsyncMock()
        assert await service.wait(timeout=1.13) == WaitResult(None, True)
        service._wait_stopped.assert_awaited_once_with(timeout=1.13)

    @pytest.mark.asyncio
    async def test_wait__one(self, *, service):
        service._wait_one = AsyncMock()
        coro = Mock()
        ret = await service.wait(coro, timeout=1.14)
        assert ret is service._wait_one.return_value
        service._wait_one.assert_awaited_once_with(coro, timeout=1.14)

    @pytest.mark.asyncio
    async def test_wait_many(self, *, service):
        with patch("asyncio.wait", AsyncMock()) as wait, patch(
            "asyncio.ensure_future", Mock()
        ) as ensure_future:
            service._wait_one = AsyncMock()
            m1 = AsyncMock()
            m2 = AsyncMock()
            res = await service.wait_many([m1, m2], timeout=3.34)
            assert res is service._wait_one.return_value

            ensure_future.assert_has_calls(
                [call(m1, loop=service.loop), call(m2, loop=service.loop)]
            )
            wait.assert_called_once_with(
                [ensure_future.return_value, ensure_future.return_value],
                return_when=asyncio.ALL_COMPLETED,
                timeout=3.34,
            )

            service._wait_one.assert_awaited_once_with(ANY, timeout=3.34)

    @pytest.mark.asyncio
    async def test_wait_first__propagates_exceptions(self, *, service):
        exc = KeyError("foo")
        m1 = Mock()
        m1.done.return_value = True
        m1.exception.return_value = exc
        m1.result.side_effect = exc
        with patch("asyncio.wait", AsyncMock()) as wait:
            wait.return_value = ((m1,), ())
            with pytest.raises(KeyError):
                await service.wait_first(asyncio.sleep(5), timeout=5)

    @pytest.mark.asyncio
    async def test_wait_first__propagates_CancelledError(self, *, service):
        m1 = Mock()
        m1.done.return_value = False
        m1.cancelled.return_value = False
        sleep = asyncio.sleep(5)
        to_cancel = [sleep]
        try:
            with patch("asyncio.ensure_future") as ensure_future:
                fut = ensure_future.return_value
                fut.done.return_value = False
                fut.cancelled.return_value = True
                with patch("asyncio.wait", AsyncMock()) as wait:
                    wait.return_value = ((m1,), ())
                    with pytest.raises(asyncio.CancelledError):
                        await service.wait_first(sleep, timeout=5)

                for call_ in ensure_future.call_args_list:
                    # Service.wait()
                    # calls ensure_future(self._stopped.wait())
                    # and since we have monkeypatched ensure_future
                    # to return a mock, it will not properly clean up.
                    # we need to clean up the coroutine we created
                    awaitable_arg = call_[0][0]
                    to_cancel.append(awaitable_arg)
        finally:
            # due to the way we mock this up, we need to
            # ``await`` any dangling ``async def`` calls
            # to avoid the "coroutine x was never awaited" warnings.
            for fut in to_cancel:
                handle = asyncio.ensure_future(fut)
                handle.cancel()
                try:
                    await handle
                except (asyncio.CancelledError, RuntimeError):
                    pass

    @pytest.mark.asyncio
    async def test_wait_until_stopped(self, *, service):
        service.wait = AsyncMock()
        await service.wait_until_stopped()
        service.wait.assert_called_once_with()

    def test_service_reset__None_in_children(self, *, service):
        service._children = [None]
        service.service_reset()

    @pytest.mark.asyncio
    async def test__default_stop_children__None(self, *, service):
        service._children = [None]
        await service._default_stop_children()

    @pytest.mark.asyncio
    async def test__default_stop__raises(self, *, service):
        service.log.exception = Mock()
        service._children = [Mock(stop=AsyncMock(side_effect=KeyError()))]
        await service._default_stop_children()
        service.log.exception.assert_called_once()

    @pytest.mark.asyncio
    async def test_crash__already_crashed(self, *, service):
        service._crashed.set()
        await service.crash(KeyError())

    @pytest.mark.asyncio
    async def test_crash__recursive_loop(self, *, service):
        service._crashed.clear()
        service.log.warning = Mock()
        service.supervisor = None
        obj = Mock(data="foo", children=[Mock(), Mock(), Mock()])
        service.beacon = Mock(
            depth=3,
            walk=Mock(return_value=[obj, obj]),
        )
        await service.crash(KeyError())
        service.log.warning.assert_called_once()

    @pytest.mark.asyncio
    async def test_crash__recursive_loop__no_root(self, *, service):
        service._crashed.clear()
        service.log.warning = Mock()
        service.supervisor = None
        obj = Mock(data="foo", children=[Mock(), Mock(), Mock()])
        service.beacon = Mock(
            depth=3,
            walk=Mock(return_value=[obj, obj]),
        )
        service.beacon.root = None
        await service.crash(KeyError())
        service.log.warning.assert_called_once()

    @pytest.mark.asyncio
    async def test__gather_futures__raises_cancel(self, *, service):
        service._futures = [Mock()]
        service._maybe_wait_for_futures = AsyncMock()

        def on_wait_for_futures(**kwargs):
            if service._maybe_wait_for_futures.call_count >= 3:
                service._futures.clear()
            raise asyncio.CancelledError()

        service._maybe_wait_for_futures.side_effect = on_wait_for_futures

        await service._gather_futures()

        assert service._maybe_wait_for_futures.await_count == 3

    @pytest.mark.asyncio
    async def test__maybe_wait_for_futures__ValueError_left(self, *, service):
        service._futures = [Mock()]
        with patch("asyncio.shield", AsyncMock()) as shield:
            with patch("asyncio.wait", AsyncMock()):

                async def on_shield(fut, *args, **kwargs):
                    # if we don't wait for coroutine passed to shield
                    # we get 'was never awaited' warning.
                    await fut
                    raise ValueError()

                shield.side_effect = on_shield
                with pytest.raises(ValueError):
                    await service._maybe_wait_for_futures()

    @pytest.mark.asyncio
    async def test__maybe_wait_for_futures__ValueError_empty(self, *, service):
        service._futures = [Mock()]
        with patch("asyncio.shield", AsyncMock()) as shield:
            with patch("asyncio.wait", AsyncMock()):

                async def on_shield(fut, *args, **kwargs):
                    # if we don't wait for coroutine passed to shield
                    # we get 'was never awaited' warning.
                    await fut
                    service._futures.clear()
                    raise ValueError()

                shield.side_effect = on_shield
                await service._maybe_wait_for_futures()

    @pytest.mark.asyncio
    async def test__maybe_wait_for_futures__CancelledError(self, *, service):
        service._futures = [Mock()]
        with patch("asyncio.shield", AsyncMock()) as shield:
            with patch("asyncio.wait", AsyncMock()):

                async def on_shield(fut, *args, **kwargs):
                    # if we don't wait for coroutine passed to shield
                    # we get 'was never awaited' warning.
                    await fut
                    raise asyncio.CancelledError()

                shield.side_effect = on_shield
                await service._maybe_wait_for_futures()

    @pytest.mark.asyncio
    async def test_itertimer(self, *, service):
        with patch("mode.services.Timer") as itertimer:

            async def on_itertimer(*args, **kwargs):
                yield 1.0
                yield 1.003
                yield 0.995

            itertimer.side_effect = on_itertimer

            service.sleep = AsyncMock()
            values = [value async for value in service.itertimer(1.0)]
            assert values == [1.0, 1.003, 0.995]

    @pytest.mark.asyncio
    async def test_itertimer__first_stop(self, *, service):
        with patch("mode.services.Timer") as itertimer:

            async def on_itertimer(*args, **kwargs):
                service._stopped.set()
                yield 1.0

            itertimer.side_effect = on_itertimer
            values = [value async for value in service.itertimer(1.0)]
            assert values == []

    @pytest.mark.asyncio
    async def test_itertimer__second_stop(self, *, service):
        with patch("mode.services.Timer") as itertimer:

            async def on_itertimer(*args, **kwargs):
                for val in [0.784512, 0.2, 0.3]:
                    await service.sleep(val)
                    yield val

            itertimer.side_effect = on_itertimer

            service.sleep = AsyncMock(name="sleep")

            async def on_sleep(*args, **kwargs):
                service._stopped.set()
                return None

            service.sleep.side_effect = on_sleep
            values = [value async for value in service.itertimer(1.0)]

            assert values == []
            service.sleep.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_itertimer__third_stop(self, *, service):
        with patch("mode.services.Timer") as itertimer:

            async def on_itertimer(*args, **kwargs):
                yield 0.1341
                yield 0.2
                yield 0.3
                yield 0.4

            itertimer.side_effect = on_itertimer

            sleep = AsyncMock(name="sleep")

            values = []
            async for value in service.itertimer(1.0, sleep=sleep):
                values.append(value)
                service._stopped.set()
            assert values == [0.1341]
