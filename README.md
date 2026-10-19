# Canvas Plus

Canvas Plus is the CS 4300/5300 Fall 2026 Team 6 group project. It is a Django application with `accounts` and `assignments` apps.

## Current project structure

```text
team-6/
├── .github/
│   └── workflows/
│       └── ci-cd.yaml           # CI/CD pipeline (lint, test, coverage, deploy)
├── canvas_plus/                 # Django project root
│   ├── assignments/             # Assignments Django app
│   │   ├── migrations/
│   │   ├── admin.py
│   │   ├── apps.py
│   │   ├── templates/assignments/
│   │   │   └── assignment_list.html
│   │   ├── models.py
│   │   ├── tests.py
│   │   ├── urls.py
│   │   └── views.py
│   ├── accounts/                # Accounts Django app
│   │   ├── templates/accounts/
│   │   │   ├── login.html
│   │   │   └── register.html
│   │   ├── __init__.py
│   │   ├── apps.py
│   │   ├── forms.py
│   │   ├── tests.py
│   │   ├── urls.py
│   │   └── views.py
│   ├── canvas_plus/             # Django project configuration
│   │   ├── settings.py
│   │   ├── urls.py
│   │   ├── asgi.py
│   │   └── wsgi.py
│   └── manage.py
├── src/                         # Placeholder module used by the CI pipeline
│   └── main.py
├── tests/                       # pytest tests run by the CI pipeline
│   └── test_main.py
├── pyproject.toml               # Pinned dependencies plus lint/test tooling (dev extra)
└── README.md
```

Local-only files such as `.venv/`, Python bytecode, and `db.sqlite3` are excluded from version control.

## Prerequisites

- Git
- Python 3.14
- `pip`

The pinned Python dependencies, including Django 6.1.1, are listed in `pyproject.toml`. Lint and test tools are in the `dev` optional dependency group.

## Local installation

Clone the repository and enter its directory:

```console
git clone git@github.com:CS4300-CS5300-FA26/team-6.git
cd team-6
```

Create a virtual environment with Python 3.14. If your prompt shows `(base)`, run `conda deactivate` first, or the venv may be built with conda's Python instead.

macOS or Linux:

```console
python3.14 -m venv .venv
```

Windows:

```console
py -3.14 -m venv .venv
```

Activate it with the command for your shell.

Fish:

```fish
source .venv/bin/activate.fish
```

Bash or Zsh:

```bash
source .venv/bin/activate
```

Windows (PowerShell or Command Prompt):

```console
.venv\Scripts\activate
```

Confirm the venv uses Python 3.14:

```console
python --version
```

Install the project dependencies:

```console
python -m pip install -e ".[dev]"
```

Create a local environment file from the example in the repository root:

```console
cp env.example .env
```

Edit `.env` to set local values. `DJANGO_DEBUG=True` enables Django debug mode, and
`DJANGO_SECRET_KEY` in the example is only a development placeholder. The Django
settings load `.env` automatically for local runs. `.env` is ignored by Git; do
not commit it or use the example secret in production. Configure production
secrets through the server's environment variables instead.

## Running the application

From the repository root, enter the Django project directory and apply the database migrations:

```console
cd canvas_plus
python manage.py migrate
```

Start the development server:

```console
python manage.py runserver
```

Open <http://127.0.0.1:8000/assignments/> to see the Assignments page, which confirms the project is running. 
The Django administration site is at <http://127.0.0.1:8000/admin/>. Create an administrator account with `python manage.py createsuperuser` to sign in.

## Production deployment

Live application: https://canvas-plus-1dc9dd2e56ac.herokuapp.com/

## Connecting a Canvas account

Sign in to Canvas+ and choose **Connect Canvas** from the sidebar. Paste a personal
access token generated in your school's Canvas account. A successful connection
shows your active student course names and saves the credential encrypted. Returning
to the connection page shows only its last four characters. Opening the signed-in
home page checks the saved connection and offers reconnection if Canvas rejects it.

Configure these environment variables before connecting:

- `CANVAS_BASE_URL`: your school's HTTPS origin, such as `https://school.instructure.com`,
  without `/api/v1` or any other path.
- `CANVAS_TOKEN_ENCRYPTION_KEY`: a separate Fernet encryption key. Generate it once
  with the following command after installing dependencies, then save it in `.env`
  locally or the production platform's secret environment configuration:

