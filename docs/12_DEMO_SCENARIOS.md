# Demo Scenarios

## Objective

The portfolio demo should make the accelerator's value obvious in a few minutes. It should not require a reviewer to understand the full source code first.

## Which of these actually run today

This document was written in session 2, before any code existed, as the target. Nine of
the ten are real; **one is not, and a reviewer following it would find nothing there**,
so the status is here rather than discovered:

| demo | status |
|---|---|
| 1 — Customer support ticket | **runs** — `pii-reduction benchmark`, or the control panel |
| 2 — Transcript-aware reduction | **runs**, and the byte-exact round trip is pinned by test |
| **3 — Note history** | **DOES NOT RUN.** No `note_history` parser exists (charter UC-03, deferred as `docs/17` D13). A note column parsed as `transcript` gets most of the way, and ADR-0032 puts the note author in scope for it, but the header semantics this demo describes are not implemented. |
| 4 — Multilingual routing | **runs** — en/de/el, per-language provider chains |
| 5 — Provider benchmark | **runs** — `--chain deterministic_only` vs `deterministic_presidio`, and the comparison is 56 gates |
| 6 — False-positive protection | **runs** — the identifier guard; the incident corpus exists to price it (ADR-0022) |
| 7 — Ground-truth injection | **runs** — seeded, manifest-based, byte-reproducible (ADR-0011) |
| 8 — Local to Databricks parity | **runs**, and was executed on a real workspace (`docs/22` §6) — the *driver* path; the distributed path is infra-blocked |
| 9 — Scalability | **partly** — a 10k-document two-chain comparison exists (`docs/16`); the distributed path that would make this a scale demo has never executed |
| 10 — Privacy-safe audit | **runs** — the audit table is metadata-only by construction, asserted by test |

`docs/22_EVIDENCE.md` is the executed record. What follows is the original scenario
text, kept as written.

## Demo 1 — Customer support ticket

### Input

Synthetic/public-safe example:

```text
Ticket: INC-DEMO-00142
Short description: Customer cannot update profile
Description:
Customer Maria Rossi asked us to call her at +30 210 000 0000.
Her contact email is maria.rossi@example.com.
Machine: DEMO-PC-6915
KB Article: KB000002715
```

### Expected reduced output

```text
Ticket: INC-DEMO-00142
Short description: Customer cannot update profile
Description:
Customer <PERSON> asked us to call her at <PHONE>.
Her contact email is <EMAIL>.
Machine: DEMO-PC-6915
KB Article: KB000002715
```

### What this demonstrates

- mixed sensitive and non-sensitive identifiers,
- PII scope control,
- original operational IDs preserved,
- multiple entity types in one field.

---

## Demo 2 — Transcript-aware reduction

### Input

```text
2026-04-03 09:15:04 - Support Agent: Hello, how can I help?
2026-04-03 09:15:13 - Guest: Hi, I'm Maria Rossi. Please call me on +30 210 000 0000.
2026-04-03 09:15:42 - Support Agent: Can you confirm your email?
2026-04-03 09:15:49 - Guest: maria.rossi@example.com
```

### Expected output

```text
2026-04-03 09:15:04 - Support Agent: Hello, how can I help?
2026-04-03 09:15:13 - Guest: Hi, I'm <PERSON>. Please call me on <PHONE>.
2026-04-03 09:15:42 - Support Agent: Can you confirm your email?
2026-04-03 09:15:49 - Guest: <EMAIL>
```

### Required assertion

All metadata prefixes remain unchanged.

### What this demonstrates

- text segmentation,
- reconstruction,
- metadata preservation,
- multi-turn processing.

---

## Demo 3 — Note history

### Input

```text
2026/01/07 04:00:12 PM - Demo Agent (Additional comments)
Customer requested callback at +49 30 000000.

2026/01/07 12:05:30 PM - Demo Agent (Additional comments)
Customer confirmed the issue is resolved.
```

### Output

```text
2026/01/07 04:00:12 PM - Demo Agent (Additional comments)
Customer requested callback at <PHONE>.

2026/01/07 12:05:30 PM - Demo Agent (Additional comments)
Customer confirmed the issue is resolved.
```

### What this demonstrates

Multiple logical documents inside one database cell.

---

## Demo 4 — Multilingual routing

Create equivalent support examples in several languages.

### English

```text
My name is Maria Rossi and my email is maria@example.com.
```

### German

```text
Mein Name ist Lukas Schneider und meine E-Mail ist lukas@example.com.
```

### Greek

```text
Ονομάζομαι Μαρία Παπαδοπούλου και το email μου είναι maria@example.com.
```

Display:

```text
language detected
confidence
provider chain selected
entities found
reduced output
```

### What this demonstrates

Language is used operationally rather than merely displayed.

---

## Demo 5 — Provider benchmark

Run the same corpus through:

```text
Deterministic Only
Presidio Baseline
Hybrid
Multilingual NER
```

Show:

| Provider | PERSON F1 | EMAIL F1 | PHONE F1 | ADDRESS F1 | Leakage |
|---|---:|---:|---:|---:|---:|
| ... | ... | ... | ... | ... | ... |

### What this demonstrates

Engineering decisions backed by evidence.

---

## Demo 6 — False-positive protection

Input:

```text
Incident INC0004182 on DEMO-PC-6915 references KB000002715 and version 4.8.3.
```

Expected:

No change.

### What this demonstrates

The accelerator is not indiscriminately masking every identifier.

---

## Demo 7 — Ground-truth injection

Show a public-safe source sentence:

```text
Customer asked to receive a callback after lunch.
```

Generated benchmark sentence:

```text
Maria Rossi asked to receive a callback at +39 020 000 0000 after lunch.
```

Ground truth:

```json
[
  {"type": "PERSON", "start": 0, "end": 11},
  {"type": "PHONE", "start": 43, "end": 59}
]
```

### What this demonstrates

The benchmark knows the exact answer before the detector runs.

---

## Demo 8 — Local to Databricks parity

Run the same 100-row fixture:

```text
local pandas runner
Databricks Spark runner
```

Compare output hashes.

Expected:

Equivalent reduced text for deterministic provider configuration.

### What this demonstrates

One core engine, multiple execution environments.

---

## Demo 9 — Scalability

Generate or load a larger public-safe dataset.

Display:

```text
rows processed
characters processed
runtime
rows/sec
provider latency
workers/partitions
```

Compare two execution strategies if available.

### What this demonstrates

The project is more than a notebook experiment.

---

## Demo 10 — Privacy-safe audit

Show audit rows such as:

```text
run_018 | row_42 | transcript | PERSON | 15 | 26 | 0.94 | presidio | en
run_018 | row_42 | transcript | EMAIL  | 54 | 78 | 1.00 | deterministic | en
```

No raw matched PII appears.

### What this demonstrates

Observability without creating a second sensitive dataset.

---

# Recommended walkthrough order

A 3-5 minute portfolio walkthrough should follow:

1. What problem does this solve?
2. Show one support ticket.
3. Show transcript-aware preservation.
4. Show multilingual routing.
5. Show provider benchmark.
6. Show Databricks architecture/dashboard.
7. End with how a user configures their own source.

Avoid spending the first half of the video on folder structure.
