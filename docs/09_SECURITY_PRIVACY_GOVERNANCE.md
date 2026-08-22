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
- entity counts,
- provider,
- language,
- runtime,
- parser status,
- error category.

**Audit-table fields only, never a log line and never a response:** text length,
entity type, span offsets and lengths, per-entity confidence. Earlier revisions of
this document listed them above; they are disclosive in a way the rest of the list is
not (offsets restore the span lengths redaction removed — see *Data retention*), and
the shipped allowlist `ALLOWED_FIELDS` in
`src/pii_reduction/observability/logging.py` has never contained them. They belong to
the audit table, which is governed at least as strictly as reduced output, not to
telemetry.

### Unsafe by default

- full original text,
- full reduced text,
- detected raw entity values,
- snippets surrounding entity spans,
- authentication headers.

## Display surfaces, API responses, and request payloads

The logging policy above governs one channel. It is not the only one that leaves the
process, and — once a service exists — not the only one that enters it. A rendered
page, an HTTP response body, a validation error, a notebook cell output, a redirect,
a downloaded file and a `print` are the same disclosure with different transport. The
rule that applies to them is the rule above, restated so nobody has to reason by
analogy:

**A surface may show metadata about text. It may not show, stream, redirect to, or
vend a URL for the text.**

"Text" here means all three of source text, reduced text, and detected entity values
— Class B *and* Class C. Reduced text is not exempt: reduction is **measured, not
guaranteed**. The published leakage rate is 0.067 for the hybrid chain
(`docs/08_EVALUATION_BENCHMARKING.md`) and 0.433 for the deterministic one
(`docs/15_PROVIDERS.md`) on the committed corpus, and on the public packs 0.000 for
the hybrid chain on two of them and 0.065 on the third — and, as
`docs/18_RUNBOOK_DATABRICKS.md` states plainly, the rate on somebody else's data is
unknown until they sample and look. A surface that displays reduced text displays
whatever leaked.

**Why reduced text may sit in a table and not in a response.** `docs/09`'s grant
model puts the reduced-only artifact in a schema granted to broader analytics
consumers (ADR-0024), which looks like a contradiction and is not: that artifact is
disclosed *under Unity Catalog grants, to named principals, with access audited*. A
response body is disclosed under whatever authentication the surface happens to have.
The data class did not change; the governance did.

### Safe on a display surface

`ALLOWED_FIELDS` in `src/pii_reduction/observability/logging.py` is the governing
list, and these are its keys. It is not a subset of the *Safe to log* prose above and
the prose is not a subset of it — each carries names the other lacks. Where they
differ **the code governs**, which is why the prose above was corrected rather than
left for a reader to reconcile:

- dataset, column, output column, row id, run id, config hash,
- provider(s), parser, reducer, language,
- status, error **category**, duration,
- rows, rows read/written, fields processed/failed, entities detected/reduced,
  fallbacks,
- destination — the one key under which a configuration-derived table or file name
  may appear.
- **source file *name*, and only for a `select_file` template** (ADR-0036). This is
  the one entry on this list that is **data-derived rather than configuration-derived**
  — the name of a file somebody dropped in a directory — so it is called out rather
  than folded into the bullet above.

  Three things bound it. It is **opt-in per template**, so an operator decides whether
  their directory is offered at all. It is a **name, never a path**: the joined path is
  the operator's directory plus the caller's name, and `POST /configs` returns the
  directory as a placeholder for the same reason `saved_path` is relativized. And the
  listing is **one level, filtered to the source type, and never opens a file**.

  **What it does not bound is the name itself.** A file called after a person puts that
  person's name in a listing every principal the platform admits can read, and no code
  can tell. The operator who sets `select_file` owns that: an inbox is a shared
  surface, and `docs/19` says so where they will meet it.

### Unsafe by default on a display surface

