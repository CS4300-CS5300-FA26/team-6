from django.db import models

# Create your models here.

class Assignment(models.Model):
    title = models.CharField(max_length=200)
    course = models.CharField(max_length=100)
    due_date = models.DateTimeField()

    def __str__(self):
        return self.title