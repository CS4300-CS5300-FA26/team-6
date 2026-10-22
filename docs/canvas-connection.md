# Canvas connection implementation and study guide

Issue #38 connects an existing Canvas+ user to their school's Canvas account using
a personal access token. It validates the token, lists enrolled courses, saves the
connection across sessions, and requests reconnection when Canvas rejects a saved
credential. Assignment importing belongs to issue #39.

## Read the implementation in this order

| File | What to study |
| --- | --- |
| `canvas_plus/accounts/forms.py` | A plain Django Form requires a token, strips surrounding whitespace, and uses PasswordInput with render_value=False. The 64-character limit follows Canvas's current token generation length. |
| `canvas_plus/accounts/urls.py` | The named connect_canvas route exposes /accounts/connect-canvas/. |
| `canvas_plus/accounts/views.py` | The view coordinates validation, the external API request, saving, and template context. It requires login, protects sensitive POST data in error reports, and disables response caching. |
| `canvas_plus/accounts/canvas_client.py` | The service module makes authenticated HTTP requests, follows pagination, validates returned course data, and translates failures into application exceptions. |
| `canvas_plus/accounts/models.py` | CanvasConnection owns encrypted credentials and their per-user database relationship. |
| `canvas_plus/accounts/migrations/0001_initial.py` | Django's migration creates the connection table, unique user relationship, and foreign key. |
| `canvas_plus/accounts/connections.py` | connection_status checks saved credentials and returns banner context for the current home page. |
| `canvas_plus/assignments/views.py` | The current signed-in home page invokes that check. The root URL already redirects signed-in students here. |
| `canvas_plus/accounts/templates/accounts/connect_canvas.html` | The page displays the form, errors, success, course names, and saved-token suffix. Django escapes course names. |
| `canvas_plus/templates/base.html` | Shared navigation links to Connect Canvas, and the shared banner provides reconnect or temporary-error feedback. |

## A successful connection

1. A signed-in student opens the connection page. GET creates an unbound form and
   queries only that student's saved connection. The template receives the suffix,
   never the saved plaintext or ciphertext.
2. Submitting the form sends POST data with a CSRF token. The view binds even empty
   POST data, allowing required-field errors to appear. Cleaned form data establishes
   that a token was supplied; it does not establish that Canvas accepts it.
3. list_courses sends GET /api/v1/courses to CANVAS_BASE_URL with active student
   enrollment filters and the token in the Authorization bearer header. The token
   is never added to the URL.
4. Each successful response contributes a page of courses to one combined list.
   The next URL comes from the Link header. Only the first request receives the
   initial query parameters; Canvas's next URL already carries its own parameters.
5. After every page succeeds, the view encrypts the token and saves the connection.
   Empty enrollment lists still represent successful authentication.
6. The template displays "Canvas connected" and enrolled course names. Reopening
   the page displays a masked prefix and the final four token characters, with an
   empty password field.

## Database fields and encryption

CanvasConnection has a one-to-one user relationship, encrypted_token, token_last_four,
canvas_url, is_valid, and updated_at. Django's unique relationship permits only one
connection per user. The cascade deletes the connection when its user is deleted.

set_token encrypts the token before assigning it to a database field. get_token
decrypts it only when the server needs to authenticate to Canvas. Fernet provides
authenticated encryption: ciphertext that has been modified is rejected. A separate
environment key is required; the implementation never silently falls back to
plaintext or a default encryption key.

The display suffix is intentionally unencrypted. It lets the view show the required
last four characters without decrypting the credential. The password input's masking
is a browser display feature; it does not replace encryption at rest or HTTPS in transit.
The storage decision and its consequences are recorded in
[the Canvas token storage ADR](adr/0001-canvas-token-storage.md).

## Failure and reconnect behavior

