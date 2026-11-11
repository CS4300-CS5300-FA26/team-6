"""Fake Canvas HTTP responses shared by Course Hub pytest and Behave tests.

Response bodies mirror what canvas-lms serializes for a student with the query
parameters our client sends; see lib/api/v1/course.rb, course_json.rb,
enrollment_term.rb, assignment.rb, submission.rb and lib/sorts_assignments.rb.
"""

from copy import deepcopy
from datetime import datetime, timedelta, timezone as dt_timezone
from unittest.mock import Mock, patch
from urllib.parse import urlparse

from bs4 import BeautifulSoup
from django.urls import reverse
from django.utils import timezone

CANVAS_HOST = "https://canvas.example.edu"
CANVAS_USER_ID = 7001
# Built-in role IDs on a stock Canvas install; Enrollment::SIS_TYPES gives the short types.
ROLES = {"student": ("StudentEnrollment", 3), "teacher": ("TeacherEnrollment", 4)}


def canvas_time(moment):
    """Canvas renders every timestamp as UTC ISO 8601 with a Z suffix."""
    return moment.astimezone(dt_timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse(value):
    return None if value is None else datetime.fromisoformat(value.replace("Z", "+00:00"))


# Each keyword represents a separate Canvas enrollment/term fixture condition.
# pylint: disable-next=too-many-arguments
def hub_course(course_id, code, name, *, ended=False, role="student", state="active"):
    """One element of GET /api/v1/courses?include[]=term, as a student sees it."""
    now = timezone.now()
    term_start = now - timedelta(days=60)
    term_end = now + timedelta(days=-30 if ended else 90)
    role_name, role_id = ROLES[role]
    return {
        "id": course_id,
        "name": name,
        "account_id": 1,
        "uuid": f"hub{course_id:037d}",
        "start_at": None,
        "grading_standard_id": None,
        "is_public": False,
        "created_at": canvas_time(term_start - timedelta(days=30)),
        "course_code": code,
        "default_view": "modules",
        "root_account_id": 1,
        "enrollment_term_id": 101 if ended else 102,
        "license": "private",
        "grade_passback_setting": None,
        "end_at": None,
        "public_syllabus": False,
        "public_syllabus_to_auth": False,
        "storage_quota_mb": 500,
        "is_public_to_auth_users": False,
        "homeroom_course": False,
        "course_color": None,
        "friendly_name": None,
        "apply_assignment_group_weights": False,
        "calendar": {"ics": f"{CANVAS_HOST}/feeds/calendars/course_hub{course_id}.ics"},
        "time_zone": "America/Denver",
        "blueprint": False,
        "template": False,
        "enrollments": [{
            "type": role,
            "role": role_name,
            "role_id": role_id,
            "user_id": CANVAS_USER_ID,
            "enrollment_state": state,
            "limit_privileges_to_course_section": False,
        }],
        "hide_final_grades": False,
        "workflow_state": "available",
        "restrict_enrollments_to_course_dates": False,
        "term": {
            "id": 101 if ended else 102,
            "name": "Spring 2026" if ended else "Fall 2026",
            "start_at": canvas_time(term_start),
            "end_at": canvas_time(term_end),
            "created_at": canvas_time(term_start - timedelta(days=90)),
            "workflow_state": "active",
            "grading_period_group_id": None,
        },
    }


def hub_assignment(course, due_at):
    """One element of GET /courses/:id/assignments?include[]=submission for a student."""
    assignment_id = course["id"] * 10
    created = due_at - timedelta(days=14)
    return {
        "id": assignment_id,
        "description": f"<p>Instructions for {course['course_code']}.</p>",
        "due_at": canvas_time(due_at),
        "unlock_at": None,
        "lock_at": None,
        "points_possible": 10.0,
        "grading_type": "points",
        "assignment_group_id": course["id"] * 100,
        "grading_standard_id": None,
        "created_at": canvas_time(created),
        "updated_at": canvas_time(created),
        "peer_reviews": False,
        "automatic_peer_reviews": False,
        "position": 1,
        "grade_group_students_individually": False,
        "anonymous_peer_reviews": False,
        "group_category_id": None,
        "post_to_sis": False,
        "moderated_grading": False,
        "omit_from_final_grade": False,
        "intra_group_peer_reviews": False,
        "anonymous_instructor_annotations": False,
        "anonymous_grading": False,
        "graders_anonymous_to_graders": False,
        "grader_count": 0,
        "grader_comments_visible_to_graders": True,
        "final_grader_id": None,
        "grader_names_visible_to_final_grader": True,
        "allowed_attempts": -1,
        "annotatable_attachment_id": None,
        "hide_in_gradebook": False,
        "suppress_assignment": False,
        "secure_params": "fake.jwt.value",
        "lti_context_id": f"hub-lti-{assignment_id}",
        "course_id": course["id"],
        "name": f"Upcoming work for {course['course_code']}",
        "submission_types": ["online_upload"],
        "has_submitted_submissions": False,
        "due_date_required": False,
        "max_name_length": 255,
        "in_closed_grading_period": False,
        "graded_submissions_exist": False,
        "is_quiz_assignment": False,
        "can_duplicate": False,
        "original_course_id": None,
        "original_assignment_id": None,
        "original_lti_resource_link_id": None,
        "original_assignment_name": None,
        "original_quiz_id": None,
        "workflow_state": "published",
        "important_dates": False,
        "muted": False,
        "html_url": f"{CANVAS_HOST}/courses/{course['id']}/assignments/{assignment_id}",
        "published": True,
        "only_visible_to_overrides": False,
        "visible_to_everyone": True,
        "locked_for_user": False,
        "submissions_download_url": (
            f"{CANVAS_HOST}/courses/{course['id']}/assignments/{assignment_id}"
            "/submissions?zip=1"
        ),
        "post_manually": False,
        "anonymize_students": False,
        "new_quizzes_anonymous_participants": False,
        "require_lockdown_browser": False,
        "restrict_quantitative_data": False,
        "submission": {
            "id": assignment_id * 10,
            "user_id": CANVAS_USER_ID,
            "url": None,
            "score": None,
            "grade": None,
            "excused": None,
            "attempt": None,
            "submission_type": None,
            "submitted_at": None,
            "body": None,
            "assignment_id": assignment_id,
            "graded_at": None,
            "grade_matches_current_submission": True,
            "grader_id": None,
            "workflow_state": "unsubmitted",
            "late_policy_status": None,
            "points_deducted": None,
            "grading_period_id": None,
            "cached_due_date": canvas_time(due_at),
            "extra_attempts": None,
            "posted_at": None,
            "redo_request": False,
            "sticker": None,
            "custom_grade_status_id": None,
            "late": False,
            "missing": False,
            "seconds_late": 0,
            "entered_grade": None,
            "entered_score": None,
            "preview_url": (
                f"{CANVAS_HOST}/courses/{course['id']}/assignments/{assignment_id}"
                f"/submissions/{CANVAS_USER_ID}?preview=1&version=0"
            ),
        },
    }


def active_hub_courses():
    """Use nonsequential API IDs so positional links cannot accidentally pass."""
    return [
        hub_course(43009, "CS 4300", "Software Engineering"),
        hub_course(21507, "MATH 2150", "Discrete Mathematics"),
        hub_course(13103, "ENGL 1310", "Rhetoric and Writing"),
        hub_course(10105, "HIST 1010", "World History"),
    ]


def excluded_hub_courses():
    """Cover ended terms, inactive students, and active nonstudent enrollments."""
    return [
        hub_course(99001, "OLD 1000", "Ended Term", ended=True),
        hub_course(99002, "OLD 2000", "Concluded Enrollment", state="completed"),
        hub_course(99003, "OLD 3000", "Invited Enrollment", state="invited"),
        hub_course(99004, "OLD 4000", "Teacher Enrollment", role="teacher"),
    ]


def course_links(response, courses):
    """Find course navigation by destination without prescribing CSS or ARIA markup."""
    destinations = {reverse("course_detail", args=[course["id"]]) for course in courses}
    return [
        link for link in BeautifulSoup(response.content, "html.parser").select("main a[href]")
        if link["href"] in destinations
    ]


def _matches_enrollment(course, params, now):
    """Mirror CoursesController#courses_for_user for enrollment_type/enrollment_state."""
    for enrollment in course["enrollments"]:
        if params.get("enrollment_type") and enrollment["type"] != params["enrollment_type"]:
            continue
        if params.get("enrollment_state") == "active":
            # Canvas returns participating enrollments: active and not concluded by date.
            # ponytail: models term end only; add course-date overrides if a fixture needs them.
            term_end = _parse(course["term"]["end_at"])
            if enrollment["enrollment_state"] != "active" or (term_end and term_end <= now):
                continue
        return True
    return False


def _in_bucket(assignment, bucket, now):
    """Mirror SortsAssignments: upcoming is due within a week; overdue is past due, unsubmitted."""
    due = _parse(assignment["due_at"])
    if bucket == "upcoming":
        return due is not None and now <= due <= now + timedelta(weeks=1)
    if bucket == "overdue":
        return (due is not None and due < now
                and assignment["submission"]["workflow_state"] == "unsubmitted")
    raise AssertionError(f"Bucket not modeled: {bucket}")


def _response(data, status_code=200):
    response = Mock(status_code=status_code, links={})
    response.json.return_value = deepcopy(data)
    return response


# A fake HTTP service needs only the requests-compatible get entry point.
# pylint: disable-next=too-few-public-methods
class HubCanvas:
    """Serve deterministic Canvas data, honoring the query filters our client sends."""

    def __init__(self, courses):
        self.courses = courses
        self.course_calls = 0
        due = timezone.now().replace(microsecond=0) + timedelta(days=2)
        self.assignments = {course["id"]: [hub_assignment(course, due)] for course in courses}

    def get(self, url, **kwargs):
        """Implement the HTTP boundary for direct and session-backed Canvas requests."""
        parsed = urlparse(url)
        assert parsed.netloc == "canvas.example.edu", f"Unexpected Canvas host: {url}"
        params = kwargs.get("params") or {}
        parts = parsed.path.strip("/").split("/")
        now = timezone.now()
        if parts == ["api", "v1", "courses"]:
            self.course_calls += 1
            return _response([c for c in self.courses if _matches_enrollment(c, params, now)])
        if parts[:3] != ["api", "v1", "courses"] or len(parts) < 4:
            raise AssertionError(f"Unexpected Canvas URL: {url}")
        course = next((c for c in self.courses if c["id"] == int(parts[3])), None)
        if course is None:
            return _response({"errors": [{"message": "The specified resource does not exist."}]},
                             status_code=404)
        if len(parts) == 4:
            data = {k: v for k, v in course.items() if k != "term"}
            data["syllabus_body"] = "<p>Course policies</p>"
            return _response(data)
        if parts[4:] == ["assignments"]:
            return _response([a for a in self.assignments.get(course["id"], [])
                              if _in_bucket(a, params.get("bucket"), now)])
        if parts[4:] == ["students", "submissions"]:
            return _response([])
        raise AssertionError(f"Unexpected Canvas URL: {url}")


def install_hub_canvas(add_cleanup, courses):
    """Replace both HTTP entry points; no test contacts a live Canvas server."""
    canvas = HubCanvas(courses)
    targets = (
        "accounts.canvas_client.requests.get",
        "accounts.canvas_client.requests.Session.get",
    )
    for target in targets:
        patcher = patch(target, side_effect=canvas.get)
        patcher.start()
        add_cleanup(patcher.stop)
    return canvas


def hub_cache_clock(add_cleanup):
    """Advance only Django's cache clock, leaving test-runner timing unaffected."""
    clock = Mock(return_value=2000000000)
    targets = ("django.core.cache.backends.base.time", "django.core.cache.backends.locmem.time")
    for target in targets:
        patcher = patch(target, Mock(time=clock))
        patcher.start()
        add_cleanup(patcher.stop)
    return clock
