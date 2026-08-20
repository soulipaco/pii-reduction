# ADR-0008: src-layout package; provider, language, and Databricks dependencies are optional extras

**Status:** accepted · **Date:** 2026-08-17 · **Session:** 2

## Context

`AGENTS.md` requires provider dependencies to stay optional and every major
dependency justified. A user must be able to install the core package and run the
test suite without multi-gigabyte model downloads.

## Decision

`pyproject.toml` with `src/` layout:

- **core dependencies:** `pydantic>=2`, `PyYAML`, `pandas>=1.5,<3` (ADR-0006),
  `phonenumbers`. Nothing else. Core installs in seconds; deterministic provider,
  parsers, reducers, evaluation, and the whole unit-test suite work with core only.
- **extras:**
  - `presidio` → `presidio-analyzer`, `spacy` (models installed by documented
    command, never as dependencies — they are not on PyPI and pinning wheel URLs in
    metadata breaks resolvers),
  - `language` → `lingua-language-detector`,
  - `databricks` → `databricks-connect` (version documented against workspace
    runtime at Increment F),
  - `dev` → `pytest`, `ruff`, `mypy`, `Faker`.
- Import-time behavior: importing `pii_reduction.providers.presidio` without the
  extra raises an actionable `ConfigurationError` naming the extra; nothing
  auto-downloads at import (`docs/07` model-lifecycle rule).
- Versions are lower-bounded, not hard-pinned, except the pandas ceiling;
  provider/model versions used in a run are recorded in run metadata instead
  (reproducibility lives in metadata, not in over-pinning a library).

**Amended (session 3, Increment A5):** a `parquet` extra (`pyarrow`) was added.
`configs` already allow parquet sources and destinations, pandas cannot read or write
parquet unaided, and pulling pyarrow into core would contradict the "nothing else"
rule above. The adapters raise an actionable `SourceError`/`OutputError` naming the
extra when it is absent; CSV works without it. `pyarrow` is included in `dev` so the
default test run covers those adapters.

**Amended (session 11, ADR-0026):** a `service` extra (`fastapi`) **is added with
rung 4's first increment**, along with `fastapi` and `httpx` in `dev`. Recorded here
with the decision; the manifest changes in the commit that creates
`src/pii_reduction/service/`. Same reasoning
as the `parquet` amendment above and the same shape of decision: the default test tier
should exercise the surface, and it can only drive an ASGI app over a real transport
if `httpx` is installed. `httpx` was present in the development venv undeclared,
which meant CI would not have had it. The core dependency list is unchanged, and
`pii_reduction.service` stays importable with no extra installed — only
`service/api.py` names `fastapi`, and `service/__init__.py` must never import it.

**Amended (session 6, Increment D):** **no `demo` extra was added.** Retrieving the
public datasets was the open question ADR-0017 answers, and the answer needs nothing
new: the fetcher is `urllib` from the standard library, and reading MASSIVE's parquet
uses the `parquet` extra already listed above. So the extras list is unchanged, and
the documented command for building a public pack is `pip install -e ".[parquet]"`
(or `".[dev]"`, which includes it). Bitext ships a CSV and needs core only.

## Consequences

- CI's default job is fast and model-free; integration jobs opt into extras
  (ADR-0009).
- The ruff autofix hook activates once `.venv` exists with `dev` installed.
- Two-level install documentation is required in README quickstart (core demo vs
  full NER demo).