| Condition | Result |
| --- | --- |
| Blank token | A required-field error appears; Canvas is not contacted. |
| Canvas returns 401 during submission | The form displays "Invalid token. Check your token and try again." A previously saved connection is preserved. |
| Canvas returns 403, 429, or a server error | A service error appears; it is not classified as an expired credential. |
| Timeout, network failure, malformed JSON, or an unexpected payload | A safe error appears, without reflecting the token or raw request exception. |
| Missing Canvas configuration or encryption key | Saving fails closed with administrator feedback. Other parts of the app can still start. |
| Saved token receives 401 when opening the home page | is_valid becomes false and the page displays "Your Canvas connection expired. Please reconnect." with the connection-page link. |
| Canvas is temporarily unavailable during a saved-token check | A retry banner appears and the saved token remains valid. |
| Saved ciphertext cannot be read or the configured Canvas host changed | The credential is not sent to the new host; the student is asked to reconnect. |
| Student submits a valid replacement | The existing row is updated and is_valid becomes true again. |

Pagination URLs must retain the configured scheme, host, and effective port. URLs
containing embedded credentials are rejected. Automatic redirects are disabled so
the client does not follow an unexpected authentication destination. Repeated links
and chains over 100 pages fail rather than looping or silently returning partial results.
Production origins require HTTPS; HTTP is permitted only for loopback testing.

## Automated tests

`accounts/test_canvas_connection.py` implements the four original acceptance cases
using a loopback fake Canvas HTTP server. Django routes, templates, sessions, and the
database remain real. The fake server accepts a made-up token, supplies known courses,
and can revoke that token. New browser sessions check that storage persists.

Additional cases cover encrypted storage, rejected replacements, successful reconnection,
user isolation, authentication, CSRF, blank submissions, missing or malformed keys,
changed Canvas hosts, corrupted ciphertext, temporary outages, and zero enrollments.

`accounts/test_canvas_client.py` replaces HTTP calls with controlled responses to check
pagination, authentication on later pages, origin checks, HTTP errors, timeout handling,
and payload validation. The tests use no real personal access tokens.

`features/connect_canvas.feature` contains the original Given/When/Then scenarios.
Its step definitions mock the external API while retaining real forms, views, encrypted
storage, and sessions. Existing generic text-check steps are reused.

From a development environment with dependencies installed:

```sh
export DJANGO_DEBUG=False
export DJANGO_SECRET_KEY=test-only-secret
python -m pytest
pylint --fail-under=8.0 .
uv lock --check
python canvas_plus/manage.py check
python canvas_plus/manage.py makemigrations --check --dry-run
coverage run --source=canvas_plus,src -m pytest
coverage report -m --fail-under=80
```

Run Behave from the Django project directory:

```sh
cd canvas_plus
python manage.py behave --settings=canvas_plus.settings_test
```

The original four tests were observed failing before the feature was implemented.
Additional client tests were also run against the incomplete client before its error
and security handling were added. Browser appearance and a real school account remain
manual verification tasks; automated tests validate the simulated API contract.

## Setup and deployment

Run uv sync --extra dev, configure CANVAS_BASE_URL and CANVAS_TOKEN_ENCRYPTION_KEY,
and apply migrations. Generate a Fernet key once using the README command and keep it
stable across app restarts and deployments. Store production values in the hosting
platform's environment, never in source control. The existing Heroku release command
runs the accounts migration automatically when the branch is eventually deployed.

No real school token or production secret is required to run the tests: they supply
their own fake API origin and temporary encryption key. A production administrator
must supply the actual settings before students connect. Losing or replacing the key
makes saved credentials unreadable and requires reconnection; automatic key rotation
is outside this issue.

Saved connections are checked synchronously on each request to the current assignments
home page. Every outbound request has a ten-second connection/read timeout, which is
not a total wall-clock deadline for a complete paginated request. A later dashboard
or synchronization feature should reuse the client and deliberately decide its
refresh policy. Existing assignment records are not imported or changed by this feature.

## External references

- [Canvas courses API](https://developerdocs.instructure.com/services/canvas/resources/courses)
- [Canvas pagination](https://developerdocs.instructure.com/services/canvas/basics/file.pagination)
- [Canvas token generation](https://github.com/instructure/canvas-lms/blob/master/app/models/access_token.rb)
- [Fernet authenticated encryption](https://cryptography.io/en/latest/fernet/)
