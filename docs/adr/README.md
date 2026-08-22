# Architecture Decision Records

Decisions made from evidence (probes, licence checks, dataset verification) rather
than restated documentation. Each ADR lists what would have to be true for the
decision to be revisited. Produced starting session 2 (2026-08-17); see
`docs/14_IMPLEMENTATION_PLAN.md` for how they compose into the build sequence.

| ADR | Decision |
|---|---|
| [0001](0001-dependency-stack.md) | Deterministic core + Presidio/spaCy NER + lingua detection |
| [0002](0002-address-entity-deferred.md) | ADDRESS in taxonomy, not detected until Phase 7 |
| [0003](0003-fixture-domains-and-email-recognizer.md) | Fixtures use example.com/org/net; `.test` only in edge tests |
| [0004](0004-label-normalization-at-adapter-boundary.md) | Per-model label mapping inside provider adapters |
| [0005](0005-per-recognizer-confidence-thresholds.md) | Per-provider/per-entity thresholds; global threshold forbidden |
| [0006](0006-databricks-connect-and-pandas-pin.md) | Spark via Databricks Connect; `pandas>=1.5,<3` |
| [0007](0007-mit-licence.md) | MIT licence; Greek spaCy models (CC BY-NC-SA) excluded |
| [0008](0008-packaging-and-extras.md) | src layout; presidio/language/parquet/databricks/service extras + dev |
| [0009](0009-ci-design.md) | Model-free CI gate; nightly integration with md models |
| [0010](0010-demo-datasets.md) | Bitext, MultiWOZ 2.2, MASSIVE as demo sources |
| [0011](0011-evaluation-matching-and-ground-truth.md) | Strict-primary matching; manifest-only ground truth; no Unicode normalization |
| [0012](0012-language-detection-policy.md) | lingua detector with hard short-text gate |
| [0013](0013-mask-and-pseudonymization-in-a4.md) | Mask + deterministic pseudonymization pulled forward into Increment A4 |
| [0014](0014-synthetic-phone-number-ranges.md) | Synthetic phone numbers from published permanently-unassigned ranges |
| [0015](0015-cpu-only-deployment-target.md) | CPU-only is a hard constraint; no component may require a GPU |
| [0016](0016-line-splitting-option-not-a-key-value-parser.md) | `split_lines` option on the plain-text parser instead of the planned `key_value` parser |
| [0017](0017-dataset-retrieval-by-pinned-fetch.md) | Public datasets fetched as pinned files with recorded checksums, not via `datasets` |
| [0018](0018-bitext-supplies-both-packs-after-multiwoz-rejection.md) | MultiWOZ rejected for real PII; Bitext renders both the ticket and conversation packs |
| [0019](0019-greek-person-three-failure-modes.md) | Greek PERSON is span absorption + label confusion + the άνω τελεία; the corpus is not made easier |
| [0020](0020-greek-label-promotion-scoped-to-greek.md) | Greek-only LOC/ORG promotion to PERSON; strict precision traded for 43% less leakage; no surgery |
| [0021](0021-person-span-left-extension.md) | Extend a PERSON span left over one token (Greek only) — the visible error, not the trim that leaks |
| [0022](0022-incident-notes-as-an-over-redaction-stress-corpus.md) | `incident_notes` is a generated over-redaction stress corpus, not a public pack |
| [0023](0023-fail-closed-default-failure-mode.md) | Default failure mode is `quarantine_row`; raw-text pass-through is an explicit opt-in |
| [0024](0024-reduced-only-projection.md) | Opt-in reduced-only projection (local `destination.projection`, `run_driver` second prefix) makes the docs/09 grant model realisable |
| [0025](0025-databricks-is-the-primary-deployment-target.md) | Azure Databricks is the **primary deployment target**; local stays the development/test surface and a hard engineering constraint |
| [0026](0026-service-layer-is-a-thin-api.md) | Rung 4 is a **thin HTTP API**, hosted as a Databricks App rather than built as one; no service response may carry text |
| [0027](0027-markup-is-machine-syntax.md) | Clip model-inferred spans out of HTML/BBCode/URLs at the provider boundary, and check the written output with an **independently written** markup assertion |
| [0028](0028-reachability-decomposition-of-recall.md) | The benchmark reports how much ground truth the parser ever offered a provider, beside recall over it — a miss nothing could have caught is not a detection result |
| [0029](0029-a-corpus-for-the-markup-guard.md) | A committed markup corpus, because ADR-0027 shipped without one — and its first run found that markup **destroys PERSON recall**, not just structure |
| [0030](0030-the-service-journals-what-it-was-asked.md) | The service journals **what it was asked**; `<dataset>_run_metrics` records **what a run did**. Two records, joinable, deliberately not merged |
| [0031](0031-a-source-can-be-asked-what-it-has.md) | `SourceAdapter.schema()` — column names **without reading the rows**, so a picker or a config check costs a metastore lookup rather than a table scan |
| [0032](0032-the-speaker-prefix-stays-preserved-by-default.md) | The speaker prefix stays **preserved by default**; `preserve_prefix: false` is the ruled, measured opt-in for transcripts whose speakers are people |
| [0033](0033-batched-detection-within-a-row.md) | Detection batches **within a row** (1.6–1.8× on multi-segment columns, output-identical); across rows is refused because it would break ADR-0023's per-row quarantine |
| [0034](0034-what-a-caller-may-choose.md) | A caller may move a **quality** knob (now including parser options, from a template's menu) and never a **privacy boundary**; a choice is always a selection, never a free-form value |
