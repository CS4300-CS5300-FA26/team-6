# Dynamic Priority Indicators Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the hard-coded "Upcoming" badge on each dashboard assignment card with a label recomputed on every page load: Submitted, Past due, Due soon, or Upcoming (issue #41).

**Architecture:** `accounts/canvas_client.py` fetches Canvas's `upcoming` and `overdue` buckets with the student's submission and adds a `submitted` flag to each assignment. A pure function `assignments/priority.py::priority()` maps `(due_date, submitted, now)` to a label. The view stamps that label on each assignment using one `now`, and the template renders it with a modifier CSS class.

**Tech Stack:** Python 3.14, Django 6.1, requests, pytest + pytest-django, behave-django, pylint, uv.

**Spec:** `docs/superpowers/specs/2026-10-22-dynamic-priority-indicators-design.md`. Read it before starting any task.

## Global Constraints

- Strict TDD. Write the test, run it, **see it fail for the expected reason**, and commit `test: …`. Then implement, run it green, and commit `feat: …`. Include the red output in your report.
- Commit only your own files. Use `git commit -m "<msg>" -- <paths>`, because other agents may be working in the same tree. Never `git add -A`, never amend, never push.
- End every commit message with the trailer `Co-Authored-By: <your model name> <noreply@example.com>`.
- Labels are exactly `"Submitted"`, `"Past due"`, `"Due soon"`, `"Upcoming"`. The window is `timedelta(hours=48)`. Exactly 48 h left is `"Due soon"`. `due_date == now` is `"Due soon"`. `due_date < now` is `"Past due"`. Submitted wins over every other label.
- "Submitted" means `submission.get("submitted_at") is not None or submission.get("workflow_state") == "graded"`.
- First-page Canvas params are exactly `{"bucket": <bucket>, "include[]": "submission"}`. Later pages use `params=None`.
- Bucket order per course is `"upcoming"`, then `"overdue"`.
- No new dependencies. No changes to `accounts/models.py` or `assignments/models.py`. Don't modify PR #99's Recently graded code paths, except the fixture edits listed in Task 3.
- Run commands from the repo root `/Users/joshdouglas/dev/team-6`:
  - pytest: `uv run pytest`
  - behave: `cd canvas_plus && uv run python manage.py behave --settings=canvas_plus.settings_test`
  - lint: `uv run pylint --fail-under=8.0 .`
- Tests carry `@pytest.mark.unit` or `@pytest.mark.integration`, as in the existing files. Imports in tests follow `from assignments.grades import recent_grades  # pylint: disable=import-error`.

## Review Focus

1. **A Canvas submission object that exists but is unsubmitted** (`workflow_state: "unsubmitted"`, `submitted_at: null`) must count as **not** submitted. Pinned in Task 2.
2. **The second (overdue) request fails after the first succeeds.** A 500 must raise `CanvasAPIError` (the page shows "unavailable", not a partial list), and a 401 must raise `CanvasAuthenticationError`. Pinned in Task 2.
3. **A pagination `next` link on the overdue bucket that points at another origin** must be rejected before the token is sent. Pinned in Task 2.
4. **Work submitted late** (due in the past, submitted) must show **Submitted**, not Past due. Pinned in Task 1.
5. **The CSS class the template emits must match the CSS rules.** `slugify` must yield exactly `due-soon`, `past-due`, `submitted` and `upcoming`. Pinned in Task 3.

## Agent assignment and order

| Task | Agent | Starts after |
|---|---|---|
| 1 `priority()` | GLM 5.3 (opencode) | now |
| 2 Canvas client | GLM 5.3 (opencode) | now, in parallel with 1 |
| 3 View + template | GLM 5.3 (opencode) | Task 1 committed |
| 4 Behave acceptance scenarios | GPT 6.1 sol | Task 3 committed |
| 5 Full gates, README AI note, PR | orchestrator (Claude) | Tasks 2 and 4 |

---

### Task 1: Pure `priority()` rule

**Files:**
- Create: `canvas_plus/assignments/priority.py`
- Test: `canvas_plus/assignments/test_priority.py`

