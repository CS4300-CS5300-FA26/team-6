"""Test that greet prints the expected greeting."""
from src.main import greet

def test_say_hello(capsys):
    """Verify that greet prints 'Hello, World!' followed by a newline.

    Args:
        capsys: Pytest fixture that captures stdout and stderr.
    """
    greet("World!")
    captured = capsys.readouterr()
    assert captured.out == "Hello, World!\n"
