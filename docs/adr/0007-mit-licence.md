# ADR-0007: Repository licence is MIT; the Greek spaCy models are excluded as non-commercial

**Status:** accepted · **Date:** 2026-08-17 · **Session:** 2

## Context

`README.md` left the licence open pending a dependency review. Session 2 checked the
licences of everything ADR-0001 proposes, including the *models*, from their own
metadata:

| Component | Licence | Verified via |
|---|---|---|
| presidio-analyzer | MIT | package metadata |
| spaCy | MIT | package metadata |
| `en_core_web_lg`/`md` | MIT | model `meta.json` (probe) |
| `de_core_news_lg`/`md` | MIT | model `meta.json` (probe) |
| `xx_ent_wiki_sm` | MIT | model `meta.json` (probe) |
| **`el_core_news_lg`/`md`** | **CC BY-NC-SA 3.0** | model `meta.json` (probe) |
| lingua-language-detector | Apache-2.0 | package metadata |
| phonenumbers | Apache-2.0 | package metadata |
| pandas | BSD-3-Clause | package metadata |
| pydantic, PyYAML, Faker | MIT | package metadata |

The Greek spaCy models are **non-commercial** — documented in no project doc and
easy to ship by accident, since `el_core_news_lg` is the obvious pick for Greek.

## Decision

- Repository licence: **MIT** (simplest permissive; everything retained is
  MIT/Apache-2.0/BSD-compatible).
- `el_core_news_*` must never appear in dependencies, extras, install docs, or CI.
  Greek NER routes through `xx_ent_wiki_sm` (MIT) until a permissively-licensed
  multilingual model is added in Phase 7 with its own licence check.
- Dataset licences are tracked separately in the demo registry (CDLA-Sharing-1.0,
  MIT, CC BY 4.0 for the ADR-0010 candidates) and never mixed into the code licence
  claim. Model weights are never committed.

## Consequences

- Greek PERSON quality is bounded by `xx_ent_wiki_sm` for now; the benchmark shows
  it honestly (ADR-0011).
- Every future provider/model addition requires a licence entry in its
  documentation before merge (`AGENTS.md` provider checklist already demands this).