**Interfaces:**
- Produces: `priority(due_date: datetime | None, submitted: bool, now: datetime) -> str`, which returns one of the four labels. Also the module constant `DUE_SOON_WINDOW = timedelta(hours=48)`.

- [ ] **Step 1: Write the failing test** `canvas_plus/assignments/test_priority.py`

```python
"""Unit tests for the dashboard urgency label."""
from datetime import datetime, timedelta, timezone

import pytest

from assignments.priority import priority  # pylint: disable=import-error

NOW = datetime(2026, 10, 22, 12, 0, tzinfo=timezone.utc)


@pytest.mark.unit
@pytest.mark.parametrize("due_date, submitted, expected", [
    (NOW + timedelta(hours=48), False, "Due soon"),
    (NOW + timedelta(hours=48, seconds=1), False, "Upcoming"),
    (NOW + timedelta(days=6), False, "Upcoming"),
    (NOW, False, "Due soon"),
    (NOW - timedelta(seconds=1), False, "Past due"),
    (NOW + timedelta(hours=1), True, "Submitted"),
    (NOW - timedelta(days=1), True, "Submitted"),
    (NOW + timedelta(days=6), True, "Submitted"),
    (None, False, "Upcoming"),
])
def test_priority_label(due_date, submitted, expected):
    """Each rule row and boundary from the spec maps to exactly one label."""
    assert priority(due_date, submitted, NOW) == expected
```

- [ ] **Step 2: Run it and watch it fail.** Run `uv run pytest canvas_plus/assignments/test_priority.py -v`. Expected: collection error `ModuleNotFoundError: No module named 'assignments.priority'`.
- [ ] **Step 3: Commit the test.** `git commit -m "test: specify dashboard urgency labels and their boundaries" -- canvas_plus/assignments/test_priority.py` (`git add` the file first).
- [ ] **Step 4: Implement `priority(due_date, submitted, now) -> str`** in `canvas_plus/assignments/priority.py`. It has a module docstring and early returns in the order Submitted → no due date → Past due → Due soon → Upcoming. It imports only `datetime.timedelta`.
- [ ] **Step 5: Run it green.** Run `uv run pytest canvas_plus/assignments/test_priority.py -v`. Expected: 9 passed. Then run `uv run pylint canvas_plus/assignments/priority.py canvas_plus/assignments/test_priority.py`. Expected: no new warnings.
- [ ] **Step 6: Commit.** `git commit -m "feat: compute dashboard urgency label from due date and submission" -- canvas_plus/assignments/priority.py`

---

### Task 2: Fetch overdue work and submission status in the Canvas client

**Files:**
- Modify: `canvas_plus/accounts/canvas_client.py` (`_normalize_assignment`, `_list_course_upcoming_assignments`, `list_upcoming_assignments`)
- Modify: `canvas_plus/accounts/test_canvas_client.py`
- Modify: `README.md` (add the section below)

**Interfaces:**
- Produces: `list_upcoming_assignments(token, courses) -> list[dict]` (same name and signature). Each dict is exactly `{"title": str, "course_name": str, "due_date": datetime | None, "submitted": bool}`. It contains the `upcoming` and `overdue` buckets for every course, sorted as before (due date ascending, `None` last).
- Internal: `_list_course_upcoming_assignments(token, course, base_url, bucket)`.

- [ ] **Step 1: Update existing tests to the new contract.** Each one goes red in Step 2. Use `side_effect` lists in the order *course A upcoming pages, course A overdue pages, course B upcoming…*.
  - `test_upcoming_assignments_are_normalized_and_include_course_name`:
    - Change to `side_effect=[response(assignments), response([])]`.
    - Expected dict gains `"submitted": False`.
    - Assert `get.call_args_list[0]` targets `.../courses/42/assignments` with params `{"bucket": "upcoming", "include[]": "submission"}`.
    - Assert `get.call_args_list[1]` params are `{"bucket": "overdue", "include[]": "submission"}`.
  - `test_upcoming_assignments_preserve_missing_due_date_as_none`: change to `side_effect=[…, response([])]`. Expected dict gains `"submitted": False`.
  - `test_upcoming_assignments_are_sorted_by_due_date_across_courses`: four responses (42 upcoming, 42 overdue = `response([])`, 84 upcoming, 84 overdue = `response([])`). The expected order is unchanged.
  - `test_upcoming_assignments_combine_course_results_and_return_empty_list`: four empty responses, `call_count == 4`. The params list is upcoming, overdue, upcoming, overdue, each with `"include[]": "submission"`.
  - `test_upcoming_assignments_follow_pagination_without_repeating_query_params`: append `response([])` for the overdue call. `call_args_list[0]` params include `include[]`. `call_args_list[1]` params are `None`. `call_args_list[2]` params are the overdue dict.
  - The single-call failure tests (unauthorized link, 401, 403/429/500, malformed) stay as they are. They fail on the first call.
