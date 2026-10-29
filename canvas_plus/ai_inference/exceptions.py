"""Documented failures raised by the AI inference interface."""


class AIInferenceError(Exception):
    """Base class for inference failures; messages never contain the token."""


class AIConfigurationError(AIInferenceError):
    """OPENAI_API_KEY is not configured."""


class AIAuthenticationError(AIInferenceError):
    """The provider rejected the configured credentials."""


class AIProviderError(AIInferenceError):
    """The provider request failed."""


class AIRefusalError(AIInferenceError):
    """The provider refused to generate the requested response."""


class AIIncompleteResponseError(AIInferenceError):
    """The provider did not complete the response."""


class AIInvalidOutputError(AIInferenceError):
    """The response could not be parsed or validated as requested."""
