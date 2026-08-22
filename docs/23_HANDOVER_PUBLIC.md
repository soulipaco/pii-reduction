# Handover: taking this public

Written at the end of session 14, for whoever does the last step. Everything here is a
short, bounded task with an exit criterion. **The engineering is done** — this is
presentation and publication, and one licence obligation that becomes real the moment
the repository stops being private.

Read `docs/22_EVIDENCE.md` first: it is the executed record, and it is what the
front-page claims rest on.

---

## 1. ~~The one thing that is not optional: `NOTICE`~~ — **DONE**

**The owner decided the repository goes public, so `NOTICE` was written in session 14**,
before the visibility change rather than with it. Nothing is outstanding here; what
follows is the record of what it covers and why.

Original framing, kept because it is the rule: nothing is owed while the repository is
private, and the moment it is public two obligations become real and must land no later
than the visibility change. `docs/17` D14 and the charter both say so.

No dataset is redistributed here — packs are rebuilt on demand from a pinned revision
with a recorded checksum (ADR-0017) — but the *build tooling and its documentation*
reference both sources, and one of the two licences is share-alike.

Everything needed is already recorded in `demo/registry.yaml`:

| dataset | licence | what it requires |
|---|---|---|
| Bitext customer support | **CDLA-Sharing-1.0** (`share_alike: true`) | https://cdla.dev/sharing-1-0/ — a *sharing* licence: anything published that is derived from the data carries the same terms |
| MASSIVE (AmazonScience) | **CC BY 4.0** (`attribution_required: true`) | https://creativecommons.org/licenses/by/4.0/ — attribution **and** an indication that changes were made |

Source URLs, the pinned revisions and the transformation applied are all in
`demo/registry.yaml`, and each built pack's `meta.json` carries the same fields.

**Exit criterion:** a `NOTICE` file naming both datasets, their licences, their source
URLs and the transformation this project applies, referenced from `README.md`'s
*License* section — committed in the same change that makes the repository public. Check
afterwards that the *License* section's current sentence ("Nothing is published today,
so no attribution is owed yet") is replaced rather than left contradicting the new file.

## 2. Screenshots — the one gap in the front page

The README leads with a text before/after, which is the right first thing. What it does
not have is a picture of the control panel, and a portfolio reader looks for one.

This could not be done in the session that built the panel: the agent's browser pane
would not composite frames, and a fabricated screenshot is worse than none.

It is a two-minute manual step:

```bash
pii-reduction-service --configs configs
# open http://127.0.0.1:8000/
```

Three shots worth having, in light mode, ~1360px wide:

1. **Build a configuration** — template picked, columns and entities visible, the parser
   options showing with their captions. This is the shot that proves the accuracy knobs
   are reachable, which is the whole point of ADR-0034.
2. **A finished run** — the `succeeded` pill with the metadata table under it. This is
   the shot that proves it is metadata-only: there is no text on the screen anywhere,
   because no endpoint returns any.
3. *(optional)* **The Reference tab** — the entity table with `ADDRESS` marked as
   detected by nothing. A reviewer who notices that notices the project's honesty.

**Everything on those screens is Class A synthetic** (`docs/09`, *Public demo
screenshots*) — the shipped `synthetic_corpus` template points at the committed corpus,
and the panel cannot display text in any case. Use the shipped templates, not a real
dataset.

Put them in `docs/images/` and reference them from the README under *See it work in two
minutes*. `.gitattributes` already marks `*.png` binary.

**Exit criterion:** at least shots 1 and 2 committed and rendered in the README.

## 3. GitHub repository front matter

Not settable from inside the repository; these are GitHub-side settings.

**Description** — one line, and it should say what it is *and* what it is not, because
the "not" is the credible part:

> Structure-aware, multilingual PII reduction for Databricks. Every published number is
> a regression gate. Not an estate scanner — it reduces PII in columns you name.

**Topics** (`docs/13` suggests these; all accurate):

```text
databricks  pii  privacy  presidio  nlp  named-entity-recognition
pseudonymization  data-governance  python  spacy  unity-catalog
```

```bash
gh repo edit soulipaco/pii-reduction \
  --description "..." \
  --add-topic databricks --add-topic pii --add-topic privacy \
  --add-topic presidio --add-topic nlp --add-topic data-governance
```

