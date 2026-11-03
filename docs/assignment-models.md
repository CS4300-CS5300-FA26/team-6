# Assignment uploads, StudyFile, and Attachment models (issue #42)

Issue #42 lets a student attach and manage files on their assignments. This
implementation includes user-owned local assignment records, reusable files,
and uploads from assignment cards. Attachments and the estimates planned in
issue #49 can persist independently of live Canvas API calls.

**User story:** As a student, I want user-owned local Canvas assignment records
and reusable files, so attachments and future estimates can persist
independently.

## Read the implementation in this order

| File | What to study |
| --- | --- |
| `canvas_plus/assignments/models.py` | The three models, the uuid storage path, and the ownership `clean()` that `save()` enforces. |
| `canvas_plus/assignments/migrations/0003_assignment_user_studyfile_attachment.py` | The preflight that refuses legacy rows, then adds the required `user` key with no default. |
| `canvas_plus/assignments/test_models.py` | Unit tests for ownership, uniqueness, reuse, unlink, and cascade behavior. |
| `canvas_plus/assignments/test_migrations.py` | MigrationExecutor tests: applies on an empty prior schema, refuses and preserves legacy rows. |

## Models at a glance

| Model | Purpose | Key rules |
| --- | --- | --- |
| `Assignment` | One local record of a Canvas assignment | required `user` FK (CASCADE); `title` (200) and `course` (100); nullable `due_date` for undated Canvas items; required `canvas_course_id` / `canvas_assignment_id`; unique per `(user, canvas_assignment_id)` |
| `StudyFile` | One uploaded, reusable file | required `user` FK (CASCADE); `FileField` on the default Django storage under `study_files/<user id>/<uuid>.<ext>`; `original_name` (255); `size`; `uploaded_at` |
| `Attachment` | One link between an assignment and a study file | required `user` FK (CASCADE) — all three models are user-owned by team decision; FKs to `assignment` and `study_file` (CASCADE, related name `attachments`); `category` (50, blank allowed, no frozen choices); unique per `(assignment, study_file)` |

## Acceptance scenarios

Automated in `test_models.py` (unit) and `test_migrations.py` (migrations).

### Assignment ownership and Canvas identity

```gherkin
Given two students who both mirror Canvas assignment 101
When each saves their own Assignment row
Then both rows exist, because uniqueness is per (user, canvas_assignment_id)

Given a student who already mirrors Canvas assignment 101
When they save a second row with the same canvas_assignment_id
Then the database rejects the duplicate

Given a student saving an assignment with no due date and no attachments
When the row is saved and reloaded
Then due_date is null and the attachment list is empty
```

### Reusable study files

```gherkin
Given a student who uploads two files with the same original name
When both are saved
Then each lands under study_files/<user id>/ with a distinct uuid name
And the stored bytes exist on disk

Given a student who deletes their account
When the user row is deleted
Then their StudyFile rows cascade away, but the stored files remain on disk
```

### Attachments

```gherkin
Given a student's assignment and their study file
When they link them with objects.create
Then the link shows in assignment.attachments and study_file.attachments
And starts with a blank category

Given one study file and two of the student's assignments
When the file is linked to both
Then both links exist

Given a link whose user, assignment owner, or study file owner differ
When objects.create runs, for any mismatch permutation
Then save() runs the ownership clean() and ValidationError rejects the link

Given an (assignment, study_file) pair that is already linked
When a second link is created
Then the database rejects the duplicate
```

### Unlinking versus deleting

```gherkin
Given a linked file
When only the Attachment row is deleted
Then the StudyFile row, its bytes on disk, and the assignment all remain

Given a linked file
When the assignment is deleted
Then its attachments cascade away, but the StudyFile row and bytes remain
```

## Integration example: get_or_create with defaults

When first attaching a file or saving an estimate, use `(user, canvas_assignment_id)` to create the local row on demand:

```python
from assignments.models import Assignment

assignment, created = Assignment.objects.get_or_create(
    user=request.user,
    canvas_assignment_id=canvas_id,
    defaults={
        "title": canvas_title,       # from the Canvas API
        "course": course_name,
        "canvas_course_id": canvas_course_id,
        # due_date omitted: it stays null for undated Canvas assignments
    },
)
```

A later save with the same Canvas id returns the same row (`created` is False)
and never overwrites the stored defaults.

## Ownership validation and its limits

