"""Documented failures raised by the AI inference interface."""


class AIInferenceError(Exception):
    """Base class for inference failures; messages never contain the token."""


class AIConfigurationError(AIInferenceError):
    """AI_API_KEY is not configured."""
