# ADR-0036: A template may offer a directory, and a caller may name a file in it

**Status:** accepted · **Date:** 2026-08-22 · **Session:** 14

## Context

The obvious next request for a hosted service is "let me upload a file and reduce it".
It is also the request this project has the most reason to be careful about, and the
carefulness has been earned rather than assumed:

- **ADR-0026 rule 4**: a caller may not name a source. `POST /runs` carrying a `source`
  field is a `422`, live in the hosted process.
- **The reason is measured, not cautious**: a Databricks App authenticates the end user
  and authorizes as its **own service principal**, whose default on-behalf-of-user
  scopes carry no data scope (`docs/19`). A caller who could name
  `catalog.schema.table` would make the service principal read it.
- **No endpoint accepts text**, enforced by a reflection test over every request model
  rather than by a filter.

A file upload appears to collide with all three. On examination it collides with fewer
than it looks, and the difference matters:

**The confused-deputy argument does not apply to an upload.** That guard exists because
naming a table makes the service read something the caller may not be entitled to. An
upload inverts the direction — the caller pushes data they already hold. What survives
is not a *disclosure* objection but an *operational* one: the service would then hold
customer PII on container-local disk, outside Unity Catalog, with its own retention and
residency story, and a JSON API would have to grow a multipart surface whose validation
errors echo file content.

Meanwhile `docs/18` §6 records something that makes all of that unnecessary: **a
Unity Catalog volume file needs no new adapter, because a volume path is a filesystem
path.** It was executed for real — a file uploaded to a volume, read through the
ordinary CSV source, reduced as a serverless job.

So the data can already arrive. What was missing is that the *template* fixes one exact
path, so a newly-arrived file needs a YAML edit before anyone can reduce it.

**Why ADR-0031's preferred shape does not govern here.** ADR-0031 faced a similar
question — should the service expose what a source contains? — and ruled that the
better shape is "validate every template against `schema()` at `create_app` startup and
expose **no endpoint at all**". A reader will reach for that precedent, and it does not
apply, for a reason worth stating rather than leaving to be re-litigated: ADR-0031's
question is about **columns**, which are fixed for the life of a source, so startup
validation can answer it once. This question is about **directory contents**, which
change between one request and the next. Startup validation structurally cannot answer
it. Where ADR-0031's reasoning *does* bite is the suffix table — see *Consequences*.

## Decision

**A template may set `select_file: true`, which makes its `source.path` a *directory*.
The caller then names one file inside it.**

```yaml
uc_volume_inbox:
  source:
    type: csv
    path: /Volumes/<catalog>/<schema>/<volume>/inbox/
  select_file: true
```

`GET /templates/{name}/files` lists what is currently there — **names only**.
`POST /configs` takes `source_file`, and the built configuration records the resolved
absolute path.

**The caller still cannot name a source.** The operator chose the directory; the caller
chooses among its contents. That is the same shape as picking a column from a declared
menu, and it keeps every reason ADR-0026 gave: nothing a request contains can point the
service's credentials at a place the operator did not sanction.

**And the service still never receives the file.** It is told *which* file to read. No
multipart endpoint, no upload buffer, no request model that can carry content — the
reflection test that proves that is untouched, because `source_file` is a *name*.

### Defences on the name, because one is never enough

This is the only place in the service where a caller-supplied string becomes part of a
filesystem path.

1. **The name is a name.** `^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$` — no separator, no
   `..`, no leading dot, no absolute form, bounded. Rejected by pydantic, so a traversal
   attempt is a `422` that does not echo what was sent. Two further rules close
   *canonicalisation* gaps the pattern alone does not, both found by probing rather
   than by reasoning, and both refused **on every platform** so a config built on Linux
   and run on Windows cannot mean two things:
   - **a trailing dot** — Windows strips it when opening, so `report.csv.` opens
     `report.csv`: two names for one file, and the listing shows only one of them;
   - **a reserved device name** — `NUL`, `CON`, `COM1` pass the pattern *and* the
     containment check, because they resolve inside the directory. Opening one reaches
     a device rather than a file: `NUL` is an empty stream, `COM1` a serial port a read
     can block on. Not a disclosure and not a traversal, but a way to make a run behave
     strangely, which is reason enough to refuse a name nobody legitimately wants.

   Canonicalisation mismatches get their own rules rather than a looser pattern because
   they are where traversal bugs are born: the name that was checked stops being the
   name that is opened. `console.csv`, `nullable.csv` and `a..b.csv` remain valid — the
   rule matches the stem, not a substring, and a test says so.
2. **The joined path is resolved and must land inside the declared directory.** This is
   the load-bearing one: the pattern closes every *textual* route out, but a **symlink**
   inside the directory has an ordinary name, and only resolving both sides catches it
   pointing elsewhere.

**One predicate serves both the listing and the builder**, so a picker cannot offer a
name the builder would refuse — or, worse, accept one it never offered.

Both defences are tested separately, because either alone would suffice and neither is
trusted to be the one that holds. The symlink tests need a privilege Windows does not grant by
default, so a third test drives the same containment branch by making resolution move
the path — the check is never untested on a developer's machine.

### The listing is names, one level, filtered — and never opens anything

`GET /templates/{name}/files` returns file names in the directory, not recursing, and
filtered to the suffixes the template's source type can read. A listing that walked
would be a way to explore a volume. A listing that opened a file would be the preview
endpoint ADR-0026 forbids by name.

