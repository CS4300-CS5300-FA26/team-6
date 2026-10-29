"""Run structured inference through OpenAI with the application's configured token."""

from openai import OpenAI  # pylint: disable=unused-import


def infer(prompt, content, response_model):
    """Return a validated response_model instance for the prompt and content."""
    raise NotImplementedError
