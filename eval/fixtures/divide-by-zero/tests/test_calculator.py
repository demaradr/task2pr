import pytest

from calculator import divide


def test_divide():
    assert divide(10, 2) == 5


def test_divide_by_zero_raises_value_error():
    with pytest.raises(ValueError, match="Cannot divide by zero"):
        divide(1, 0)
