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
│   │   ├── models.py
│   │   ├── tests.py
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

Create a virtual environment:

```console
python -m venv .venv
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

Install the project dependencies:

```console
python -m pip install -e ".[dev]"
```

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

Open <http://127.0.0.1:8000/> to see the Django "The install worked successfully!" starter page, which confirms the project is running. The Django administration site is at <http://127.0.0.1:8000/admin/>. Create an administrator account with `python manage.py createsuperuser` to sign in.

## Running tests

With the virtual environment active, run the Django test suite from the `canvas_plus` directory:

```console
python manage.py test
```

The suite currently contains no tests, so the command reports `Found 0 test(s)` and `NO TESTS RAN`.

## AI disclaimer

AI tools were used during the completion of this course project. The use of AI was encouraged by the professor, and the course provided guidance on appropriate applications of AI through the course book. The course book's AI guidance can be found here: [SWE Book](https://www.swebook.org/index.html).

### During requirements engineering

#### Decomposing high-level user stories

Stephen Tovar used ChatGPT to assist with decomposing their assigned high-level user stories.

### During Sprint 0–3

#### Updating the README

Joshua Douglas used Codex to assist in updating the README to reflect project changes.

### During software development

#### Translating ADO pipeline knowledge to GitHub Actions

Stephen Tovar used ChatGPT to translate his existing knowledge of Azure DevOps pipelines into the equivalent terminology and YAML syntax used by GitHub Actions.
