"""Template filters for showing Canvas scores."""
from django import template

register = template.Library()


@register.filter
def score(value):
    """Show a score the way Canvas does: up to two decimals, no trailing zeros."""
    if value is None or value == "":
        return value
    try:
        text = f"{float(value):.2f}"
    except (TypeError, ValueError):
        return value
    return text.rstrip("0").rstrip(".")
