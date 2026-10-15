"""Forms for account creation."""
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import UserCreationForm


class RegistrationForm(UserCreationForm):  # pylint: disable=too-many-ancestors
    """Validate a new username and password, hashing the password on save."""

    class Meta:  # pylint: disable=too-few-public-methods
        """Use Django's built-in user model with only a username field."""
        model = get_user_model()
        fields = ("username",)
