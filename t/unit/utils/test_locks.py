from mode.utils.locks import Event


def test_repr():
    ev = Event()
    assert repr(ev)
    ev._waiters = [1, 2, 3]
    assert repr(ev)
