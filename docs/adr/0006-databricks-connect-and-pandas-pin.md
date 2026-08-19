# ADR-0006: Phase 6 runs Spark via Databricks Connect; pandas pinned `>=1.5,<3`

**Status:** accepted · **Date:** 2026-08-17 · **Session:** 2

## Context

Local Spark is blocked on the development machine: only Java 22 is installed
(re-verified in session 2), PySpark 3.5 needs Java 8/11/17, and installing
Temurin 17 requires an elevated shell. Local Spark on Windows additionally needs
`winutils.exe`/`HADOOP_HOME`. Meanwhile the `databricks` CLI holds four valid
authenticated profiles against a workspace. PySpark 3.5's pandas API is
incompatible with pandas 3.x, and Databricks runtimes ship pandas 1.5/2.x.

## Options

1. Databricks Connect against the authenticated workspace for Phase 6 development
   and parity tests; local Spark optional for contributors who have Java 17.
2. Require local Spark (elevated JDK 17 install + winutils) as the Phase 6 path.
3. Defer all Spark work indefinitely.

## Decision

Option 1. The architecture already guarantees the same core pipeline behind
source/output adapters, so the execution surface choice is an adapter concern.
Workspace host/IDs come from CLI profiles or env at runtime — never committed
(`AGENTS.md` hard rule; the privacy hook blocks hard-coded hosts).

`pandas>=1.5,<3` is pinned in core **now** so the local baseline never drifts onto
a pandas that Spark-parity work cannot use.

**Amended (session 7, Increment F).** The decision held with three facts the
original could not know:

1. **The workspace is serverless-only** — classic cluster creation is refused
   ("no associated worker environments"), so Databricks Connect targets serverless
   compute. Client generations 15.4 (Python 3.11) and 16.4 (Python 3.12) both
   handshake with versionless serverless; the dedicated venv the isolated extra
   anticipated is real (`uv venv .venv-dbx --python 3.12`), and the extra now pins
   `databricks-connect>=15.4`.
2. **Serverless Python-UDF sandboxes are broken on this workspace's channel**
   (`ISOLATION_STARTUP_FAILURE`: the aarch64 image's own Python fails to exec —
   Databricks-side, reproducible, client-version-independent). The `mapInPandas`
   path is therefore shipped and proven at the function level in the default tier,
   and watched by a `databricks`-marked test that skips with the incident name and
   starts asserting distributed parity the day the sandbox works.
3. **Parity was met on the driver path**: corpus up as Delta, read through the
   Spark source adapter, the byte-identical local `Pipeline.process`, Delta out,
   read back — output-hash equality with the local run, plus audit and run-metrics
   Delta tables that carry metadata only.

## Consequences

- `databricks`-marked tests require credentials and are excluded from CI
  (ADR-0009); parity is asserted on the shared 100-row fixture via output hashes.
- CI and contributors without a workspace still run everything else.
- Wrong if: Databricks Connect's own dependency constraints clash with the core
  environment — then Phase 6 gets a dedicated environment/lockfile, which the
  isolated `databricks` extra already anticipates.
