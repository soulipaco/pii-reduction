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

The final implementation should document exact commands once `pyproject.toml` exists. The intended development workflow is:

```text
create virtual environment
install package + development dependencies
run unit tests
run lint/type checks
run small synthetic benchmark
```

Databricks access should not be necessary for most development.

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