`Attachment.clean()` compares the user of the link, the assignment, and the
study file, and raises `ValidationError` when they do not match.
`Attachment.save()` calls that focused `clean()` before writing, so
`objects.create()` cannot bypass ownership. It deliberately does not run a full
`full_clean()` on every save.

**Limit:** bulk writes skip `Model.save()` entirely. `bulk_create()`,
queryset `update()`, and raw SQL bypass this validation. Uploads scope writes
to `request.user` and verify the assignment against that student's live Canvas
data; future attachment write endpoints must enforce the same ownership rules.

## Migration policy for legacy rows (0003)

Migration `0003_assignment_user_studyfile_attachment` extends the existing
Assignment table; it never deletes data or guesses owners:

1. A RunPython **preflight runs as the first operation**. If any historical
   Assignment row exists, it raises a `RuntimeError` telling the operator to
   export those rows (title, course, due_date), reconcile or remove them so the
   table is empty, and re-run the migration. Nothing is changed.
2. Only then are the required `user` FK, the required Canvas ids, and the
   nullable `due_date` added. The fields carry **no default** — the preflight
   proved the table empty, so no artificial user or Canvas id is ever written.
3. `StudyFile` and `Attachment` are created, then the two unique constraints.
   The reverse code is a documented noop.

Run `python manage.py migrate` before using these models. Databases with legacy
rows need the reconciliation above first. Keep the dashboard on live Canvas data;
page loads must not create or synchronize local rows. Matching live assignments to
local data uses the Canvas assignment ID and the signed-in user.

## Upload flow and limits

The signed-in student chooses one or more files on an assignment card. The POST
validates the whole batch before loading Canvas data, then verifies both the
course and assignment IDs against the student's current Canvas assignments.
An empty batch or unavailable Canvas data is rejected; an assignment outside
that list returns 404 without saving anything.

The combined batch limit is **26,214,400 bytes (25 MiB)**, inclusive. The UI calls
this 25 MB; larger batches receive **"File batch exceeds 25 MB limit"**. Files
are saved together with their StudyFile and Attachment rows in a database
transaction, creating the local Assignment on demand. If any write fails, all
database writes roll back and cleanup attempts to delete every file already
stored for that batch. Cleanup failures are logged and do not stop the remaining
cleanup attempts. The student receives a retry message rather than partial success.

Each valid upload reloads Canvas data once during the POST and once on the
redirect to the assignment list. This is a known cost that could later be
reduced with a single-assignment lookup.

## Upload storage

With all four Bucketeer variables empty or absent, uploads use Django's
FileSystemStorage in `canvas_plus/media/` (ignored by Git). Tests explicitly use
filesystem storage. Production sets all four: `BUCKETEER_AWS_ACCESS_KEY_ID`,
`BUCKETEER_AWS_SECRET_ACCESS_KEY`, `BUCKETEER_AWS_REGION`, and
`BUCKETEER_BUCKET_NAME`. Partial configuration fails at startup, naming missing
variables without disclosing their values.

The all-empty fallback also applies with `DEBUG=False`: startup checks detect
partial configuration, not an entirely missing production configuration. Verify
all four variables on Heroku before deploying uploads; local dyno storage is
ephemeral and cannot preserve the uploaded bytes across restarts.

Complete configuration selects `storages.backends.s3.S3Storage` with private
defaults (`default_acl=None`, `querystring_auth=True`, `file_overwrite=False`).
There is no custom domain or `public/` prefix: uploads remain under
`study_files/<user id>/` in the private bucket. Bucketeer's `public/` prefix is
world-readable and must not be used for these uploads. There is no public media
route. Static files retain their WhiteNoise backend, with Django's plain static
backend in tests.

The provisioned Heroku Bucketeer add-on uses the **Hobbyist** plan
(~$0.007/hour, max $5/month): **5 GB storage**, **5 GB bandwidth**, and
**0 days data retention**. Upgrade (Micro, max $15/month) before either quota
is reached.

## Boundaries (deliberately out of scope here)

- Downloads and unlinking through the UI remain later work.
- Uploading to assignments without dashboard cards is not supported.
- Category choices and picker UX: issue #44; the field stays a free 50-character string.
- Estimate fields on Assignment: issue #49.
- Physical file deletion when a StudyFile row goes away: no delete logic exists
  by design; unlinking preserves both the row and the stored bytes.
