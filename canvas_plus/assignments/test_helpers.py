"""Shared setup helpers for assignments integration tests."""

from cryptography.fernet import Fernet
from django.contrib.auth import get_user_model
from django.test import override_settings

from accounts.models import CanvasConnection


def configure_canvas_user(test_case):
    """Set up a logged-in user with a test Canvas connection."""
    settings_override = override_settings(
        CANVAS_BASE_URL="https://canvas.example.edu",
        CANVAS_TOKEN_ENCRYPTION_KEY=Fernet.generate_key().decode(),
    )
    settings_override.enable()
    test_case.addCleanup(settings_override.disable)
    user = get_user_model().objects.create_user(
        username="canvas-student",
        password="test-password-123",
    )
    connection = CanvasConnection(
        user=user,
        canvas_url="https://canvas.example.edu",
    )
    connection.set_token("fake-canvas-token")
    connection.save()
    test_case.client.force_login(user)
    return user, connection
