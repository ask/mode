import asyncio
import sys
from unittest.mock import Mock, patch

if sys.version_info < (3, 8):
    from mock.mock import AsyncMock
else:
    from unittest.mock import AsyncMock

import pytest

from mode.exceptions import MaxRestartsExceeded
from mode.supervisors import (
    CrashingSupervisor,
    ForfeitOneForAllSupervisor,
    ForfeitOneForOneSupervisor,
    OneForAllSupervisor,
    SupervisorStrategy,
)


class test_SupervisorStrategy:
    @pytest.fixture()
    def service(self):
        return Mock(stop=AsyncMock())

    @pytest.fixture()
    def sup(self, *, service):
        return SupervisorStrategy(service)

    def test_discard(self, *, sup, service):
        s1 = Mock()
        sup.discard(service, s1)
        assert service not in sup._services

    def test_insert(self, *, sup, service):
        s1 = Mock(name="s1")
        s2 = Mock(name="s2")
        s3 = Mock(name="s3")
        s4 = Mock(name="s4")
        sup._services = [s1, s2, s3, s4]

        s5 = Mock(name="s5")
        sup.insert(2, s5)
        assert sup._services == [s1, s2, s5, s4]

    @pytest.mark.asyncio
    async def test_run_until_complete(self, *, sup):
        sup.start = AsyncMock()
        sup.stop = AsyncMock()
        await sup.run_until_complete()
        sup.start.assert_awaited_once_with()
        sup.stop.assert_awaited_once_with()

    @pytest.mark.asyncio
    async def test__supervisor__second_stop(self, *, sup, service):
        service.started = False
        with patch("asyncio.wait_for", AsyncMock()) as wait_for:

            async def on_wait_for(*args, **kwargs):
                if wait_for.call_count >= 2:
                    sup._stopped.set()
                raise asyncio.TimeoutError()

            wait_for.side_effect = on_wait_for

            sup.start_services = AsyncMock()
            sup.restart_services = AsyncMock()
            await sup._supervisor(sup)

            sup.start_services.assert_called_once_with([service])
            sup.restart_services.assert_called_once_with([])

    @pytest.mark.asyncio
    async def test_on_stop(self, *, sup):
        sup._services = [
            Mock(stop=AsyncMock()),
            Mock(stop=AsyncMock()),
            Mock(stop=AsyncMock()),
        ]
        sup._services[0].started = False
        await sup.on_stop()
        for s in sup._services[1:]:
            s.stop.assert_awaited_once_with()

    @pytest.mark.asyncio
    async def test_on_stop__raises_MemoryError(self, *, sup, service):
        service.stop.side_effect = MemoryError()
        with pytest.raises(MemoryError):
            await sup.on_stop()

    @pytest.mark.asyncio
    async def test_on_stop__raises_exc(self, *, sup, service):
        sup.log.exception = Mock()
        service.stop.side_effect = KeyError("foo")
        await sup.on_stop()
        sup.log.exception.assert_called_once()

    @pytest.mark.asyncio
    async def test_restart_service(self, *, sup, service):
        service.restart = AsyncMock()
        sup._bucket = AsyncMock()
        await sup.restart_service(service)
        service.restart.assert_awaited_once_with()

    @pytest.mark.asyncio
    async def test_restart_service__max_restarts(self, *, sup, service):
        sup.log.warning = Mock(0)
        sup._bucket = AsyncMock()
        service.restart = AsyncMock()
        service.restart.side_effect = MaxRestartsExceeded()
        with pytest.raises(SystemExit):
            await sup.restart_service(service)
        service.restart.assert_awaited_once_with()
        sup.log.warning.assert_called_once()

    @pytest.mark.asyncio
    async def test_restart_service__replacement(self, *, sup):
        sup._bucket = AsyncMock()
        s1 = Mock(name="s1")
        s2 = Mock(name="s2")
        s3 = Mock(name="s3")

        sup._services = [s1, s2, s3]
        sup._index = {s: i for i, s in enumerate(sup._services)}

        s4 = Mock(name="s4")
        s4.supervisor = None
        sup.replacement = AsyncMock()
        sup.replacement.return_value = s4

        await sup.restart_service(s2)

        assert sup._services == [s1, s4, s3]
        assert sup._index[s4] == 1
        assert s2 not in sup._index

        assert s4.supervisor is sup


class test_OneForAllSupervisor:
    @pytest.fixture()
    def sup(self):
        return OneForAllSupervisor(Mock())

    @pytest.mark.asyncio
    async def test_restart_services__empty(self, *, sup):
        await sup.restart_services([])


class test_ForfeitOneForOneSupervisor:
    @pytest.fixture()
    def sup(self):
        return ForfeitOneForOneSupervisor(Mock())

    @pytest.mark.asyncio
    async def test_restart_services__empty(self, *, sup):
        await sup.restart_services([])


class test_ForfeitOneForAllSupervisor:
    @pytest.fixture()
    def sup(self):
        return ForfeitOneForAllSupervisor(Mock())

    @pytest.mark.asyncio
    async def test_restart_services__empty(self, *, sup):
        await sup.restart_services([])


class test_CrashingSupervisor:
    @pytest.fixture()
    def sup(self):
        return CrashingSupervisor(Mock())

    def test__contribute_to_service(self, *, sup):
        s = Mock()
        s.supervisor = None
        sup._contribute_to_service(s)
        assert s.supervisor is None

    def test_wakeup(self, *, sup):
        assert not sup._stopped.is_set()
        wakeup = sup._please_wakeup = Mock()
        wakeup.done.return_value = False
        wakeup.cancelled.return_value = False
        sup.wakeup()
        assert sup._stopped.is_set()
        wakeup.set_result.assert_called_with(None)
