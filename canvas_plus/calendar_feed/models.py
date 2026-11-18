"""Calendar subscription credentials."""

from django.conf import settings
from django.db import models


class CalendarSubscription(models.Model):
    """A user's subscription credential stored only as a digest."""

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    token_digest = models.CharField(max_length=64, unique=True, editable=False)