- [ ] **Step 2: Add new failing tests** in the same file:
  - `test_overdue_assignments_are_included_and_sorted_first`. Course 42: the upcoming page holds `{"name": "Soon", "due_at": "2026-10-23T18:30:00Z"}`, and the overdue page holds `{"name": "Late", "due_at": "2026-10-20T18:30:00Z"}`. Assert the titles are `["Late", "Soon"]`.
  - `test_submission_status_is_normalized` (parametrized over the `submission` value, expecting the `submitted` result):
    - key absent → `False`
    - `None` → `False`
    - `{"workflow_state": "unsubmitted", "submitted_at": None}` → `False`
    - `{"workflow_state": "submitted", "submitted_at": "2026-10-21T10:00:00Z"}` → `True`
    - `{"workflow_state": "graded", "submitted_at": None}` → `True`
  - `test_malformed_submission_raises_api_error`, parametrized over `"submitted"`, `["x"]` and `42` as the `submission` value. Each raises `CanvasAPIError`.
  - `test_overdue_request_failure_raises_api_error`: `side_effect=[response([]), response({}, status=500)]` raises `CanvasAPIError`.
  - `test_overdue_request_rejected_token_raises_authentication_error`: `side_effect=[response([]), response({}, status=401)]` raises `CanvasAuthenticationError`.
  - `test_overdue_pagination_rejects_other_origin`: `side_effect=[response([]), response([], next_url="https://untrusted.example/api/v1/assignments")]` raises `CanvasAPIError`, and `get.call_count == 2`.
- [ ] **Step 3: Run it and watch it fail.** Run `uv run pytest canvas_plus/accounts/test_canvas_client.py -v`. Expected: the updated and new assignment tests FAIL (missing `submitted` key, wrong params, `StopIteration` or wrong call count). The course tests still pass.
- [ ] **Step 4: Commit the tests.** `git commit -m "test: require overdue bucket and submission status from Canvas client" -- canvas_plus/accounts/test_canvas_client.py`
- [ ] **Step 5: Implement.**
  - `_normalize_assignment`: add the `submission` validation and `submitted` per Global Constraints. If the key is present and is neither `None` nor a dict, raise `CanvasAPIError("Canvas returned unexpected assignment data. Please try again.")`.
  - `_list_course_upcoming_assignments`: take `bucket` and use it in the first-page params.
  - `list_upcoming_assignments`: loop `for bucket in ("upcoming", "overdue")` inside the per-course loop, then sort as now. Update its docstring to say it returns upcoming **and overdue** assignments with submission status.
- [ ] **Step 6: Run it green.** Run `uv run pytest canvas_plus/accounts -v` (all pass), then `uv run pylint canvas_plus/accounts` (no new warnings).
- [ ] **Step 7: Add the README section.** Insert `## Dashboard known limitations` directly before `## Running tests` in `README.md`, with these bullets, copied from the spec:
  - Overdue work stays listed for as long as the course is active, even if it is months old.
  - Overdue quizzes and external-tool or attendance assignments are not shown as **Past due**, because Canvas's `overdue` bucket excludes them.
  - An overdue assignment that is locked against late submission is not shown, because Canvas excludes work the student can no longer submit.
  - The dashboard makes three Canvas requests per course on each load: upcoming, overdue, and graded.
  - Urgency badges change only when the page is loaded or reloaded; there is no live update.
- [ ] **Step 8: Commit.** `git commit -m "feat: fetch overdue assignments and submission status from Canvas" -- canvas_plus/accounts/canvas_client.py README.md`

