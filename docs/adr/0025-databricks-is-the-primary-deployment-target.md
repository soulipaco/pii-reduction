# ADR-0025: Azure Databricks is the primary deployment target, not one surface among several

**Status:** accepted · **Date:** 2026-08-20 · **Session:** 10

## Context

Every positioning document in this repository was written to keep Databricks
*optional*. `docs/00_PROJECT_CHARTER.md` lists portability as a required quality —
"Databricks should add scale, governance, orchestration, and visualization rather
than becoming a hard dependency"; `docs/11_ROADMAP.md` sequences Databricks
execution as Phase 6 of eleven, ahead of Phase 7's provider expansion; `README.md`
presented local and Databricks execution as co-equal surfaces. That framing was
correct for a portfolio artifact whose reviewer might have no workspace.

It is no longer the whole truth about what this repository is for. The owner
stated the real target on 2026-08-19 (recorded in `docs/14_IMPLEMENTATION_PLAN.md`
§8's platform queue): an **internal Azure Databricks platform** for AI analysis of
ServiceNow / case-description records — PII reduction now, PHI later if it proves
feasible — with a service layer (a Databricks App or API: upload a file or pick a
table, choose columns, run with pre-configured parameters) built *over* this
engine. Azure Databricks is a requirement of the environment, not a deployment
option someone selected.

Leaving the documents as they were would have two costs. A contributor reading the
charter would rank a new provider above a runbook, because the roadmap says
providers come next. And a reader would reasonably conclude that the Databricks
path is a demonstration rather than the path the work is actually for — which is
exactly the "docs claim what the code does not" failure mode
`docs/17_EXTERNAL_REVIEW_RECONCILIATION.md` D4 was written to stop.

## Decision

**Azure Databricks is the primary deployment target of this project.** Local
execution is the development, test and evaluation surface; it is not the
deployment surface, and no document should imply otherwise.

Two things this deliberately does **not** change, because conflating them is how a
positioning change becomes an architecture regression:

1. **The core library still runs without Databricks, and must.** `pytest -q`
   stays model-free and Spark-free (ADR-0009); nothing on the runtime path may
   import `pyspark` (`docs/01_ARCHITECTURE.md`, *Package dependency direction* —
   three separate guards enforce it); the Spark adapters keep living under
   `databricks/`. Local runnability is not a portability nicety we are now
   downgrading — it is the property that makes the parity claim *checkable*.
   "One implementation, two runtimes" (`AGENTS.md` rule 10) requires two runtimes
   to exist.
2. **Workspace values stay out of the repository.** Catalog, schema, table,
   profile and host come from configuration or environment, always
   (`AGENTS.md` Databricks rules). A primary target is not a licence to hard-code
   one workspace.

**The platform ladder**, recorded so the layering is a decision rather than an
accident:

```text
rung 4   service layer (Databricks App / API: pick a table, choose columns, run)
rung 3   scheduled job / Asset Bundle deployment
rung 2   runbook-driven manual run on the workspace   <- the near-term target
rung 1   the engine: this library, config-driven, runtime-agnostic
```

Each rung may only depend on the ones below it. The engine never learns that a
service layer exists; the service layer owns no reduction logic. Both external
reviews endorsed this split independently, and it is the same boundary
`AGENTS.md` rule 3 draws against notebooks — a UI is a notebook with better
styling as far as business logic is concerned.

**The PHI horizon is recorded, not promised.** PHI is a plausible later scope for
the same platform. It is not in scope today and nothing in this repository detects
it: it would need its own entity taxonomy, its own provider evidence, its own
benchmark corpora, and a legal/model-risk review this project explicitly does not
claim to substitute for (`docs/00_PROJECT_CHARTER.md`, *Non-goals*). Naming the
horizon here is what stops it being read into the current entity list.

## Consequences

- **Prioritization changes.** Databricks-facing capability (config-nameable UC
  IO, a runbook, a deployable job, batching) outranks a new provider or a new
  parser until the platform path is usable end to end. `docs/11_ROADMAP.md`'s
  Phase 7–11 ordering is now subordinate to the platform queue in plan §8, and
  the roadmap says so at the top rather than reading as the live sequence.
- The charter's *Portability* quality is amended in place: local-runnable stays a
  hard engineering constraint, "Databricks is not a hard dependency for the
  product" does not.
- **Phase 6's unmet exit criterion matters more, not less.** The distributed path
  is still infra-blocked (ISOLATION_STARTUP_FAILURE, ADR-0006's amendment). A
  primary target with one unexecuted distributed benchmark is the honest state and
  is recorded as such; it does not become green because the target got promoted.
- Documentation that positions the project — README, charter, roadmap — must
  agree with this ADR. They were amended in the same commit that introduced it.
- The near-term exit criterion the owner set: **run real workspace data using only
  a runbook** (rung 2). That is what `docs/18_RUNBOOK_DATABRICKS.md` is for; it was
  written later the same session and carries its own verification status, because
  the runbook existing and the runbook having been executed are different claims.

## Alternatives rejected

- **Leave the documents alone and just work the queue.** The work would land and
  the documents would quietly describe a different project. This repository's
  standing rule is that a divergence between documents and reality gets recorded,
  not tolerated (docs/17 D4) — and a positioning gap is the kind a newcomer acts
  on before anyone notices.
- **Make Databricks a hard dependency and delete the local path.** It would
  destroy the parity assertion, the model-free CI tier, and the ability to
  measure anything without a workspace — paying the project's entire evaluation
  apparatus for a positioning statement. The local path is *why* the Databricks
  claim is credible.
- **Rewrite `docs/11_ROADMAP.md` into a Databricks-first sequence.** The roadmap
  is a record of how the build was phased, and phases 0–6 happened in that order.
  Rewriting history to match current priorities makes the document less useful and
  less true; a status note at the top that points at plan §8 does the same job
  honestly.

## What would revisit this

The target environment changing — the platform moving off Azure Databricks, or
the internal use case being dropped in favour of the portfolio framing. Either
would make this ADR wrong rather than outdated, and it should then be superseded
explicitly rather than reinterpreted. A second deployment target arriving
(Fabric, Snowflake, plain Kubernetes) does not revisit it either: that is a new
execution surface under the same engine, which is the architecture this ADR
protects.
