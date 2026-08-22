# Finalization: what "done" means, and the shortest path to it

Written at the end of session 12 (2026-08-22), for session 13, whose brief is to
**finish this project**.

Everything below is either a small piece of work with an exit criterion, or a decision
to park something explicitly. Nothing here is exploration. If session 13 does only
Part 1 and Part 3, the project is finished by the definition its own charter wrote.

---

## Where this actually stands

**The engine is complete and the platform runs end to end.**

| | state |
|---|---|
| Roadmap phases 0–6 | built, measured, gated |
| Charter *Definition of done* (9 items) | **all met** |
| Databricks driver path | verified on the real workspace |
| Runbook (`docs/18`) | executed end to end |
| Service layer (rung 4) | built, run, and **hosted as a Databricks App** |
| Identity question | **answered by measurement** (`docs/19`) |
| Durable run store | built and verified across a real restart |

1226 default-tier tests, 92 integration, **56 regression gates across three corpora**,
31 ADRs, CI green on Linux and Windows. No published benchmark number has ever moved
without being re-measured.

**What is left is not engineering. It is closing the open items honestly and cutting a
release.**

---

## Part 1 — Park every open item, explicitly (half a session)

The single most valuable finalization act. Each of these is *open*, and an open item
with no recorded decision is how a finished project reads as an abandoned one. Each
needs a sentence in the right place saying **parked, and what would reopen it** — not
new work.

| # | item | where it lives | suggested disposition |
|---|---|---|---|
| 1 | **The speaker-prefix question** — a work-note author is never offered to a provider, so tier-4 PERSON recall is 0.000 and cannot move | ADR-0022, plan §8, `docs/08` | **Write the ADR.** It is called "the most serious open design item" in three places and has been open since session 8. It is a *decision*, not code: redacting inside a preserved prefix collides with the reconstruction guarantee. ADR-0028's reachability metric now measures its exact cost (90 of 315 entities). Decide "preserved, and here is why" — the reference implementation's owner ruled the same way (`docs/20` R5) — or "reduced, and here is the parser option". Either is finishable in one sitting. |
| 2 | **Markup destroys PERSON recall** (0.322 vs 0.821) | ADR-0029 | **Park with the condition.** The remedy — strip markup before detection, map offsets back — changes the model's *input*, which plan §8 Q2 measured as trading one error for another twice. Reopens when someone can measure it on `tests/fixtures/markup`, which now exists for exactly that. |
| 3 | **Batching (P5)** — `detect_batch` still has no caller | plan §8, `docs/17` D10 | **Do it or park it.** It is the last pickup-list item. If done, it carries a measurement obligation: rows/s before and after. If parked, say that the condition (a surface using the path) has arrived and the reason for not doing it is scope, not readiness. |
| 4 | **Greek PERSON** — licence-bound to `xx_ent_wiki_sm` | ADR-0007, ADR-0019/0020/0021 | **Park.** Phase 7 work; diagnosed to the mechanism, two of three mechanisms already addressed. |
| 5 | **The distributed Spark path** | plan §8, ADR-0006 | **Park.** `ISOLATION_STARTUP_FAILURE` is Databricks infrastructure; a `databricks`-marked test flips from skip to assertion the day it is fixed, with no code change. |
| 6 | **`bundle deploy`** | plan §8, `docs/19` | **Park.** CLI v0.280.0's expired Terraform signing key. Note the correction session 12 made: this never blocked Apps, which deploy without a bundle. |
| 7 | **`docs/20` §9 follow-ons** — source profiler (D8), case augmentation (D1), row-scoped gazetteer + protected terms (D2/D3) | `docs/20` | **Already parked with conditions.** Confirm nothing there reads as pending work. |
| 8 | **`docs/17` §7 deferrals** | `docs/17` | Already a decision table. Confirm still accurate. |

**Exit criterion:** every item above resolves to a sentence a reader can find, and plan
§8's queue contains nothing without a disposition.

---

## Part 2 — Optional: the one piece of work worth doing (half a session)

**Batching (P5)**, if and only if Part 1 and Part 3 are comfortable. It is the only
remaining pickup-list item, and its reopening condition arrived two sessions ago.

- Wire `detect_batch` into `FieldProcessor`/`Pipeline`.
- Measure rows/s before and after. The 10k pack needs a download; the committed corpus
  does not, and is the honest fallback — say which was used.
- Publish the number beside the existing ones. **Do not move a detection number**:
  batching must be output-identical, and a test should assert that.

**Exit criterion:** a rows/s figure published with its corpus named, and every one of
the 56 gates unchanged.

---

## Part 3 — Cut the release (half a session)

Roadmap Phase 11. Nothing here is hard; it is the difference between a repository and a
release.

1. **`CHANGELOG.md`** — does not exist. One entry, `0.1.0`, written from the ADR index
   and plan §8's Complete table. This is the artifact that makes twelve sessions legible
   to someone who arrives cold.
2. **Tag it.** No git tag exists. `v0.1.0` on the final commit.
3. **README final pass** — it is already good. Check only that the front-page claims
   match the current state: rung 4 is hosted, the identity finding is stated, and the
   test/gate counts are current.
4. **`NOTICE`** — still not owed. `docs/17` D14: MASSIVE is CC BY 4.0 and Bitext is
   share-alike, and both facts reach a pack's `meta.json`, but **nothing is published**,
   so nothing is owed. If session 13 makes the repository public, this becomes real and
   must land in the same change.
5. **Decide the App's fate.** It is running and holds compute:
   `databricks apps stop pii-reduction-service` stops it, `apps delete` removes it and
   its service principal. Whatever is chosen, say so in `docs/19` so the next reader
   knows whether the thing they are reading about still exists.

**Exit criterion:** `CHANGELOG.md` exists, a `v0.1.0` tag is pushed, CI is green, and
`docs/19` states whether the App is still running.

---

## What finalization does **not** mean

Stated so the finish line does not move:

- **Not Phase 7–10.** A better Greek model, an AI/BI dashboard, production-hardening
  patterns and MLflow tracking are all roadmap items that were never in the charter's
  definition of done.
- **Not a UI.** ADR-0026 decided rung 4 is an API; a UI is a client of it, and
  `docs/09`'s conditions for a Class B display surface are *not* met by hosting
  (`docs/19`, measured).
- **Not the distributed path**, which is blocked by Databricks infrastructure.
- **Not making any published number better.** `AGENTS.md` forbids tuning a benchmark to
  the model, and three corpora exist precisely so the numbers stay honest.

---

## The order to do it in

1. Part 1 (park everything, write the speaker-prefix ADR).
2. Part 3 (changelog, tag, README pass, App decision).
3. Part 2 only if both are done and there is room.

Part 1 and Part 3 together are one comfortable session and finish the project. Part 2 is
the nice-to-have, and it is the one that can be dropped without anything reading as
unfinished.