---

### Task 3: Show the label on each dashboard card

**Files:**
- Modify: `canvas_plus/assignments/views.py`
- Modify: `canvas_plus/assignments/templates/assignments/assignment_list.html`
- Modify (fixtures only): `canvas_plus/assignments/tests.py`, `canvas_plus/assignments/test_recently_graded.py`, `canvas_plus/features/steps/recently_graded_steps.py`, `canvas_plus/features/steps/assignment_steps.py`

**Interfaces:**
- Consumes: `priority(due_date, submitted, now)` from Task 1. Each assignment dict carries `"submitted": bool` (Task 2's contract; views tests stub the client, so Task 2 need not be merged first).
- Produces: each assignment in `response.context["assignments"]` has `"priority": str`. The badge markup is exactly `<span class="assignment-status assignment-status--{{ assignment.priority|slugify }}">{{ assignment.priority }}</span>`. Task 4 asserts against this.

- [ ] **Step 1: Update the fixtures.** Add `"submitted": False` to every stubbed assignment dict in the four files above:
  - `UPCOMING` in `test_recently_graded.py`
  - the dict near line 117 in `recently_graded_steps.py`
  - `assignment_result` in `assignment_steps.py`
  - every assignment dict in `assignments/tests.py`
  
  Also, in `test_page_renders_assignments_from_canvas`, replace `assertContains(response, 'class="assignment-status"')` with `assertContains(response, 'class="assignment-status assignment-status--')`.
- [ ] **Step 2: Write the failing integration test** in `assignments/tests.py`: `test_each_card_shows_its_urgency_label`. Use the same decorators as `test_page_renders_assignments_from_canvas`.
  - Use `now = timezone.now()`.
  - Stub four assignments:
    - "Turned in": `now + 30h`, submitted
    - "Missed": `now - 2h`, not submitted
    - "Close": `now + 30h`, not submitted
    - "Far": `now + 6 days`, not submitted
  - Assert the response contains each of:
    - `'assignment-status--submitted">Submitted</span>'`
    - `'assignment-status--past-due">Past due</span>'`
    - `'assignment-status--due-soon">Due soon</span>'`
    - `'assignment-status--upcoming">Upcoming</span>'`
  - Assert `[a["priority"] for a in response.context["assignments"]]` equals the four labels in the stubbed order.
- [ ] **Step 3: Run it and watch it fail.** Run `uv run pytest canvas_plus/assignments/tests.py -v`. Expected: the new test and the modified assertion FAIL. Other tests pass.
- [ ] **Step 4: Commit the tests.** `git commit -m "test: require urgency label on each dashboard card" -- <the four fixture files>`
- [ ] **Step 5: Implement.**
  - In `views.py`, import `from django.utils import timezone` and `from .priority import priority`. Immediately after `assignments = list_upcoming_assignments(token, courses)`, take `now = timezone.now()` once. Then, for each assignment, set `assignment["priority"] = priority(assignment["due_date"], assignment["submitted"], now)`.
  - In the template, replace the hard-coded `<span class="assignment-status">Upcoming</span>` **in the Upcoming loop only** with the markup from Interfaces. PR #99's `Graded` badge stays.
  - Add CSS rules to the existing `<style>` block:
    - `.assignment-status--due-soon`: amber background, dark text, e.g. `#fdf0d5` / `#7a4b00`
    - `.assignment-status--past-due`: red, e.g. `#fbe3e1` / `#9b1c13`
    - `.assignment-status--submitted`: grey, e.g. `#eceeed` / `#6b7570`
    - `--upcoming` needs no rule; it inherits the base style.
- [ ] **Step 6: Run it green.** Run `uv run pytest` (whole suite passes; if Task 2 is still in progress, failures confined to `accounts/test_canvas_client.py` are not yours, so report them and continue), then the behave command in Global Constraints (all existing scenarios pass), then `uv run pylint canvas_plus/assignments` (no new warnings).
- [ ] **Step 7: Commit.** `git commit -m "feat: show urgency label on each dashboard assignment card" -- canvas_plus/assignments/views.py canvas_plus/assignments/templates/assignments/assignment_list.html`

---

### Task 4: Acceptance scenarios for issue #41 (Behave)

**Files:**
- Modify: `canvas_plus/features/assignments_page.feature`
- Modify: `canvas_plus/features/steps/assignment_steps.py`

**Interfaces:**
- Consumes: Task 3's badge markup and `response.context["assignments"][i]["priority"]`. Also the existing `prepare_student(context, assignments)` stub, which patches `assignments.views.list_upcoming_assignments`, and the existing `When I open the logged-in home page` / `When I reload the logged-in home page` steps.

- [ ] **Step 1: Append these scenarios verbatim** to `assignments_page.feature`. Their wording is the requirement; do not edit it to fit the code.

```gherkin
  Scenario: Work due within 48 hours is flagged as due soon
    Given I am a connected student with unsubmitted coursework due in 30 hours
    When I open the logged-in home page
    Then I see "Canvas Project 1" marked "Due soon"

  Scenario: Work with ample time is not flagged as high priority
    Given I am a connected student with unsubmitted coursework due in 6 days
    When I open the logged-in home page
    Then I see "Canvas Project 1" marked "Upcoming"
    And I see no high-priority marker

  Scenario: The marker escalates once the deadline window is entered
    Given I am a connected student with unsubmitted coursework due in 50 hours
    And my dashboard shows "Canvas Project 1" marked "Upcoming"
    When 3 hours pass
    And I reload the logged-in home page
    Then I see "Canvas Project 1" marked "Due soon"

  Scenario: A missed deadline shows a past-due warning
    Given I am a connected student with unsubmitted coursework that was due 2 hours ago
    When I open the logged-in home page
    Then I see "Canvas Project 1" marked "Past due"

  Scenario: Submitted work is not flagged as urgent
    Given I am a connected student who has submitted coursework due in 30 hours
    When I open the logged-in home page
    Then I see "Canvas Project 1" marked "Submitted"
```

- [ ] **Step 2: Run behave and watch the new scenarios fail** with undefined steps. Commit: `git commit -m "test: add acceptance scenarios for dynamic priority indicators" -- canvas_plus/features/assignments_page.feature`.
- [ ] **Step 3: Implement the step definitions.** Your design, within these constraints:
  - Due dates are relative to the current time when the Given step runs.
  - "`N` hours pass" moves the clock that the view's `timezone.now()` reads forward by N hours, through a `patch` registered with `context.add_cleanup`. It must not leak into other scenarios.
  - "marked `<label>`" asserts the card for that title carries the `assignment-status--<slug>">label</span>` markup **and** that the context entry for the title has that `priority`.
  - "no high-priority marker" asserts that neither `assignment-status--due-soon` nor `assignment-status--past-due` appears.
  - Reuse `prepare_student` and the existing open/reload steps. Do not add a second stubbing mechanism.
  - **Prove the steps can fail:** temporarily change `DUE_SOON_WINDOW` to `timedelta(hours=24)` and confirm the "due within 48 hours" and "escalates" scenarios go red. Then revert, and report both outputs.
- [ ] **Step 4: Run it green.** Run the behave command (all scenarios pass, including the 24 that existed before), then `uv run pylint canvas_plus/features` (no new warnings).
- [ ] **Step 5: Commit.** `git commit -m "test: implement steps for dynamic priority scenarios" -- canvas_plus/features/steps/assignment_steps.py`

---

### Task 5: Integration gates and PR (orchestrator)

- [ ] Run all four CI gates from the spec (pytest, behave, pylint ≥ 8.0, coverage ≥ 80) and paste their output into the PR.
- [ ] Inspect the git log to confirm each `test:` commit precedes its `feat:` commit.
- [ ] Add an AI-disclosure entry under `README.md` → `### During software development` (`#### Dynamic priority indicators (issue 41)`), matching the existing entries.
- [ ] Run the app against a real Canvas token if one is available, to confirm the Canvas bucket behavior.
- [ ] Push and open a PR against `feat/issue-40-recently-graded`, so the diff shows only #41. Retarget it to `main` after #99 merges. Body: summary, the decisions, the TDD evidence, and `Closes #41`.
