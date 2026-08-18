# ADR-0017: retrieve public datasets as pinned files with recorded checksums, not through the `datasets` library

**Status:** accepted · **Date:** 2026-08-18 · **Session:** 6

## Context

Increment D builds demo packs from public corpora. `docs/02_PUBLIC_DATA_STRATEGY.md`
requires that raw data is never committed and that a pack is rebuilt from source:
"document the source and expected checksum/version". `demo/registry.yaml` already
records `retrieval_method: huggingface` and a `version` for each source, but nothing
retrieves anything yet, so those two fields are currently a promise rather than a
mechanism.

Both remaining sources (ADR-0018 removed MultiWOZ) are HuggingFace datasets, and the
retrieval mechanism was left open:

- add `datasets` as a new `demo` extra and call `load_dataset(...)`, or
- fetch the individual files over HTTPS at a pinned revision.

Facts established by probing the two repositories in this session:

| | `bitext/Bitext-…-training-dataset` | `AmazonScience/massive` |
|---|---|---|
| files on `main` | one 19.2 MB CSV | a loading **script**, no data |
| data reachable without a script | yes, the CSV | only via `refs/convert/parquet` |
| per-locale file | n/a (English only) | `de-DE/validation/0000.parquet` 159 KB, `el-GR/…` 205 KB |

Two consequences follow from that table. First, `datasets>=3` no longer executes
dataset loading scripts at all, so for MASSIVE it would resolve the *same*
auto-converted parquet files this project would fetch directly — the library would add
a layer, not a capability. Second, the whole retrieval for a pack is three files
totalling under 20 MB.

## Decision

**Fetch named files over HTTPS at a pinned commit revision, verify each against a
SHA-256 recorded in the registry, and cache them under `data/downloads/`.** No new
extra: the fetcher is `urllib` from the standard library. Reading MASSIVE's parquet
needs `pyarrow`, which is the **existing** `parquet` extra (ADR-0008, amended in
session 3) and is already installed by `dev`.

The registry gains a `retrieval:` block per dataset — repository, revision, and one
entry per file with its path, `sha256` and `bytes`. `synthetic/registry.py` parses and
validates it, so a dataset's licence record and its download instructions are the same
record and cannot drift apart.

Reasons, in the order they decided it:

1. **A checksum makes "reproducible from documented commands" checkable.** The exit
   criterion for Increment D is reproducibility. A recorded SHA-256 turns that into a
   thing the code asserts on every run: if upstream republishes the file, the fetch
   fails loudly and someone re-measures deliberately. `load_dataset` offers no
   comparable per-byte guarantee — its cache fingerprints depend on the library
   version, so the same call on two machines can produce different local artifacts
   without either being wrong.
2. **Dependency discipline (`AGENTS.md`, ADR-0008).** `datasets` pulls roughly ten
   transitive packages (`huggingface_hub`, `fsspec`, `dill`, `multiprocess`, `xxhash`,
   `aiohttp`, `tqdm`, `requests`, `pyarrow`) into a repository whose core is four. The
   rule is that every major dependency is justified; "it would save thirty lines of
   `urlopen`" does not justify ten.
3. **For the sources that remain, the library adds no capability.** See the table
   above: one CSV and two parquet files, one of which `datasets` would fetch by the
   identical URL.
4. **Failure modes are explicit and distinguishable.** A moved file is a 404, a
   republished file is a checksum mismatch, an offline machine is a connection error,
   and a corrupted cache entry is a checksum mismatch on the cached bytes. Each gets
   its own message naming what to do. A library that silently falls back to a warm
   cache would hide the second and fourth.

## Consequences

- **Revisions are pinned by hand and updated deliberately.** `demo/registry.yaml`
  carries the commit SHA per dataset. Moving to a newer revision is a visible diff that
  changes checksums, which is the intent — a corpus that silently changed underneath a
  published benchmark number is the failure this avoids.
- **MASSIVE is pinned to a generated branch.** Its parquet lives on
  `refs/convert/parquet`, which HuggingFace regenerates. Pinning the *commit* rather
  than the branch name keeps the URL stable, because the old commit stays resolvable;
  if it is ever garbage-collected the fetch 404s rather than fetching different bytes.
- **A cached file that fails its checksum is refused, not re-downloaded.** Silently
  replacing it would make a tampered or truncated cache self-healing and invisible.
  The message names the file and says to delete it.
- **Only `https://` URLs are accepted** from the registry, so a malformed or edited
  entry cannot turn the fetcher into a reader of arbitrary local paths.
- **No test downloads anything.** The checksum, cache and refusal logic are tested
  against `file://` URLs and temporary directories; CI never reaches the network, and
  a HuggingFace outage cannot turn a push red (ADR-0009 keeps the default tier
  model-free; this keeps it network-free too).
- **The pack gates are therefore local.** A pack cannot be rebuilt inside CI without a
  download, so pack gate files under `configs/pack_gates/` are run on demand rather
  than by a workflow. The synthetic gates in `configs/benchmark_gates.yaml` are
  unaffected and remain the CI regression floor.

- **The fetcher lives in `synthetic/`, not `sources/`, and that is a deliberate
  placement.** `sources/` is the runtime path: a `SourceAdapter` returns a
  `SourceDataset` and is reached from `pipeline.process`. `fetch()` returns a file path,
  runs at corpus *construction* time, and is never reachable from the pipeline. Putting
  a networked build-time tool into `sources/` would place it on the production
  processing path, which is the more expensive mistake. `docs/01_ARCHITECTURE.md` now
  records `synthetic/` as a build-time package for the same reason.
- **`registry.py` depends on `fetch.RemoteFile`**, so the licence record and the
  download instructions are one record and cannot drift. The cost is that a *malformed
  registry entry* is detected by `RemoteFile`'s validation, which raises a
  download-flavoured error; `registry.py` catches it and re-raises with the registry
  file and dataset key, so the fault is not misattributed to a transfer that never
  started.

## Alternatives rejected

- **A `demo` extra with `datasets`.** Rejected on 1–3 above. It would also make the
  first `pii-reduction build-pack` run a multi-hundred-megabyte install on a machine
  that already has everything it needs.
- **Committing a small sample of each source.** It is the one thing
  `docs/02_PUBLIC_DATA_STRATEGY.md` forbids outright, and it would make the pack a
  fixture rather than a test against the public corpus.
- **`huggingface_hub` alone** (`hf_hub_download`), the middle option. It is one
  dependency rather than ten and it does resolve revisions — but it caches by its own
  layout, verifies with the ETag rather than a checksum this repository recorded, and
  still would not remove the need to pin a revision by hand. It buys a redirect
  follower this project gets from `urlopen`.

## What would revisit this

A source that is genuinely not reachable as a small number of files — sharded across
hundreds of parquet parts, or gated behind an authenticated API — is the case direct
fetching does not cover. At that point `huggingface_hub` (not `datasets`) is the
smaller of the two steps, and the checksum record has to move to whatever that library
can verify.
