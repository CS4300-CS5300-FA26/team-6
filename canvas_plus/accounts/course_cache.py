"""Shared Canvas course caching for pages using a saved connection."""
from django.core.cache import cache
from django.views.decorators.debug import sensitive_variables

# Enrollments rarely change mid-term; reconnecting Canvas starts a fresh cache key.
COURSE_CACHE_SECONDS = 60 * 60


@sensitive_variables("token")
def cached_courses(connection, token, session, load_courses):
    """Reuse the saved connection's course list for one hour."""
    key = f"canvas-courses:{connection.pk}:{connection.updated_at.timestamp()}"
    courses = cache.get(key)
    if courses is None:
        courses = load_courses(token, session=session)
        cache.set(key, courses, COURSE_CACHE_SECONDS)
    return courses