- source text, in whole or in fragment,
- reduced text, in whole or in fragment,
- detected entity values,
- snippets surrounding entity spans,
- **span offsets and lengths**, and per-entity confidence — see *Data retention*
  below: audit metadata is governed at least as strictly as reduced output, because
  exact offsets restore the span lengths redaction removed. A surface that renders
  *where* something was found has rendered part of the thing,
- authentication headers, tokens, and workspace URLs,
- an exception message that carries a value it was raised about.

**Class A is the carve-out.** Synthetic or explicitly public-safe text may be
shown where a document says so — the *Public demo screenshots* section below and
`docs/11_ROADMAP.md`'s Phase 9 demo surface both depend on it, and `CLAUDE.md`'s
privacy checkpoint states the same exception for debugging. The carve-out is per
dataset and per document, never per developer's judgement in the moment, and it never
extends to Class B or Class C.

**It does not create a service endpoint.** ADR-0026's no-text rule is absolute
regardless of the data class behind it, because a dataset's class is a configuration
value while an endpoint is code: an endpoint blessed for a synthetic dataset is still
an endpoint, and the next config change repoints it. Nothing declares a dataset's
class today — `DatasetIdentity` carries `name`, `row_id` and `source_version` and
nothing else — so the carve-out currently attaches to a *committed in-repo synthetic
corpus or a documented public pack*, by name. Any future text-rendering surface must
read a machine-readable `dataset.data_class` and refuse what it does not recognise,
rather than trusting a file name.

One other exception exists in this repository and it is narrower still:
`observability.log_raw_text`, which the config loader refuses unless
`project.environment` is `local`. It is a *logging* switch for local debugging, it is
read by nothing today, and it never extends to a display surface or a response.

### Request payloads: the inbound half

A service boundary has two directions and the paragraphs above govern one. Text
arriving over HTTP is Class B the moment it exists in the process, and it arrives
into channels no reduction has touched:

- **text in a URL path or query string** — reaches every access log, proxy and
  browser history on the path. Forbidden outright; there is no safe amount.
- **an uploaded file** — becomes a copy of the source with weaker governance than
  the source (`docs/09`, *Core principle*) unless it is written only to the
  configured destination boundary, never logged, and deleted on a stated schedule.
- **request bodies in an access-logging middleware or a captured traceback** — the
  same leak with nobody's name on it. A service that accepts text must disable body
  logging explicitly rather than rely on the default.
- **framework-generated responses** — a validation error that echoes the offending
  input, and a debug-mode traceback, are *defaults*, not exceptions the service
  raises, so "report by category" does not reach them. A service must install its own
  validation-error handler and must never run with debug enabled.

**As of ADR-0026 the service layer has no endpoint that accepts text**, which is what
makes the outbound argument hold: text that never enters cannot leave. Adding one is
a governed change under this section, not a feature.

### Choosing where data is read from and written to

A surface that triggers work runs it with the surface's credentials, not the
caller's. If the caller also names the source table and the destination, the surface
is a confused deputy: a request can read a restricted schema and land the output —
which by default still carries the source columns (`AGENTS.md` rule 4) — somewhere
the caller can read. That is threat T4 below, executed through a surface whose
response bodies are impeccably clean.

Therefore: **a service resolves the source and destination from server-side
configuration or a server-side allowlist, never from free-form request strings**, and
any file it writes on a caller's behalf gets a server-derived name and location. A
caller may choose *which configured dataset* to run. It may not choose *what
`catalog.schema.table` that means*.

The same reasoning bounds a **config builder**, and there the bound is not only about
locations. A dataset configuration carries switches whose whole purpose is to move a
privacy boundary: `processing.failure_mode`, whose
`preserve_original_and_record_error` value is ADR-0023's explicit raw-text
pass-through and would land source text in a column an operator governs as reduced;
`processing.preserve_original`, whose `false` value is the controlled replacement
workflow `AGENTS.md` rule 4 requires a configuration to define explicitly; and
`destination.projection`, which is the ADR-0024 grant boundary itself. **A builder
accepts dataset identity, column selection and entity selection. Everything else —
source, destination, failure mode, preservation, projection — comes from a
server-side template**, which the builder fills rather than deserializing a
configuration from a request body.

