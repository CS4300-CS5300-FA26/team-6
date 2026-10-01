# Test to validate task1. Import in the test since task1 has no methods
from src.main import greet

def test_say_hello(capsys):
    greet("World!")
    captured = capsys.readouterr()
    assert captured.out == "Hello, World!\n"