**Exit criterion:** description and topics set; the CI badge at the top of the README
renders green on the public page (it is already pointed at
`.github/workflows/ci.yml`).

## 4. Decisions the owner has to make, not the agent

These are listed because they are genuinely the owner's call, and none of them is
blocking:

All four were decided in session 14. Recorded with the reasoning, so a later reader can
disagree with the reasoning rather than guess at it.

- **Public or private? — PUBLIC.** `NOTICE` landed ahead of it (§1). The only remaining
  step is the GitHub visibility toggle itself, which is the owner's to make.
- **Do `CLAUDE.md` and `.claude/` stay? — THEY STAY**, and one thing was fixed on the
  way: `.claude/settings.json` carried an absolute path with the developer's OS
  username, now `Read(./**)`. Three reasons to keep them, in order of weight.

  **Agent involvement is already public in the git history** — every commit carries a
  `Co-Authored-By: Claude Opus 5` trailer. Deleting `.claude/` would not conceal it; it
  would only remove the evidence of how carefully it was governed.

  **The content is a strength for this project specifically.** `.claude/settings.json`
  denies reads of `.env`, `.databrickscfg`, `.aws/credentials`, `.ssh/**`, `*.pem` and
  `*.key`, and blocks `git push --force` and `rm -rf`. The two custom agents are a
  **privacy auditor** and an **architecture guardian**; the hooks are a privacy guard
  and a formatter. For a repository about reducing PII, a locked-down development
  environment is on-message rather than incidental.

  **`.claude/SESSION_HANDOFF.md` is the rarest artifact here** — fourteen sessions of
  engineering log that records the mistakes as well as the outcomes, including the same
  CI failure twice from a rule that was already written down. Most portfolios show only
  the finished thing.

  The honest counter-argument: some reviewers discount AI-assisted work. But hiding it
  while the commit trailers say otherwise is worse than owning it, and this project's
  entire credibility rests on not doing that kind of thing.
- **Is the Databricks App restarted? — NOT NEEDED.** The panel and the API are
  byte-identical whether served locally or by the App; a screenshot or a recording from
  `127.0.0.1` shows exactly what an App serves. The App costs compute while running and
  its address bar is a **workspace URL**, which this project's own rules put on the
  unsafe side of a display surface — so filming it hosted would mean blurring the one
  thing it was filmed to prove. Restart it only if a colleague needs to click it live.

  One caveat that changed in session 14: the stopped deployment **predates** the control
  panel, the caller knobs and the file picker. If it is ever restarted to demonstrate
  those, it needs `apps deploy` with the current wheel first — otherwise it serves a
  snapshot without them. `docs/22` §6 records this among the things not executed.
- ~~**A recorded walkthrough.**~~ **Decided: yes.** The script is
  `docs/24_WALKTHROUGH_SCRIPT.md` — four minutes, every command verified, with a
  *what not to say* list (do not claim the distributed path works; do not call it an
  estate scanner; do not show a workspace URL). It also carries a LinkedIn post skeleton
  that leads with the Greek failure rather than a feature.

## 5. One check worth running before publishing anything

```bash
uv venv /tmp/venv-core --python 3.11
VIRTUAL_ENV=/tmp/venv-core uv pip install -e ".[dev]"
VIRTUAL_ENV=/tmp/venv-core /tmp/venv-core/bin/pytest -q
```

**A green run on a development machine does not prove the push tier is green.** The dev
environment has the `presidio` and `language` extras; the tier CI installs does not.
This has cost two CI failures on this repository, and both times the rule was already
written down.

---

## What is deliberately *not* on this list

Nothing here reopens engineering. `docs/14` §8's *Parked, with the condition that would
reopen it* is the complete register of what is unbuilt — Greek beyond the licence
ceiling, the markup remedy, the distributed path, `ADDRESS`, the note-history parser —
each with the condition under which someone should pick it up. **Publishing does not
change any of them.**

And two things stay stated rather than quietly resolved, because both are true:

- **Whether a Databricks App can see `/Volumes` is unverified.** The proven volume route
  is a serverless job. One `ls /Volumes/...` from the App settles it.
- **An inbox listing shows filenames to everyone who may use that template**, and a
  filename can itself be personal data. It is the first data-derived entry on `docs/09`'s
  display-surface allowlist.
