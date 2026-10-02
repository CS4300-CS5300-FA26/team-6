"""DB models for assignment app"""

from django.db import models

# Create your models here.

class Assignment(models.Model):
    """Course assignment with title, course, and due date."""

    title = models.CharField(max_length=200)
    course = models.CharField(max_length=100)
    due_date = models.DateTimeField()

    def __str__(self):
        """returns title as string"""
        return str(self.title)