A missing directory answers **empty rather than raising**: an inbox that has not been
created yet is an ordinary state on a workspace, and a 500 naming a path would put the
operator's directory in a response body. A template with a fixed source also answers
empty — the question has a correct answer for it, and that answer is none.

### What the listing does not offer, and will not for now

**A partitioned parquet directory cannot be picked.** `ParquetSource` reads one
happily — ADR-0031 made `schema()` accept one for exactly that reason — but the listing
filters on `is_file()`, so a directory written by Spark is invisible here. That is the
one source shape an inbox is most likely to receive, and it is a real limitation rather
than an oversight: offering a directory means the suffix rule has nothing to match, and
the containment and canonicalisation checks would need a segment-by-segment version.
**Reopens when somebody has a partitioned inbox**, with those checks extended rather
than relaxed.

**`.tsv` and `.txt` are not offered for a CSV template**, although `CsvSource` reads
both — it takes a `delimiter` option and passes any path to `pd.read_csv`. The offer is
deliberately narrower than the adapter: an inbox is a shared directory whose contents
nobody reviewed, so it offers the unambiguous case only. Widening it is a decision
about what an operator is promising, not a bug fix.

### The build does not check that the file exists

Deliberately. Checking would mean the service reaching into a data directory to answer
a question about a *configuration*, and it would still be a race — the file can vanish
between the check and the run. The run's own source error is the honest report, and it
names the missing path to the person who can fix it.

## Consequences

- **"Upload a file and reduce it" works, without the service becoming a file service.**
  Drop a file in the directory — through Databricks' own volume upload, a job, or `cp`
  locally — and it appears in the picker.
- **The data never leaves the governed perimeter.** A volume file stays in Unity
  Catalog, under its grants and its audit, and the reduced output lands where the
  template says. Nothing transits the service.
- **The generated configuration is self-contained**, recording the resolved absolute
  path rather than the name — so `pii-reduction run <dataset>` reads it later with no
  memory of which template produced it. Verified: a config the control panel wrote
  from a picked file runs identically from the local CLI.
- **Local is a first-class case, not a simulation of the workspace one.** The shipped
  `corpus_inbox` template points at `data/inbox/`, so the whole flow is exercisable from
  a clone with no Databricks at all — which is also how it is tested.
- **`docs/09`'s display-surface allowlist gained an entry, and it is the first
  data-derived one.** Every other name on that list is configuration-derived. A source
  filename is not: somebody chose it when they dropped the file. It is recorded there
  explicitly rather than folded into the `destination` bullet, with the three things
  that bound it and the one thing that does not.
- **`PATH_SOURCE_SUFFIXES` lives in `config/registries.py`, not in `service/`.** An
  earlier draft put it beside the listing code, which would have made it the first
  restatement of engine knowledge inside `service/` pinned by nothing. `docs/01` names
  the rule: a capability the service needs that the engine lacks becomes a change to
  the engine, through the sanctioned relay. Pinned against `KNOWN_SOURCE_TYPES` in both
  directions, so a new path-based source type fails a test rather than getting a
  silently empty listing.
- **Filenames become visible to everyone who may use that template**, and that is the
  one disclosure this adds. It is `select_file`-gated per template, so it is the
  operator's decision — and they need to know that an inbox is a shared surface. A file
  named after an individual puts that individual's name in a listing. Recorded in
  `docs/19` beside the run-history note, which has the same shape.

### What is **not** verified

**Whether a Databricks App can see `/Volumes` is unverified by this project.** The
runbook's verified route for volume ingestion is a serverless job (`docs/18` §6), and
the App's own runtime is `local`. The mechanism here is path-based and therefore works
wherever the process can see the path; whether that includes an App container is a
question for `ls /Volumes/...` from the App, not an assumption this ADR makes. The
shipped commented template says so in place.

## What would reopen this

- **A real multipart upload**, if the operational objections are answered rather than
  avoided: where the bytes live, for how long, under whose grants, and what stops a
  validation error echoing file content. This ADR does not rule it out; it observes
  that the volume route delivers the same outcome without needing those answers.
- **Sub-directories.** The listing is one level, and a dated-folder inbox
  (`inbox/2026-08/`) is the obvious next shape. It needs a segment-by-segment version
  of the same two defences, not a relaxed pattern.
- **A file the caller can also *write*.** Everything here is read-only for the caller.
  A "put your file here" endpoint is the multipart question above wearing a different
  hat.

## Alternatives rejected

- **Accept a multipart upload into the service.** The service principal would then hold
  customer PII on container-local disk — ephemeral, single-replica, outside Unity
  Catalog governance — and the framework's own validation errors commonly echo the
  offending input, which for a file body is the file. The volume route gets the same
  user experience and keeps the data inside the perimeter it was already in.
- **Let the caller send a full path.** That is `source` under another name, and it is
  the confused deputy ADR-0026 refused.
- **Have the template list its files explicitly**, like `columns`. It makes every new
  file a YAML edit and a redeploy, which is the problem being solved.
- **Check the file exists at build time.** It puts a data-directory read inside a
  configuration question and is still a race; see above.
- **Let the listing recurse.** A volume can hold a great deal that is not for this
  template, and a recursive listing is an exploration tool.
