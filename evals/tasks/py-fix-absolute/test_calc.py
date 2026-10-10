from calc import absolute


def test_absolute() -> None:
    assert absolute(-4) == 4
    assert absolute(3) == 3
