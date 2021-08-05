import mode


def test_dir():
    assert dir(mode)
    assert "__version__" in dir(mode)