```console
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Do not commit the generated key or a Canvas token. Keep the encryption key stable
across deployments and protect its backup: replacing or losing it requires students
to reconnect. The app can start without Canvas configuration, but connecting fails
closed until both settings are supplied. Apply the new accounts migration with
`python canvas_plus/manage.py migrate`; Heroku's existing release command also runs migrations.

The [Canvas connection study guide](docs/canvas-connection.md) explains the request
flow, files, tests, deployment configuration, and limitations. Assignment importing
is tracked separately in issue #39.

## Running tests

With the virtual environment active, run the test suite from the repository root:

```console
python -m pytest
```

This is the same command the CI pipeline runs. It uses `pytest-django` to find tests in `tests.py` and `test_*.py` files, including the Django app tests under `canvas_plus/`.

To run only the Django app tests with Django's own test runner, run this from inside `canvas_plus/`:

```console
python manage.py test
```

## AI disclaimer

AI tools were used during the completion of this course project. The use of AI was encouraged by the professor, and the course provided guidance on appropriate applications of AI through the course book. The course book's AI guidance can be found here: [SWE Book](https://www.swebook.org/index.html).

### During requirements engineering

#### Decomposing high-level user stories

Stephen Tovar used ChatGPT to assist with decomposing their assigned high-level user stories.

### During Sprint 0–3

#### Updating the README

Joshua Douglas used Codex to assist in updating the README to reflect project changes.

#### Running Django tests in CI

Jackson McGuire used Claude Code to apply the CI test configuration Joshua Douglas outlined in PR #64. Jackson reviewed each change and confirmed locally that pytest collects and runs Django tests before committing.

#### Writing the assignments page tests

Jackson McGuire used Claude Code to help write the integration tests for the assignments page. The tests were committed before the page existed and failed with a 404, then passed once the page was merged. Jackson ran every test himself and reviewed each line before committing.

#### Clean-clone check and README fixes

Jackson McGuire used Claude Code to plan a clean-clone check and draft the README fixes it found. Jackson ran every step himself in a fresh clone and confirmed the corrected venv command produces Python 3.14.

### During Sprint 1

Nathan Hinebaugh used ChatGPT to assist with building Behave testing, all suggested code and configuration changes were reviewed, tested locally, and adjusted before pushed into repository

#### AI code review in CI

Jackson McGuire designed and tested the AI Code Review job and its review guidelines, using Claude Code to help write the workflow and draft triage replies. Jackson chose the key design decisions (full-file context, a two-level severity scale, and rules against invented findings), approved each part, and ran all six acceptance checks on PR #76.

#### uv.lock check in CI

Jackson McGuire used Claude Code to help add the uv.lock check to Lint and Test. Jackson proved it works by pushing a stale lockfile on purpose (CI failed), then reverting it (CI passed).

#### Landing page

Jackson McGuire used Claude Code to help write the landing page and its pytest and Behave tests. Jackson refined the Gherkin acceptance criteria, ran every test (red before the page existed, green after), and flip-checked the failed-login test.

### During software development

#### Moving navigation to the left sidebar

Joshua Douglas used Codex to update the shared base template's navigation positioning and styling from a top bar to a left sidebar, preserving the existing menu items and mobile menu toggle.

#### Connecting Canvas accounts for issue 38

Joshua Douglas used Codex to review issue #38, estimate and break down the work,
explain Django forms and views, review his form and API-client code, and create the
initial acceptance tests and connection-page template. Joshua implemented the initial
form, route, view, Canvas settings, and API client while working through those explanations.
He then asked Codex to complete the issue. Codex implemented encrypted per-user token
storage, connection and reconnection handling, saved-token masking, pagination and
error safeguards, additional automated tests, and setup and study documentation.
Codex ran the automated checks and prepared the pull request and its description.
The automated Canvas tests use a local fake API or mocked responses; they do not
validate a real school account. Human review of the generated implementation remains
part of the pull request process.

#### Translating ADO pipeline knowledge to GitHub Actions

Stephen Tovar used ChatGPT to translate his existing knowledge of Azure DevOps pipelines into the equivalent terminology and YAML syntax used by GitHub Actions.

### During Sprint 1

#### Assistance with CD pipeline

Stephen Tovar used Copilot to assist with the steps needed to deploy the application directly to Heroku without linking in the GitHub repo.

#### Assistance with Logon and Account Registration

Stephen Tovar used Copilot to explain how `django.contrib.auth` provided django user account creation.
