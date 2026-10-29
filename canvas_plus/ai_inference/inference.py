"""Run structured inference through OpenAI with the application's configured token."""

from openai import OpenAI  # pylint: disable=unused-import
from pydantic import BaseModel


def infer(prompt, content, response_model):
    """Return a validated response_model instance for the prompt and content."""
    if not isinstance(response_model, type) or not issubclass(response_model, BaseModel):
        raise TypeError("response_model must be a Pydantic BaseModel subclass")
    if not prompt.strip():
        raise ValueError("prompt must not be blank")

    raise NotImplementedError
