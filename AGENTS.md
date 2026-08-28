# AGENTS.md

## Project

CineFlow is a Python media automation application.

Main areas:

```text
cineflow/core/          Core runtime, configuration, database, workers, flows
cineflow/integrations/  External integrations such as TMDb, Jellyfin, Plex, Jackett, Transmission
cineflow/internal/      Internal library/tools
cineflow/utils/         HTTP, filesystem, image and utility helpers
tests/                  Pytest test suite
docker/                 Docker runtime and example configuration
docs/                   Project documentation
```

Python 3.13+ is supported.

## Development Environment

Use `uv` for Python environment and dependency management.

Do not introduce alternative environment or dependency tooling.

Standard setup:

```powershell
uv sync --locked --group dev
```

Run the application with:

```powershell
uv run cineflow
```

Do not manually manage `.venv` or install project dependencies with `pip`.

## Tests

Run tests with:

```powershell
uv run pytest --basetemp .pytest-codex -q
```

Run coverage validation with:

```powershell
uv run pytest --basetemp .pytest-codex --cov=cineflow --cov-report=term-missing
```

The project has a minimum coverage gate of 75%.

New functionality and bug fixes should normally include regression tests.

Tests must:

* be deterministic;
* not require real external services;
* mock network APIs;
* use temporary directories for filesystem tests;
* not sleep unnecessarily.

## Build

Build the Python package with:

```powershell
uv build
```

The Docker image consumes the generated wheel. Do not add `uv` to the runtime Docker image unless there is a concrete need.

## Code Changes

Prefer small, focused changes.

Do not perform unrelated refactoring while fixing a bug.

Preserve existing public configuration formats and flow YAML behavior unless the task explicitly requires changing them.

Do not introduce new dependencies when the standard library or an existing dependency is sufficient.

Avoid architectural abstractions unless they clearly reduce complexity.

## Error Handling

CineFlow automates operations across media systems, so failure handling should be conservative.

Important principles:

* API failure is not the same as a successful empty result.
* Destructive actions must fail closed when upstream state is incomplete or unavailable.
* Background worker exceptions must not silently terminate automation threads.
* Filesystem operations must remain inside the configured export/library root.

## Integrations

External integrations must not make real network requests during unit tests.

Use mocked `RequestHandler` responses and cover at least:

* successful responses;
* empty successful responses;
* transport failures;
* HTTP/API failures;
* important protocol-specific edge cases.

## Flow Engine

Flows are YAML-defined and execute ordered steps.

Important behavior:

* `get() -> None` represents retrieval failure and stops the current flow.
* `get() -> []` represents a successful empty result and may continue.
* flow `delay` values are in minutes.
* `parallel` and `sequential` are the supported execution modes.

Preserve these semantics unless explicitly changing the flow model.

## Validation Before Completion

For normal Python changes run:

```powershell
uv sync
uv run pytest --basetemp .pytest-codex -q
uv run pytest --basetemp .pytest-codex --cov=cineflow --cov-report=term-missing
uv build
git diff --check
```

Run focused `flake8` on changed Python files.

Repository-wide pre-existing lint debt is not a reason to expand the scope of an unrelated task.

## Git

Development work is based on the `develop` branch unless the task explicitly states otherwise.

Do not reset, overwrite, or discard unrelated working-tree changes.

Do not commit or push unless explicitly requested.

When explicitly asked to push a commit, also monitor the GitHub Actions runs
triggered by that push through to completion. If a run fails, inspect the
failed job and its logs before deciding whether to act.

The requested push authorizes a minimal follow-up commit and push only when
the failure has a clearly safe fix that preserves all application features and
behavior. Safe fixes are limited to CI, build, test, packaging, or tooling
corrections; they must not change public configuration formats, flow behavior,
runtime features, release behavior, secrets, permissions, or deployment
configuration. Validate the repair with the relevant local checks before
pushing it and continue monitoring the resulting workflow run.

If the cause is uncertain, the repair could affect application behavior, the
failure concerns infrastructure, credentials, secrets, permissions, or a
deployment, or the repair fails again, do not push a follow-up change. Report
the diagnosis and ask for direction instead.
