# Security, Privacy, and Governance

## Purpose

A PII reduction repository can accidentally create new privacy risks through logs, audit tables, fixtures, screenshots, benchmark exports, or debugging artifacts. Security is therefore part of the architecture rather than an operational afterthought.

## Core principle

> The system should not create a less-governed copy of the sensitive information it is trying to remove.

## Data classifications

The accelerator should reason about at least three data classes.

### Class A: public-safe / synthetic

May be committed when licensing permits.

Examples:

- synthetic test fixtures,
- generated fictional names,
- reserved-domain email addresses.

### Class B: source-sensitive

Real operational text that may contain PII.

Must not appear in:

- logs,
- Git,
- screenshots,
- benchmark artifacts intended for public release.

### Class C: reduced data

Text after PII transformation. Reduced does not automatically mean non-sensitive; residual sensitive data and business-confidential content may remain.

## Repository hygiene

`.gitignore` should cover likely local artifacts:

```text
.env
.env.*
!.env.example
*.xlsx
*.xls
*.csv
*.parquet
/data/raw/
/data/private/
/.databricks/
/model_cache/
```

Do not rely only on `.gitignore`. Agents and developers must actively avoid copying private data into documentation.

## Secrets

Potential secrets:

- Databricks tokens,
- cloud credentials,
- Hugging Face tokens for gated models,
- pseudonymization keys,
- model-serving credentials.

Rules:

- environment variables locally,
- Databricks Secrets or workload identity patterns in managed environments,
- never include secret values in configuration snapshots,
- never log environment dictionaries wholesale.

## Logging policy

### Safe to log

- row ID,
- dataset name,
- column name,
- text length,
- entity counts,
- entity type,
- offsets,
- confidence,
- provider,
- language,
- runtime,
- parser status,
- error category.

### Unsafe by default

- full original text,
- full reduced text,
- detected raw entity values,
- snippets surrounding entity spans,
- authentication headers.

## Audit tables

Default detection audit should record spans but not entity values.

Example:

```text
row_id=123
column=transcript
entity_type=PHONE
start=112
end=129
provider=deterministic
score=1.0
```

If a secure debugging workflow needs source text, store it separately with explicit access control and short retention.

## Pseudonymization keys

Deterministic pseudonymization must use a secret key when linkage resistance matters.

Never use a plain unkeyed hash of low-entropy values such as names or phone numbers as a privacy mechanism. Such values may be dictionary attacked.

## Reversible mapping

Reversible tokenization creates a high-value sensitive mapping table. It should remain outside the first public accelerator release unless implemented with strong controls.

If added later:

- separate catalog/schema,
- narrow access,
- encryption/key management,
- retention policy,
- audited access,
- clear deletion workflow.

## Data minimization

Process only configured columns and configured entity types.

Do not scan every column by default merely because the table is available.

## Original columns

The portfolio project keeps original fields for demonstration and measurement. In a real production environment, access to original text should be more restrictive than access to reduced outputs.

Document this difference explicitly.

## Unity Catalog governance model

A conceptual production arrangement:

```text
raw schema       -> restricted data engineering / privacy group
reduced schema   -> broader analytics consumers
audit schema     -> engineering / privacy operations
benchmark schema -> engineering / ML teams
```

The repository must not hard-code group names.

## Provider data boundaries

Every provider documentation entry should state where text is processed:

- local process,
- Databricks worker,
- internal model-serving endpoint,
- external API.

External API providers require explicit consideration of data residency, retention, contractual controls, and authorization. The open-source accelerator should default to providers that can run inside the user's controlled environment.

## Model artifacts

Check licenses before redistributing or automatically downloading models.

Do not bundle model weights in the repository unless license and size make that appropriate.

## Public demo screenshots

Only generate screenshots from synthetic/public-safe datasets.

Do not assume redacted text is safe enough to publish unless source provenance is known.

## Error handling

Exceptions can leak text.

Avoid patterns such as:

```python
raise ValueError(f"Failed to process text: {text}")
```

Prefer:

```python
raise ProcessingError(
    dataset=dataset,
    row_id=row_id,
    column=column,
    reason="provider_timeout",
)
```

## Quarantine tables

If failed records are quarantined, decide whether quarantine contains original text.

Production default should treat quarantine as sensitive and govern it at least as strictly as raw data.

## Data retention

The repository should expose retention considerations but not claim a universal policy.

Potential lifecycle:

- raw source retained according to source policy,
- transient normalized segments deleted after successful output,
- audit metadata retained longer because it excludes raw values,
- secure debug samples short-lived.

## Privacy testing

Tests should include:

- logs contain no fixture PII values,
- audit serialization excludes matched text,
- configuration snapshots exclude secrets,
- exceptions do not contain full text,
- benchmark export can be produced from synthetic data only.

## Threat scenarios

### T1: log leakage

A provider exception prints the full customer transcript.

Mitigation: sanitized exception wrappers and tests.

### T2: benchmark leakage

A developer copies production examples into a fixture.

Mitigation: synthetic-only fixture policy, code review, automated secret/data checks where practical.

### T3: reversible hashing

An unkeyed hash is used to pseudonymize phone numbers.

Mitigation: keyed deterministic tokenization.

### T4: over-broad access

Analysts gain access to the raw table because the reduced table lives in the same permission boundary.

Mitigation: separate governed schemas/catalogs and documented access model.

### T5: external provider exposure

Sensitive text is sent to an external API without approval.

Mitigation: provider boundary metadata, disabled-by-default external providers.

## Compliance statement

The README should include a concise disclaimer:

> This project provides technical components for PII detection and reduction. It does not by itself establish compliance with GDPR, HIPAA, PCI DSS, or other regulatory frameworks. Organizations must validate entity scope, residual risk, lawful processing, retention, access control, and model/provider suitability for their own use case.
