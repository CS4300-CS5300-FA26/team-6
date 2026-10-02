
# Contributing

This guide covers managing Python dependencies and validating GitHub Actions workflows locally before opening a pull request.

## Python dependencies

This project uses [uv](https://docs.astral.sh/uv/) to manage dependencies in `pyproject.toml` and the `uv.lock` lockfile. Install uv by following its [installation guide](https://docs.astral.sh/uv/getting-started/installation/).

To create or update the project environment, including development dependencies, run:

```sh
uv sync --extra dev
```

Use `uv add <package>` to add a runtime dependency and `uv add --dev <package>` to add a development dependency. Use `uv remove <package>` to remove a runtime dependency, or `uv remove --dev <package>` to remove a development dependency. These commands update the project metadata and lockfile.

If you edit `pyproject.toml` manually, regenerate the lockfile and synchronize the environment:

```sh
uv lock
uv sync --extra dev
```

## Validate GitHub Actions locally

Use [actionlint](https://github.com/rhysd/actionlint) to check workflow syntax and configuration. After installing it, run this from the repository root:

```sh
actionlint
```

You can run the workflow locally with [act](https://nektosact.com/). For example, to simulate the pull request event configured for this repository, run:

```sh
act pull_request -W .github/workflows/ci-cd.yaml
```

`act` uses Docker to provide the workflow's execution environment. Install and start [Docker Desktop](https://docs.docker.com/desktop/setup/install/windows-install/) before running it. Local runs are useful for feedback but may differ from GitHub-hosted runners.