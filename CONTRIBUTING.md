
# Contributing

This guide covers managing Python dependencies and validating GitHub Actions workflows locally before opening a pull request.

## Using Django's debug setting

Use `settings.DEBUG` to check whether Django is running in debug mode:

```
from django.conf import settings

if settings.DEBUG:
    # Enable behavior intended only for local development.
    ...
```

`DEBUG` is configured in the project's Django settings. Keep debug-only behavior, such as verbose diagnostics, behind this check, and never enable `DEBUG` in production: it can expose sensitive information in error pages. For templates, use Django's `{% if debug %}` tag when the debug context processor is enabled.

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

## AI inference

Configure `OPENAI_API_KEY` in the repository-root `.env` for local development. The
OpenAI SDK reads it when an inference or file upload is requested; In production, set `OPENAI_API_KEY` in the deployment
environment or secret manager. Never commit a real key.

### Workflow

1. Create a response model using Pydantic's `BaseModel`. This is the JSON format that will be returned.
2. Create a content package with `build_content()`, providing the user prompt and any necessary files. Files in the content package are uploaded to OpenAI in this step, so they must be deleted afterwards.
3. Call `infer()` with a system prompt, the content package, and the response model.
4. Receive the validated response and access the fields you need.
5. Delete the uploaded files with `delete_uploaded_files()`, passing the same content package from step 2.

```python
from pydantic import BaseModel

from ai_inference import build_content, delete_uploaded_files, infer


class Answer(BaseModel):
    summary: str


content = build_content("Summarize the attached report.", files=["report.pdf"])
try:
    answer = infer("Write a concise summary.", content, Answer)
    print(answer.summary)
finally:
    delete_uploaded_files(content)
```

`build_content()` requires a non-empty prompt and optional files. Each file can be a local
path/path-like value, a `(filename, bytes_or_binary_stream)` pair, or a readable
binary stream with a usable `.name`. Files are uploaded through the OpenAI Files API
with `purpose="user_data"`; the returned user message contains `input_text` and/or
`input_file` items and can be passed directly to `infer()`.

For example, callers can fetch bytes from an API or retrieve a PostgreSQL `bytea`
value themselves, then pass the bytes and a filename to the builder:

```python
# API download; the caller owns the API request and response.
report_bytes = download_response.content

# Or a bytes value retrieved from existing PostgreSQL-backed storage.
report_bytes = bytes(database_row["file_data"])

content = build_content(
    "Extract the key findings.",
    files=[("report.pdf", report_bytes)],
)
answer = infer("Return the key findings.", content, Answer)
```

Named binary streams work the same way, including streams populated by a caller's
API or storage code:

```python
from io import BytesIO

file_stream = BytesIO(report_bytes)
content = build_content("Extract the key findings.", files=[("report.pdf", file_stream)])
```

The builder uploads a caller-owned stream from its current position and does not
close it; callers are responsible for its position and lifecycle. Files must be
supported by OpenAI and `gpt-6-luna`. Response models must use the JSON Schema subset
supported by OpenAI Structured Outputs in strict mode. The interface derives the
strict schema from the Pydantic model, always uses `gpt-6-luna`, and returns a
validated instance of that model.

| Exception | When it is raised |
| --- | --- |
| `AIConfigurationError` | `OPENAI_API_KEY` is missing when a provider client is needed. |
| `AIAuthenticationError` | The provider rejects the configured credentials. |
| `AIProviderError` | A provider, network, local file-read, or upload request fails, including an unsupported request schema. |
| `AIRefusalError` | The provider refuses the inference request. |
| `AIIncompleteResponseError` | The provider does not complete the response. |
| `AIInvalidOutputError` | The completed response cannot be parsed or validated as the requested model. |

Empty content and whitespace-only prompts are rejected locally with `ValueError`;
invalid response models or file input types raise `TypeError` or `ValueError`.
Provider-facing exception messages do not include the API key. A successful file
upload does not mean inference succeeded; handle the documented exceptions from
both `build_content()` and `infer()`.

### Example Python Shell Inference

This is a live smoke test: it uploads a temporary file, sends a request to OpenAI,
and deletes the uploaded file afterward. It requires a valid `OPENAI_API_KEY` in
`.env` and may incur API usage costs. From the repository root, activate the
project's virtual environment and start a Python interactive shell before running
the code. The example assumes the repository is located at
`/coursework/Canvas_Plus`, as specified by the `.env` path in the code; if your
checkout is elsewhere, that path must match its location.

```
from openai import OpenAI
from pydantic import BaseModel
from canvas_plus.ai_inference import build_content, infer, delete_uploaded_files
from canvas_plus.ai_inference.inference import MODEL
import environ

environ.Env.read_env("/coursework/Canvas_Plus/.env")

class SmokeResult(BaseModel):
    found_phrase: bool
    summary: str

content = build_content(
    prompt="Quote the exact contents of the attached file.",
    files=[("smoke-test.txt", b"COPILOT-SMOKE-731")],
)
file_id = content[0]["content"][-1]["file_id"]

try:
    result = infer(
        "Check the attached file for the exact phrase COPILOT-SMOKE-731.",
        content,
        SmokeResult,
    )
    print(result)
finally:
    # DON'T FORGET TO DELETE UPLOADED FILES
    delete_uploaded_files(content)
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

## Main branch protection

The `main` branch is protected by an active GitHub ruleset. Changes must go through a pull request; you cannot push changes directly to `main` or force-push to rewrite its history. The branch also cannot be deleted.

Before a pull request can be merged:

- At least one reviewer must approve it. If new commits are pushed after approval, the old approval is dismissed and the pull request needs another approval.
- The person who pushed the latest changes must get approval from another reviewer.
- Review conversations must be resolved.
- The `Lint and Test` status check must pass, and the branch must include the latest changes from `main` before it can merge.
- Commits must have verified signatures.
- The pull request must be merged using a merge commit. Other merge methods, such as squash or rebase, are not allowed.

No users or teams are listed as exempt from these rules. Code-owner approval is not specifically required.