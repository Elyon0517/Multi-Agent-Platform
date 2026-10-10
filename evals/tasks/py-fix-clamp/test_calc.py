from calc import clamp


def test_clamp() -> None:
    assert clamp(9, 0, 5) == 5
    assert clamp(-1, 0, 5) == 0
