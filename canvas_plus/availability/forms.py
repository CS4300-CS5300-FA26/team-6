"""Form to create and update availability"""

#import forms and model
from django import forms
from .models import Availability

class AvailabilityForm(forms.ModelForm):
    """form for students to enter or update availability"""
    class Meta:
        """Configure which fields appear in the form."""
        #creates and updates database records.
        model = Availability
        #user selects date, start time, and end time
        #logged-in user will be assigned in view rather than allowing
        #someone to select another's account.
        fields = [
            "date",
            "start_time",
            "end_time",
        ]
        #HTML date/time input controls in browser
        widgets = {
            "date": forms.DateInput(attrs={"type": "date"}),
            "start_time": forms.TimeInput(attrs={"type": "time"}),
            "end_time": forms.TimeInput(attrs={"type": "time"}),
        }
    def clean(self):
        #validate time range is logical
        #run Django's built-in validation
        cleaned_data = super().clean()
        #get start and end time after django converted into python objects.
        start_time = cleaned_data.get("start_time")
        end_time = cleaned_data.get("end_time")
        #compare only if both times were entered correctly
        if start_time and end_time and end_time <= start_time:
            #validation error so form gets rejected and Django displays message to correct.
            raise forms.ValidationError(
                "End time must be later than start time."
            )
        #returns validated data back to django.
        return cleaned_data
