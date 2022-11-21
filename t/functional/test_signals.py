from typing import Any
from unittest.mock import Mock
from weakref import ref

import pytest

from mode import label
from mode.signals import Signal, SignalT, SyncSignal, SyncSignalT


class X:
    on_started: SignalT = Signal()
    on_stopped: SignalT = Signal()

    def __init__(self):
        self.on_started = self.on_started.with_default_sender(self)
        self.on_stopped = self.on_stopped.with_default_sender(self)


class Y(X):
    ...


class SyncX:
    on_started: SyncSignalT = SyncSignal()
    on_stopped: SyncSignalT = SyncSignal()

    def __init__(self):
        self.on_started = self.on_started.with_default_sender(self)
        self.on_stopped = self.on_stopped.with_default_sender(self)


def test_clone():
    assert X.on_started.clone()


def test_with_default_sender():
    assert X.on_started.with_default_sender(42).default_sender == 42


def test_disconnect_value_error():
    X.on_started._create_id = Mock(side_effect=ValueError())
    X.default_sender = Mock()
    X.on_started.disconnect(Mock())


@pytest.mark.asyncio
async def test_signals():
    x, y = X(), Y()

    on_stopped_mock = Mock()
    on_started_mock = Mock()

    @y.on_stopped.connect
    async def my_on_stopped(self, value, **kwargs):
        on_stopped_mock(self, value)

    @y.on_started.connect
    async def my_on_started(self, value, **kwargs):
        on_started_mock(self, value)

    await y.on_started.send(value=1)
    on_started_mock.assert_called_once_with(y, 1)

    await y.on_stopped.send(value=2)
    on_stopped_mock.assert_called_once_with(y, 2)
    assert on_started_mock.call_count == 1
    await x.on_started.send(value=3)
    await x.on_stopped(value=4)

    assert x.on_started.ident
    assert label(x.on_started)
    assert repr(x.on_started)

    assert on_started_mock.call_count == 1
    assert on_stopped_mock.call_count == 1


def test_sync_signals():
    x = SyncX()
    x2 = SyncX()

    on_stopped_mock = Mock()
    on_started_mock = Mock()

    @x.on_stopped.connect
    def my_on_stopped(self, code: int, reason: str, **kwargs: Any) -> None:
        assert kwargs["signal"] == x.on_stopped
        on_stopped_mock(self, code, reason)

    @x.on_started.connect
    def my_on_started(self, **kwargs: Any) -> None:
        assert kwargs["signal"] == x.on_started
        on_started_mock(self)

    x.on_started.send()
    on_started_mock.assert_called_once_with(x)

    x.on_stopped.send(303, "sorry not sorry")
    on_stopped_mock.assert_called_once_with(x, 303, "sorry not sorry")
    assert on_started_mock.call_count == 1

    assert x.on_started.ident
    assert label(x.on_started)
    assert label(X.on_started)
    assert repr(x.on_started)
    assert repr(X.on_started)

    prev, x.on_started.owner = x.on_started.owner, None
    assert label(x.on_started)
    x.on_started.owner = prev

    x.on_started()
    assert on_started_mock.call_count == 2

    x2.on_started.send()
    x2.on_started.send()

    assert on_started_mock.call_count == 2

    new_sender = Mock()
    sig2 = x2.on_started.clone(default_sender=new_sender)
    assert sig2.default_sender == new_sender

    sig3 = sig2.with_default_sender(None)
    assert sig3.default_sender == sig2.default_sender

    new_sender2 = Mock()
    sig4 = sig3.with_default_sender(new_sender2)
    assert sig4.default_sender == new_sender2

    sig4.name = ""
    sig4.__set_name__(sig3, "foo")
    assert sig4.name == "foo"
    assert sig4.owner == sig3
    sig4.__set_name__(sig2, "bar")
    assert sig4.name == "foo"
    assert sig4.owner == sig2

    sig4.default_sender = None
    with pytest.raises(TypeError):
        sig4.unpack_sender_from_args()
    assert sig4.unpack_sender_from_args(1) == (1, ())
    assert sig4.unpack_sender_from_args(1, 2) == (1, [2])

    partial_yes = sig4.connect(None)
    mockfun = Mock()
    partial_yes(mockfun)
    sig4.disconnect(mockfun)

    sig2.connect(mockfun, weak=True)
    sig2.disconnect(mockfun, weak=True)


def test_signal_name():
    # Signal should have .name attribute set when created
    # as a field in a class:

    class X:
        sig = Signal()
        sig2 = SyncSignal()

    assert X.sig.name == "sig"
    assert X.sig.owner is X
    assert X.sig2.name == "sig2"
    assert X.sig2.owner is X


class test_BaseSignal:
    @pytest.fixture()
    def sig(self):
        return Signal()

    def test_with_default_sender(self, sig):
        sender = Mock()
        sig2 = super(type(sig), sig).with_default_sender(sender)
        assert sig2.default_sender is sender

        sig3 = super(type(sig2), sig2).clone()
        assert sig3.asdict() == sig2.asdict()

    def test_disconnect_lambda(self, sig):
        sig._receivers = Mock()
        r = Mock()
        sig.disconnect(r, sender=None)
        sig._receivers.discard.assert_called_once()
        lmbda = sig._receivers.discard.call_args[0][0]
        assert lmbda() == r

    def test_disconnect_raises(self, sig):
        sig._create_id = Mock(side_effect=ValueError())
        sig.disconnect(Mock(), sender=Mock())

    def test_iter_receivers(self, sig):
        receivers, alive_refs, dead_refs = self.create_refs(sig)
        sig._receivers = receivers
        sig._live_receivers = set()
        sig._update_receivers = Mock(return_value=alive_refs)
        assert list(sig.iter_receivers(None)) == alive_refs

    def test_iter_receivers_no_receivers(self, sig):
        sig._receivers = set()
        sig._filter_receivers = set()
        assert list(sig.iter_receivers(None)) == []

    def test__get_live_receivers(self, sig):
        receivers, alive_refs, dead_refs = self.create_refs(sig)
        alive, dead = sig._get_live_receivers(receivers)
        sig._update_receivers(receivers)
        assert receivers == set(alive_refs)

    def create_refs(self, sig):
        sig._is_alive = Mock()

        def is_alive(x):
            return x.alive, x

        sig._is_alive.side_effect = is_alive

        alive_refs = [Mock(alive=True), Mock(alive=True)]
        dead_refs = [Mock(alive=False)]

        receivers = set(alive_refs + dead_refs)

        return receivers, alive_refs, dead_refs

    def test__is_alive(self, sig):
        class Object:
            value = None

        x = Object()
        x.value = 10
        assert sig._is_alive(lambda: 42) == (True, 42)
        assert sig._is_alive(ref(x)) == (True, x)

    def test_create_ref_methods(self, sig):
        class X:
            def foo(self, **kwargs):
                return 42

        assert sig._create_ref(X.foo)
        assert sig._create_ref(X().foo)
