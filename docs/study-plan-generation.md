# Deadline-aware study-plan generation

This feature generates and persists study sessions for a student's selected
assignments. It prepares the student's remaining availability, asks the AI
inference layer for a structured schedule, validates the proposal locally, and
only then saves the plan. Before eligibility filtering, it automatically
estimates effort for selected assignments that do not already have a positive
saved estimate. The generation entry point remains a backend service; this
feature does not add UI wiring or an HTTP endpoint.

**User story:** As a student, I want my selected assignments scheduled into my
free time before their deadlines, so that I can see a practical study plan
without overlapping existing commitments.

## Read the implementation in this order

| File | What to study |
| --- | --- |
| `canvas_plus/study_plan/generate.py` | The orchestration, assignment scoping and eligibility, bounded inference retry, and atomic persistence. |
| `canvas_plus/study_plan/availability_windows.py` | User-specific availability preparation, time-zone and daylight-saving resolution, interval merging, and removal of existing sessions. |
| `canvas_plus/study_plan/prompt.py` | Earliest-deadline-first ordering and the structured assignment/window payload sent to inference. |
| `canvas_plus/study_plan/effort_estimation.py` | Assignment effort estimation, persistence, and validation of the estimate input. |
| `canvas_plus/study_plan/schema.py` | The Pydantic response contract for sessions and notices. |
| `canvas_plus/study_plan/validation.py` | Local checks for time windows, overlaps, deadlines, late flags, and estimated effort. |
| `canvas_plus/study_plan/models.py` | The persisted plan and session records. |
| `canvas_plus/study_plan/exceptions.py` | The service-level errors callers can handle. |
| `canvas_plus/study_plan/test_generate_plan.py` | Integration coverage for selection, retries, persistence, deadlines, and remaining effort. |
| `canvas_plus/study_plan/test_effort_estimation.py` | Focused coverage for estimation inputs, estimate persistence, and manual overrides. |
| `canvas_plus/study_plan/test_availability_windows.py` and `canvas_plus/study_plan/test_validation.py` | Focused tests for interval preparation and proposal rules. |

## Models at a glance

| Model | Purpose | Key rules |
| --- | --- | --- |
| `Assignment` | A Canvas assignment selected for planning | Stores its description, nullable `estimated_effort_minutes`, and estimate source; an assignment is schedulable only when it has a due date and a positive effort estimate. |
| `StudyPlan` | One generated plan for a user | Required user FK (CASCADE); `created_at`; JSON `notices` list. |
| `StudySession` | One scheduled block in a plan | Required plan and assignment FKs (CASCADE); aware `start` and `end`; `late` records whether the session ends after its assignment deadline. |

The assignment estimate is added by
`canvas_plus/assignments/migrations/0004_assignment_estimated_effort_minutes.py`.
Apply migrations before using the planner.

## Generation flow

`generate_plan(user, assignment_ids, allow_late=False)` owns the full
generate/validate/persist flow:

1. Duplicate IDs are removed while retaining request order. An empty selection
   raises `EmptyAssignmentSelectionError`.
2. Assignments are queried by both primary key and user. If any requested ID is
   not owned by that user or does not exist, the call raises
   `InaccessibleAssignmentError`; it does not silently plan a partial selection.
3. Before eligibility filtering, each assignment without a positive saved
   estimate is passed to the existing effort estimator with its title, due
   date, and description. Successful estimates are saved as positive minutes
   and marked automatic. Existing positive manual or automatic estimates are
   reused without being refreshed.
4. An assignment that cannot be estimated because required information is
   missing or estimation raises `AIInferenceError` remains without a usable
   estimate. Eligibility filtering skips it with a notice; other selected
   assignments continue. Assignments without due dates are also skipped. If no
   eligible assignments remain, `NoEligibleAssignmentsError` is raised.
