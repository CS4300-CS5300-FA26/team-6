"""Provide a greeting function and print a greeting to the world."""

def greet(name):
    """Print a greeting for the given name followed by a newline.

    Args:
        name (str): The name to include in the greeting.
    """
    message = "Hello, " + name
    print(message)


greet("world")
