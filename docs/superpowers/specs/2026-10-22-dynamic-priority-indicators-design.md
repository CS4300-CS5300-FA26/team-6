# Dynamic Priority Indicators — Design (Issue #41, 3.2.1-d)

**Status:** Draft for approval · **Date:** 2026-10-22 · **Due:** today 4pm MDT
**Branch:** `feat/dynamic-priority-indicators`, stacked on PR #99 (`feat/issue-40-recently-graded`), which is stacked on PR #98 (#39). Merge order: #98 → #99 → this.

## Intent

> **As an** enrolled college student, **I want** my tasks labeled with dynamic urgency tags based on submission windows, **so that** I can instantly spot work that needs prompt attention.

Today every card on the dashboard's Upcoming list carries a hard-coded "Upcoming" badge. This story makes that badge tell the truth: is the work submitted, past due, due soon, or not yet urgent?

## Acceptance criteria (from the issue) and how each is met

| Issue scenario | How it is satisfied |
|---|---|
| Due within 48 h and not submitted → highlighted priority marker | Badge reads **Due soon**, highlighted (amber) |
| Ample time → no high-priority label | Badge reads **Upcoming** (current styling, unchanged) |
| Previously unmarked item crosses into threshold → indicator updates automatically | Label is recomputed from the current time on **every page load**; after time passes, a reload shows **Due soon** (decided: reload, not live JS) |
| Deadline lapsed → past-due warning tag | Badge reads **Past due** (red); overdue work is now fetched from Canvas |

## Decisions (made with the user)

1. **Recompute on page load.** No JavaScript timers. "Automatically" means the server computes the label each time the dashboard is opened or reloaded.
2. **Badge rule**, evaluated in this order:

   | Condition | Label |
   |---|---|
   | Student has submitted | **Submitted** (greyed out) |
   | `due_date < now` | **Past due** |
   | `due_date - now <= 48 hours` | **Due soon** |
   | otherwise, including no due date | **Upcoming** |

   Exactly 48 h remaining is **Due soon**.
3. **"Submitted"** means Canvas reports a `submitted_at` timestamp **or** the submission's `workflow_state` is `"graded"`.
4. **Extend `accounts/canvas_client.py`; no second client.** It already owns token handling, origin checks, pagination-URL validation, and response-shape validation. A second client would duplicate or reach into those private helpers.
5. **The urgency rule lives in `assignments/priority.py`**, a pure function, not a model method. Assignments are fetched live from Canvas as dicts and never stored. This mirrors PR #99's `assignments/grades.py`, so the dashboard follows one pattern.
6. **Stack on PR #99.** A dry-run merge is clean, and all three PRs merge today.
7. **Known limitations are documented, not fixed** (see below).

## Canvas facts this design relies on

From the Canvas API docs and `instructure/canvas-lms` `lib/sorts_assignments.rb`:

- `bucket` takes a **single** value per request.
- `upcoming` = has a due date between now and **1 week** from now. It does **not** filter by submission status.
- `overdue` = past due, **not submitted or graded**, expects a submission (excluding `external_tool`, `online_quiz`, `attendance`), and the student can still submit.
- `include[]=submission` adds the requesting student's `submission` object. **If the student has no submission, the key is absent.** Canvas may also return a submission with `workflow_state: "unsubmitted"` and `submitted_at: null`, so the key being present does not mean the work was submitted.
- `due_at` already reflects per-student overrides.

## Design

Data flows one way: **client fetches → `priority()` decides → template displays.**

### 1. `accounts/canvas_client.py` (extend)

- `_list_course_upcoming_assignments(token, course, base_url)` gains a `bucket` argument. Its first-page params become `{"bucket": bucket, "include[]": "submission"}`. Pagination is unchanged: params are `None` after the first page because the `next` link carries the query.
- `list_upcoming_assignments(token, courses)` calls that function for each course, **`"upcoming"` first and then `"overdue"`**, and combines the results. The existing due-date sort is unchanged, so past-due items rise to the top.
- `_normalize_assignment` adds `"submitted": bool` to each result:
  - `submission` key absent or `None` → `False`
  - `submission` present but not a dict → raise `CanvasAPIError("Canvas returned unexpected assignment data. Please try again.")`
  - otherwise → `submission.get("submitted_at") is not None or submission.get("workflow_state") == "graded"`
- **Our call:** the public name `list_upcoming_assignments` stays the same. Renaming it would ripple through #98's and #99's view tests and Behave patches. Its docstring is updated to say it returns upcoming **and overdue** work.
- The two buckets don't overlap: one is in the future, the other in the past. No de-duplication is needed.

### 2. `assignments/priority.py` (new)

```python
DUE_SOON_WINDOW = timedelta(hours=48)

def priority(due_date, submitted, now):
    """Return the dashboard badge label for one assignment."""
```

Returns one of `"Submitted"`, `"Past due"`, `"Due soon"`, `"Upcoming"`, following the rule table above. It is pure: no Django imports beyond what's needed, no database, no network. `now` is passed in, which is what makes it testable at exact boundaries. Unlike `recent_grades(..., now=None)`, `now` is required here, because the view always supplies it.

### 3. `assignments/views.py`

After `list_upcoming_assignments(...)` returns, the view takes **one** `now = timezone.now()` and sets `assignment["priority"] = priority(assignment["due_date"], assignment["submitted"], now)` on each item. Using one `now` keeps every badge on the page consistent. Nothing else in the view changes; error handling stays the same.

