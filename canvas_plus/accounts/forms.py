"""Forms for account creation."""
from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import UserCreationForm


class RegistrationForm(UserCreationForm):  # pylint: disable=too-many-ancestors
    """Validate a new username and password, hashing the password on save."""

    class Meta:  # pylint: disable=too-few-public-methods
        """Use Django's built-in user model with only a username field."""
        model = get_user_model()
        fields = ("username",)

class CanvasConnectionForm(forms.Form):
    """Collect the canvas API token without displaying it"""

    token = forms.CharField(
        widget=forms.PasswordInput(
            render_value=False,
            attrs={"placeholder": "Paste your Canvas API Token"}
        ),
        max_length=64,  # Canvas max token size is 64 characters (https://raw.githubusercontent.com/instructure/canvas-lms/master/app/models/access_token.rb#:~:text=TOKEN_SIZE%20%3D%2064,%3Agenerate_token%20before_create%20%3Agenerate_refresh_token)
        strip=True,
        required=True,
        label="Canvas personal access token")






