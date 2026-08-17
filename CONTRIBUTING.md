# Contributing

Thank you for contributing to the Databricks PII Reduction Accelerator.

The project deals with privacy-sensitive problem domains, so contributions are expected to meet both normal software-quality standards and stricter data-handling standards.

## Before contributing

Read:

- `README.md`
- `AGENTS.md`
- `docs/00_PROJECT_CHARTER.md`
- `docs/01_ARCHITECTURE.md`
- `docs/09_SECURITY_PRIVACY_GOVERNANCE.md`
- `docs/10_TESTING_QA.md`

## Contribution principles

### Keep examples public-safe

Do not submit real customer, employee, patient, applicant, account-holder, or private communication data.

Synthetic examples are preferred.

### Preserve architecture boundaries

A source adapter should not become a PII recognizer. A recognizer should not decide how Delta tables are written. A notebook should not become the only place where reusable logic exists.

### Add evidence, not only features

A new provider is more useful when accompanied by benchmark results and documented limitations.

### Prefer configuration over forks

If behavior varies by dataset, language, or entity scope, first consider whether it belongs in configuration.

## Development setup

```bash
python -m venv .venv && . .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
```

That is the whole install for the default tier: no NLP model, no provider extra.

```bash
ruff format --check . && ruff check .
mypy src tests
pytest -q                                       # default tier: fast, model-free
pii-reduction benchmark --gates configs/benchmark_gates.yaml
```

The provider tier needs more, and is opt-in (`docs/15_PROVIDERS.md`):

```bash
pip install -e ".[dev,presidio,language]"
python -m spacy download en_core_web_md
python -m spacy download de_core_news_md
python -m spacy download xx_ent_wiki_sm
pytest -q -m integration
pii-reduction benchmark --chain deterministic_presidio --gates configs/benchmark_gates.yaml
```

Say which tier you ran when reporting results: the default `pytest` deliberately
excludes `integration`, `slow` and `databricks` (ADR-0009).

Databricks access should not be necessary for most development.

## What CI runs

Two workflows, matching the three tiers of ADR-0009:

| Workflow | Trigger | What it runs |
|---|---|---|
| `.github/workflows/ci.yml` | every push and PR, Linux **and** Windows | ruff, mypy, the default test tier, the deterministic benchmark gates, and a check that the committed corpus still regenerates byte-for-byte from its seed |
| `.github/workflows/integration.yml` | nightly, `workflow_dispatch`, or a PR labelled `integration` | the `presidio` + `language` extras with pinned md spaCy models, `pytest -m "integration or slow"`, and the benchmark gates for both chains |

`databricks`-marked tests never run in CI — they need workspace credentials
(ADR-0006). Run them manually.

The push tier installs core + `dev` only and asserts that no provider extra is
importable, so anything that quietly makes spaCy a core requirement fails there.

## Branch/change scope

Keep pull requests focused when practical.

Good examples:

- add transcript parser + tests,
- add Presidio provider + benchmark fixture,
- add Greek language routing,
- add Spark/Delta output adapter,
- add benchmark metric.

Avoid mixing broad unrelated refactors with a new feature unless the refactor is required for the feature.

## Tests

Contributions should add tests appropriate to the change.

At minimum consider:

- unit behavior,
- negative behavior,
- parser round trip,
- provider contract,
- privacy-safe logging,
- benchmark regression,
- Spark parity where relevant.

Do not weaken existing benchmark gates merely to make a provider pass without explaining why the metric definition or gate was wrong.

Those gates are in one file, `configs/benchmark_gates.yaml`, so changing one is a
visible act in a diff. Every value there was measured on a run someone actually did,
and the file records the corpus, strategy, commit and model versions it was measured
against. Raising a floor after a real improvement is the normal path — with the new
number taken from your own run, not estimated.

## New provider checklist

A provider contribution should include:

- provider adapter,
- supported entity mapping,
- language coverage,
- model/package dependency declaration,
- confidence/threshold behavior,
- batching behavior,
- license information,
- tests,
- benchmark results or a documented reason they are not yet available,
- known limitations.

## New dataset checklist

Before adding a dataset integration, document:

- dataset name,
- source/publisher,
- license,
- version,
- whether redistribution is permitted,
- whether real PII may be present,
- language coverage,
- domain/document type,
- download/preparation mechanism,
- transformations performed,
- generated ground-truth strategy if synthetic PII is injected.

If licensing is unclear, do not commit the raw dataset.

## New parser checklist

A parser should include:

- parser contract implementation,
- round-trip tests,
- malformed-input behavior,
- reconstruction tests after text mutation,
- documentation of immutable versus processable regions.

## Documentation

Update documentation in the same contribution when changing:

- public APIs,
- configuration contracts,
- architecture,
- supported languages,
- entity taxonomy,
- provider capabilities,
- output tables,
- benchmark definitions.

## Pull request description

A good PR description answers:

1. What problem does this change solve?
2. Which architecture component does it affect?
3. What behavior changed?
4. What tests were run?
5. Did benchmark metrics change?
6. Are there privacy/security implications?
7. What limitations remain?

## Security issues

Do not open a public issue containing sensitive data or working credentials. Follow `SECURITY.md` for security-sensitive reports.
