# Walkthrough script — 4 minutes, nothing fabricated

`docs/11_ROADMAP.md` Phase 11 asks for a 3–5 minute walkthrough and records it as not
shipped. This is the script for it, written so it can be recorded in one take from a
clean clone.

**Every command below has been run and produces the output described.** Where a number
appears, it is the number the command actually prints — do not re-say it from memory if
your run differs; say what you see. That is the whole posture of this project.

**Nothing here needs a Databricks workspace.** The Databricks evidence is in
`docs/22_EVIDENCE.md` §6 and is best *told*, not demonstrated live — see §5 below for
why.

---

## Before you record

```bash
git clone <repo> && cd pii_reduction
pip install -e ".[dev]"
python -m spacy download en_core_web_md       # only for the hybrid run in §3
python -m spacy download de_core_news_md
python -m spacy download xx_ent_wiki_sm
```

Terminal at a readable font size. Browser at ~1360px, light mode. Close anything with a
real workspace URL, a token, or a customer name in it.

---

## §1 — The problem, in one screen (~30s)

Show the README's opening diff block. Say roughly:

> Operational text is where governance quietly fails. A ticket table can have clean
> schemas and controlled access while the `description` and `work_notes` fields still
> carry names, emails and phone numbers. The naive fix is a regex sweep, and it
> destroys the thing you kept the data for.

Point at the ticket id surviving:

```diff
- Please email James Whitfield at maria.rossi@example.net about ticket INC00100000.
+ Please email <PERSON> at <EMAIL> about ticket INC00100000.
```

> `INC00100000` survives. That is deliberate and it is measured — over-redaction is one
> of the numbers this project publishes.

## §2 — It is structure-aware, and that is the design (~45s)

Show the transcript example:

```diff
- 2026-04-03 09:15:13 - Guest: Hi, I'm Aisha Bello. Please call me on +1 202 555 0142.
+ 2026-04-03 09:15:13 - Guest: Hi, I'm <PERSON>. Please call me on <PHONE>.
```

> The timestamp and the speaker label are untouched. Not because a rule protects them
> afterwards — because the parser splits the cell into structure and content first, and
> the detector is only ever handed the content. Everything outside a reduced span comes
> back byte-for-byte.

Optionally show the mermaid diagram in the README while saying it.

## §3 — The numbers are gates, not claims (~60s)

```bash
pytest -q
```

> Fourteen hundred tests, and they run with no NLP model and no Spark — that is
> deliberate, because it is what makes them run everywhere.

```bash
pii-reduction benchmark
```

Point at `PERSON precision / recall = 0.000 / 0.000`.

> That is the deterministic chain — regexes. It finds every email and every phone
> number and **not one name**. Publishing that row is why the next one means anything.

```bash
pii-reduction benchmark --chain deterministic_presidio --gates configs/benchmark_gates.yaml
```

> Strict F1 0.910, leakage 0.067. And the last line is the point: these are not
> reported, they are **enforced**. Fifty-six regression gates across three corpora, and
> CI fails the build if any of them moves.

## §4 — It publishes what it gets wrong (~45s)

**This is the most important 45 seconds in the video.** Show the Greek example:

```diff
- Παρακαλώ στείλτε email στον/στην Μαρία Παπαδοπούλου στο maria.papadopoulou@example.net …
+ <PERSON> στείλτε email στον/στην Μαρία Παπαδοπούλου στο <EMAIL> …
```

> "Please" was taken for a name, and the actual name survived. This is a failure and it
> is on the front page.
>
> The reason is a licence: the good Greek spaCy models are non-commercial, and this is
> an MIT project, so Greek routes through a weaker multilingual model. The gap is
> diagnosed to three mechanisms, two of them are fixed, and Greek recall is published as
> 0.500 rather than rounded up.

> Anyone can show you a demo that works. The engineering question is what happens to the
> number when it does not.

## §5 — Where it runs (~45s)

```bash
pii-reduction-service --configs configs
```

Open `http://127.0.0.1:8000/`. Pick a template, tick the columns and entities, show the
parser options with their captions, build, save, run, let it reach `succeeded`.

> Same page a Databricks App serves — one static file inside the wheel, no build step,
> no CDN.

Point at the run summary.

> Counts, timings, a config hash. **No text anywhere on this screen**, and not because
> it is filtered out — because no endpoint in this service returns any. A request that
> tries to name its own source is refused with a 422.

On Databricks, **tell rather than show**:

> The driver path is verified against a real workspace, the runbook was executed end to
> end, and the service ran hosted as a Databricks App. That is written up with what was
> *not* verified beside it — the distributed path has never executed, because the
> workspace's serverless sandbox is broken, and the project says so instead of implying
> otherwise.

**Why not show it live:** the App's URL is a workspace URL, which this project's own
rules put on the unsafe side of a display surface. Showing a blurred address bar looks
worse than saying the sentence.

## §6 — Close (~30s)

> Thirty-six decision records. Every non-obvious choice has one, including the ones that
> were rejected and why. Two independent reviews and a second implementation of the same
> problem were reconciled against it item by item.
>
> The claim I would defend: **no published number in this repository has ever moved
> without being re-measured.**

---

## What not to say

- Do not claim the distributed Spark path works. It has never executed.
- Do not claim a Databricks App can read `/Volumes`. Unverified.
- Do not call it an estate scanner or say it "finds PII across your lakehouse". It
  reduces PII in columns an operator names — both external reviews flagged exactly this
  word, and the README was corrected for it.
- Do not imply compliance. It is an engineering accelerator; adoption needs legal,
  security and model-risk review.
- Do not show a real ticket, a real name, a workspace URL or a token. Everything on
  screen should be the committed synthetic corpus.

## LinkedIn post — the shape that matches this project

Lead with the failure, not the feature. Suggested skeleton, in your own words:

> I spent fourteen sessions building a PII reduction engine for Databricks. The thing I
> am proudest of is on the front page of the README, and it is a bug:
>
> [the Greek diff]
>
> "Please" was taken for a name. The real name survived. It is there because the good
> Greek NER models are non-commercial and this is an MIT project — so I published the
> weaker number instead of quietly dropping the language.
>
> 56 regression gates across three corpora. 1380 tests that need no model and no Spark.
> 36 decision records, including the ideas I rejected and why. No published number has
> ever moved without being re-measured.
>
> [link]

Two things worth mentioning if you want the engineering audience: that it was built
with an agent under a written policy (`AGENTS.md`), and that a privacy auditor written
for the project found a clickjacking hole in the project's own UI before it shipped.
Both are in the repository.
