# Canvas Plus

Canvas Plus is the CS 4300/5300 Fall 2026 Team 6 group project. It is a Django application that currently provides the initial project skeleton and an `assignments` app.

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

### During software development

#### Translating ADO pipeline knowledge to GitHub Actions

Stephen Tovar used ChatGPT to translate his existing knowledge of Azure DevOps pipelines into the equivalent terminology and YAML syntax used by GitHub Actions.