5. The user's availability is trimmed to the future, overlapping or adjacent
   windows are merged, and sessions from their earlier plans are subtracted.
   If no free interval remains, `NoUsableAvailabilityError` is raised.
6. Eligible assignments are ordered by due date and serialized with the free
   windows. Inference returns a `StudyPlan` response containing one or more
   sessions and optional notices.
7. Every proposal is validated. A planning inference or validation failure triggers
   one retry; after two failed attempts, the service raises
   `StudyPlanRetriesExhaustedError`.
8. Once a proposal passes, the plan and all its sessions are written in one
   database transaction. Invalid or failed proposals create no plan rows.

Effort estimates are saved separately as they are generated. If a later
availability check or planning attempt fails, those estimates remain on their
assignments and are reused on a subsequent request. Estimation failures are
handled per assignment and do not consume the planner's inference retry
attempts.

## Scheduling rules

Each proposed session must reference an assignment in the eligible selection,
have timezone-aware start and end times, and fit wholly inside one prepared
free interval. Its duration must be a positive multiple of 15 minutes. There
is no global maximum duration; the available interval and assignment deadline
bound it.

Sessions in the same proposal cannot overlap one another or any previously
saved session for that user. Touching interval boundaries are allowed. A
session ending exactly at its assignment deadline is on time. If it ends after
the deadline, its `late` flag must be true and the caller must explicitly pass
`allow_late=True`; late sessions must still fit in the user's availability.

The total proposed minutes for an assignment cannot exceed its estimate.
After validation, the plan's notices combine AI-provided notices, explanations
for skipped assignments, and notices for estimated effort that could not be
scheduled. A sub-15-minute remainder can be reported even though sessions
themselves must use 15-minute increments.

Availability uses Django's configured `TIME_ZONE`. Nonexistent local times
during a spring daylight-saving transition move forward to the next valid
minute; repeated times during the fall transition use standard time. Prepared
windows and persisted session values are aware datetimes.

## Service errors

| Exception | Meaning |
| --- | --- |
| `EmptyAssignmentSelectionError` | No assignment IDs were supplied. |
| `InaccessibleAssignmentError` | At least one requested assignment is missing or belongs to another user. |
| `NoEligibleAssignmentsError` | None of the selected assignments has both a due date and a positive effort estimate. |
| `NoUsableAvailabilityError` | The user has no future availability left after existing sessions are removed. |
| `StudyPlanRetriesExhaustedError` | Inference failed or its proposals failed validation on both attempts. |

All are subclasses of `StudyPlanError`. `PlanValidationError` is used internally
to trigger an inference retry; callers of `generate_plan` receive
`StudyPlanRetriesExhaustedError` if retries are exhausted.

## Integration example

Call the service with the authenticated user and local assignment IDs. Late
scheduling is off unless the caller deliberately opts in:

```python
from study_plan.generate import generate_plan
from study_plan.exceptions import StudyPlanError

try:
    plan = generate_plan(request.user, assignment_ids)
except StudyPlanError as error:
    # Translate the service failure into the calling interface's response.
    ...
```

The return value is a persisted `StudyPlan`; its sessions are available through
`plan.sessions`, and its notices through `plan.notices`.

## Boundaries

- The planner only handles assignments already stored locally; it does not
   fetch assignments or assignment descriptions from Canvas during generation.
- The feature provides a service function, not UI wiring or an HTTP endpoint.
- Missing estimates are generated during this flow when the assignment has
   enough information. A positive estimate already saved on an assignment is
   reused regardless of whether it is manual or automatic.
- The AI output is never trusted as the final schedule: local validation is
  required before persistence.
- Previously saved sessions reserve time but are not automatically regenerated
  or moved when availability or assignment details change.

Run the focused planner tests from the repository root with:

```sh
/coursework/Canvas_Plus/.venv/bin/python -m pytest canvas_plus/study_plan/test_generate_plan.py canvas_plus/study_plan/test_availability_windows.py canvas_plus/study_plan/test_validation.py
```