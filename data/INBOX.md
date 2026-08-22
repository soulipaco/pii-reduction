# `data/inbox/` — the local service inbox

The shipped `corpus_inbox` service template (ADR-0036) offers `data/inbox/`: drop a CSV
there and it appears in the control panel's file picker, ready to configure and run.

**The directory is not tracked, and neither is anything you put in it.** `.gitignore`
excludes it whole, with no negation — including for this file, which is why the
explanation lives here rather than inside the target it describes. A negation would be
case-insensitive on Windows and macOS, so `!README.md` would also un-ignore `readme.md`,
and an upload bundle containing one would be staged by `git add -A`. `AGENTS.md` rule 2
forbids private production data anywhere in this tree; this is the mechanism, not the
reminder.

Create it when you want it:

```bash
mkdir -p data/inbox
cp tests/fixtures/corpus/corpus.csv data/inbox/
pii-reduction-service --configs configs
```

Then pick `corpus_inbox` in the panel.

## Two things to know before using one for real

**File names are visible to everyone who may use the template**, through
`GET /templates/{name}/files` and the picker. An inbox is a shared surface — do not
name files after individuals.

**For a workspace, point the template at a Unity Catalog volume**
(`/Volumes/<catalog>/<schema>/<volume>/inbox/`) rather than at a path inside the
deployment. A volume keeps the data under Unity Catalog's grants and audit; a container
path is ephemeral local disk outside all of it. See `docs/19_SERVICE_LAYER.md`.
