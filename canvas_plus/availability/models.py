"""Database models for the availability application."""
#imports for models.py
from django.db import models

from django.conf import settings

# Availability class
class Availability(models.Model):
    """Represent one period when a student is available to study."""
    #connect availability period to student who created it,
    #if user deleted records are also deleted.

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
	    on_delete=models.CASCADE,
	)

	#store calendar date of period.
    date = models.DateField()

	#store start time
    start_time = models.TimeField()

	#store end time
    end_time = models.TimeField()

    def __str__(self):
        """Return a readable description of the availability period."""
		#makes object easier to recognize in Django
        return (
		    f"{self.user} - {self.date}: "
		    f"{self.start_time} to {self.end_time}"
		)
