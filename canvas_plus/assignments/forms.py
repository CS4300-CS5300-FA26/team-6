"""Forms for assignment-related student input."""

# Import Django's form framework.
from django import forms

# Import the Assignment model being updated.
from .models import Assignment


class EffortEstimateForm(forms.ModelForm):
    """Allow a student to manually update an assignment effort estimate."""

    class Meta:  # pylint: disable=too-few-public-methods
        """Configure the Assignment field exposed by this form."""

        # This form updates an existing Assignment record.
        model = Assignment

        # Only expose the effort estimate to the student.
        fields = [
            "estimated_effort_minutes",
        ]

        # Make the input clearer in the browser.
        widgets = {
            "estimated_effort_minutes": forms.NumberInput(
                attrs={
                    "min": 1,
                    "step": 1,
                }
            ),
        }

    def clean_estimated_effort_minutes(self):
        """Require the manual estimate to be a positive whole number."""

        # Get the validated field value.
        estimated_minutes = self.cleaned_data["estimated_effort_minutes"]

        # Reject missing or invalid values.
        if estimated_minutes is None or estimated_minutes <= 0:
            raise forms.ValidationError(
                "Estimated effort must be greater than zero minutes."
            )

        # Return the validated value to Django.
        return estimated_minutes