### 4. `assignments/templates/assignments/assignment_list.html`

- In the Upcoming loop, the hard-coded `Upcoming` becomes `{{ assignment.priority }}`.
- The badge gets a modifier class `assignment-status--{{ assignment.priority|slugify }}`, which produces `--submitted`, `--past-due`, `--due-soon` or `--upcoming`.
- CSS, added to the existing `<style>` block. **Our call** on colors:
  - `--upcoming`: current green, no change
  - `--due-soon`: amber background with dark text
  - `--past-due`: red background with white or dark-red text
  - `--submitted`: grey background with muted text
- The state is carried by the **text**, not color alone, which is an accessibility requirement.
- PR #99's "Recently graded" section and its "Graded" badge are untouched.

### 5. `README.md` — known limitations

- Overdue work stays listed for as long as the course is active, even if it is months old.
- Overdue quizzes and external-tool or attendance assignments are not shown as **Past due**, because Canvas's `overdue` bucket excludes them.
- An overdue assignment that is locked against late submission is not shown, because Canvas excludes work the student can no longer submit.
- The dashboard now makes three Canvas requests per course on each load: upcoming, overdue, and graded (#99).
- Badges change only on reload; there is no live update.

## Test strategy — TDD, red → green → refactor

Every task follows the same loop, and the git history shows it:

1. Write the test(s) first. **Run them and watch them fail for the expected reason** (an assertion or a missing name, not a typo).
2. Commit them as `test: …`.
3. Write the minimum code to pass, run the full relevant suite to green, then commit as `feat: …` (or `fix:`/`style:`).
4. Refactor only while green.

This matches the repository's existing `test:` → `feat:` commit pattern. The builder reports the red output for each task.

| Level | File | What it proves |
|---|---|---|
| Unit | `assignments/test_priority.py` (new) | Each rule row; the boundaries at **48 h exactly** (Due soon), **48 h + 1 s** (Upcoming), **due == now** (Due soon), **1 s past due** (Past due); submitted wins over past due and due soon; `due_date=None` → Upcoming |
| Unit (HTTP boundary) | `accounts/test_canvas_client.py` (extend) | Both buckets are requested per course, in order, each with `include[]=submission`; overdue results appear in the combined, sorted list; `submitted` is True for `submitted_at`, True for `workflow_state="graded"`, False for a missing key and for `unsubmitted`; a non-dict `submission` raises `CanvasAPIError`. **Existing tests that use `side_effect=[...]` must add one overdue-page response per course after that course's upcoming pages.** Existing assertions on params now include `include[]`. |
| Integration | `assignments/tests.py` (extend) | The rendered page shows each of the four labels and the matching modifier class for fixtures with known due dates and submitted flags. Existing fixtures gain `"submitted": False`. |
| Acceptance (Behave) | `features/assignments_page.feature` + `features/steps/assignment_steps.py` (extend) | One scenario per issue criterion, in domain language. Due dates are set **relative to the real current time** (e.g. "due in 30 hours"). The "crosses the threshold" scenario first shows **Upcoming** at 50 h out, then advances the clock (patch `django.utils.timezone.now` with cleanup) by 3 h, reloads, and shows **Due soon**. Behave fixtures (`assignment_result`) gain `"submitted"`. |

**Existing tests that must change, because the view now reads `assignment["submitted"]` and the client contract always includes it.** We trust that internal contract (AGENTS.md: "trust internal invariants") rather than defaulting with `.get`. Every stubbed assignment dict gains `"submitted": False`:

- `assignments/tests.py`. Also, its assertion `assertContains(response, 'class="assignment-status"')` becomes an assertion on the new modifier class.
- `assignments/test_recently_graded.py` (`UPCOMING` fixture, from #99)
- `features/steps/recently_graded_steps.py` (from #99)
- `features/steps/assignment_steps.py` (`assignment_result`)

The fourth Behave scenario (past due) stubs `list_upcoming_assignments` to return an item whose due date is in the past, as the client now would. The client's actual overdue fetch is proven at the unit level.

**Gates before PR** (same as CI, run from repo root unless noted):

- `uv run pytest`
- `cd canvas_plus && uv run python manage.py behave --settings=canvas_plus.settings_test`
- `uv run pylint --fail-under=8.0 .` (no new warnings in touched files)
- `uv run coverage run --source=canvas_plus,src -m pytest && uv run coverage report --fail-under=80`

## Non-goals

- Live badge updates without a reload (JavaScript, polling, websockets).
- Persisting assignments or adding fields to the unused `Assignment` model. Its removal is a separate cleanup.
- Changing PR #99's Recently graded section, or merging its pagination helper with ours (#99 lists that as a follow-up).
- Configurable thresholds or user preferences.
- Fixing the Canvas bucket exclusions listed under limitations.

## Anti-goals (a failure even if the tests pass)

- Badges disagree on the same page because each computed its own `now`.
- A student's token is sent anywhere new, or pagination validation is bypassed for the new bucket.
- A missing `submission` key crashes the page instead of meaning "not submitted".
- Color alone conveys urgency.
- Existing #98/#99 behavior regresses: empty state, expired-token prompt, unavailable message, Recently graded section.

## Left to the builder

- Exact hex colors within the stated palette.
- Test function names and fixture helpers.
- Whether `priority.py` uses early returns or a single expression. Keep it readable.
