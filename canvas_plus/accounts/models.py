"""Per-user Canvas credentials, encrypted separately from Django session data."""

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.db import models
from django.views.decorators.debug import sensitive_variables


def token_cipher():
    """Fail closed when the dedicated encryption key is missing or malformed."""
    try:
        return Fernet(settings.CANVAS_TOKEN_ENCRYPTION_KEY.encode())
    except (ValueError, TypeError):
        raise ImproperlyConfigured("Configure a valid CANVAS_TOKEN_ENCRYPTION_KEY.") from None


class SavedTokenError(Exception):
    """The saved credential can no longer be decrypted."""


class CanvasConnection(models.Model):
    """One encrypted credential per student, bound to its original Canvas host."""

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    encrypted_token = models.TextField(editable=False)
    token_last_four = models.CharField(max_length=4, editable=False)
    canvas_url = models.URLField(max_length=500, editable=False)
    is_valid = models.BooleanField(default=True)
    updated_at = models.DateTimeField(auto_now=True)
    objects = models.Manager()

    @sensitive_variables("token")
    def set_token(self, token):
        """Encrypt before assignment; plaintext never enters a database field."""
        self.encrypted_token = token_cipher().encrypt(token.encode()).decode()
        self.token_last_four = token[-4:]
        self.is_valid = True

    def get_token(self):
        """Decrypt only for a server-side Canvas request."""
        try:
            return token_cipher().decrypt(self.encrypted_token.encode()).decode()
        except (InvalidToken, UnicodeError):
            raise SavedTokenError("Your saved Canvas connection could not be read.") from None