### Side-by-side original/reduced views

A side-by-side "before and after" view is the most requested feature such a service
has, and over real data it is a **Class B display surface**: it discloses original
text to whoever holds the URL, outside every control the pipeline applies to the data
it writes. Over Class A data it is a demo, and `docs/11_ROADMAP.md` Phase 9 already
sanctions one. Over anything else, building it is a governed change, not a UI task.
For a view over Class B or Class C data, before one exists:

1. the surface must state which data class it is showing, per view,
2. access to it must be governed like the raw schema, not like the reduced one
   (see *Unity Catalog governance model* below — the full frame is already governed
   that way and this is the same boundary),
3. it must read **under the end user's identity**, never under the service's. A
   service principal reading and rendering to a browser launders the grants that
   condition 2 relies on, which is the one real advantage a Databricks App has
   (on-behalf-of-user authentication) and the reason condition 2 is not
   self-enforcing.

   **Measured on the deployed App (2026-08-22): hosting does not satisfy this.** The
   App carries its own service principal, and its default on-behalf-of-user scopes are
   `iam.access-control:read` and `iam.current-user:read` — identity only, **no data
   scope**. So an App authenticates the end user and *authorizes as itself*. Meeting
   this condition needs the explicit on-behalf-of-user opt-in **and** a run path that
   uses the caller's token rather than the service principal's. Neither exists today;
   `docs/19` carries the evidence;
4. it must be gated behind an explicit, recorded operator authorization for the
   dataset, granted per dataset rather than once per surface,
5. it must **record each disclosure as metadata** — viewer identity, dataset, row id,
   timestamp — and never its content. The schema it is governed like is audited by
   Unity Catalog; a view with no record of who saw which row is *less* governed than
   the table it renders,
6. nothing it renders may be logged, cached or persisted — by the surface, by the
   browser, or by anything between them (`Cache-Control: no-store`) — and it must be
   bounded in volume: a paged view over a whole table is a bulk export wearing a UI,
   and
7. the decision must be recorded as an ADR, because it changes what this project
   discloses rather than what it computes.

**As of ADR-0026 no such view exists.** The service layer's v1 has no endpoint that
returns text of any kind, which is how it satisfies this section rather than by
filtering. A filter is a thing that can be wrong; an absent capability cannot be.

### Errors crossing a service boundary

An error returned to a caller is a display surface. `docs/09`'s *Error handling*
section applies to it unchanged, plus one rule specific to services: an unexpected
exception is reported by **category**, never by relaying a message raised below the
layer that is answering. The Databricks front door is the worked example — because
the exceptions crossing into it from Databricks Connect carry the workspace URL and
profile, it reduces them to an exception class name (`databricks/cli.py`).

The core CLI deliberately does the opposite, letting an unexpected exception keep its
traceback, which is right for a local run whose output goes to the person who started
it. **That leniency does not transfer to a service run locally**: the output goes to a
client either way.

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

This arrangement is realisable with shipped code as of ADR-0024: the "reduced
schema" artifact is the reduced-only projection — locally via
`destination.projection: reduced_only`, on Databricks via `run_driver`'s
`reduced_only_prefix` pointing at a separately-granted `catalog.schema`. The
default full-frame output retains the source columns (AGENTS.md rule 4) and must
be governed like the raw schema, not like this one.

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
- audit metadata governed **at least as strictly as reduced output** — it excludes
  raw values, but its exact pre-reduction offsets restore the span *lengths* that
  redaction deliberately removed, and length + position + entity type beside
  untouched prose is a narrowing signal on short fields. An earlier revision of
  this list treated audit metadata as lower-sensitivity ("retained longer because
  it excludes raw values"); the external-review reconciliation (docs/17 §3)
  corrected that framing,
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
