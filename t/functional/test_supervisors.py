import asyncio

import pytest

from mode import Service
from mode.supervisors import (
    ForfeitOneForAllSupervisor,
    ForfeitOneForOneSupervisor,
    OneForAllSupervisor,
    OneForOneSupervisor,
)


class StatService(Service):
    started_count: int = 0
    stopped_count: int = 0
    restart_count: int = 0

    async def start(self) -> None:
        self.started_count += 1
        await super().start()

    async def stop(self) -> None:
        if not self._stopped.is_set():
            self.stopped_count += 1
            await super().stop()

    async def restart(self) -> None:
        self.restart_count += 1
        await super().restart()


class X(StatService):
    ...


class Y(StatService):
    x: X

    def __post_init__(self) -> None:
        self.x = X(loop=self.loop, beacon=self.beacon)
        self.add_dependency(self.x)


class Z(StatService):
    ...


class SupervisorTest:
    Supervisor = OneForOneSupervisor

    def __init__(self, Supervisor) -> None:
        self.Supervisor = Supervisor

    def setup_supervisor(self):
        supervisor = self.Supervisor()
        service = Y()
        service2 = Z()
        supervisor.add(service)
        supervisor.add(service2)
        return supervisor, service, service2

    async def start(self):
        supervisor, y, z = self.setup_supervisor()
        await supervisor.start()
        self.assert_started(y, supervisor)
        self.assert_started(z, supervisor)
        assert y.x.started_count
        return supervisor, y, z

    def assert_started(self, service, supervisor) -> None:
        self.assert_attached_to_supervisor(service, supervisor)
        assert service.started_count

    def assert_attached_to_supervisor(self, service, supervisor) -> None:
        assert service.supervisor is supervisor


@pytest.mark.asyncio
async def test_OneForOneSupervisor():
    t = SupervisorTest(OneForOneSupervisor)
    supervisor, y, z = await t.start()
    await asyncio.sleep(0.1)
    await z.crash(KeyError())
    await asyncio.sleep(1)
    assert y.stopped_count == 0
    assert z.stopped_count == 1
    assert z.started_count == 2
    assert y.started_count == 1
    assert y.x.started_count == 1
    await supervisor.stop()
    assert z.stopped_count == 2
    assert y.stopped_count == 1


@pytest.mark.asyncio
async def test_ForfeitOneForOneSupervisor():
    t = SupervisorTest(ForfeitOneForOneSupervisor)
    supervisor, y, z = await t.start()
    await asyncio.sleep(0.1)
    await z.crash(KeyError())
    await asyncio.sleep(1)

    assert y.stopped_count == 0
    assert z.stopped_count == 1
    assert y.started_count == 1
    assert z.started_count == 1

    await supervisor.stop()

    assert y.stopped_count == 1
    assert z.stopped_count == 1


@pytest.mark.asyncio
async def test_ForfeitOneForAllSupervisor():
    t = SupervisorTest(ForfeitOneForAllSupervisor)
    supervisor, y, z = await t.start()
    await asyncio.sleep(0.1)
    await z.crash(KeyError())
    await asyncio.sleep(1)

    assert y.stopped_count == 1
    assert y.x.stopped_count == 1
    assert z.stopped_count == 1
    assert y.started_count == 1
    assert z.started_count == 1

    await supervisor.stop()

    assert y.stopped_count == 1
    assert z.stopped_count == 1


@pytest.mark.asyncio
async def test_OneForAllSupervisor():
    t = SupervisorTest(OneForAllSupervisor)
    supervisor, y, z = await t.start()
    await asyncio.sleep(0.1)
    await z.crash(KeyError())
    await asyncio.sleep(1)
    assert y.stopped_count == 1
    assert y.x.stopped_count == 1
    assert z.stopped_count == 1

    assert not y._stopped.is_set()
    assert not y.x._stopped.is_set()
    assert y.started_count == 2
    assert y.x.started_count == 2
    assert z.started_count == 2
    await supervisor.stop()
    assert y.stopped_count == 2
    assert y.x.stopped_count == 2
    assert z.stopped_count == 2
