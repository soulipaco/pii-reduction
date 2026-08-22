# ADR-0031: A source can be asked what it has, without being read

**Status:** accepted · **Date:** 2026-08-22 · **Session:** 12

## Context

`SourceAdapter` exposed exactly one way to learn anything about a source: `load()`,
which materialises every row. Three consequences, and only the first was ever written
down:

1. **The service declares its column menus in a template**, by hand, because there was
   no other way to know what a source has. Pickup item 5 names this and is explicit
   that the fix is "an engine change, deliberately not improvised in the service".
2. **`docs/18` §2 asks an operator to name their own column** and offers no way to
   check the name. A typo is discovered when the run fails, after the load.
3. **On Unity Catalog the only way to answer "which columns?" was `toPandas()`** — the
   whole table pulled to the driver. A column picker that costs a production table
   scan is not a slow picker, it is one nobody uses.

## Decision

**`SourceAdapter.schema() -> SourceSchema`, on the protocol, implemented by every
adapter, and required to answer without reading data.**

| adapter | how it answers |
|---|---|
| `PandasSource` | the frame's own columns; already in memory |
| `CsvSource` | `nrows=0` — the header line and nothing after it |
| `ParquetSource` | `pyarrow.dataset` — the footer, no row group opened; a **partitioned directory** is accepted because `load()` accepts one |
| `SparkTableSource` | `spark.read.table(...).schema` — the metastore; the frame stays lazy and no action runs |

Front door: `pii-reduction describe <dataset>`, which prints the source's columns and
marks the ones the configuration processes, the one that is the row id, and any that
would collide with an output column. It exits 1 on any of the three, each a failure
that today happens after the load.

### Three things it deliberately does not do

**It does not return types.** A CSV has none, and inferring them means reading rows.
Adapters that *could* answer honestly (parquet, Delta) would then be the only ones that
did, and a caller could not tell "this column is not text" from "this adapter does not
know". One answer every adapter can give beats a richer one only some can.

**It does not return a row count.** Same reason, sharper: for a CSV it is a full read.

**It does not reach the service.** `pii_reduction.sources` is one of the nine names
in `ENGINE_INTERNALS_CLOSED_TO_THE_SERVICE`
(`test_the_service_layer_cannot_name_the_engines_internals`), so the service genuinely
cannot call this today — a column picker over HTTP needs a sanctioned relay, and that
is a design decision rather than a wiring change. Two reasons to leave it: the
allowlist exists precisely to stop the service growing engine knowledge one convenience
at a time, and an endpoint returning *every* column of a configured source would let a
caller enumerate the columns a template deliberately withheld.

Two shapes are worth naming for whoever picks this up, and the **second is better**:

1. An **intersection** — "of the columns this template offers, here are the ones the
   source actually has". It does not enumerate the schema, but it is not zero
   disclosure either: a caller learns *which* declared columns the source lacks, which
   is one bit per offered column about a source the operator did not publish. Small,
   probably acceptable, and it should be written as the trade it is.
2. **Validate every template against `schema()` at `create_app` startup**, log the
   mismatch as metadata, and expose **no endpoint at all**. It catches the same typo,
   earlier, with nothing crossing the HTTP boundary — and it needs the same relay, so
   it costs no more design work than the endpoint does.

### The property is tested, not documented

`tests/test_source_schema.py` pins it per adapter, through readers that fail if the
data is touched:

- **CSV** — a file whose second line is unparseable, and a configured `nrows` that must
  be ignored;
- **parquet** — `read_table`, `ParquetFile.read_row_group` and `pd.read_parquet` all
  patched to raise, so swapping the footer read for a full read fails the test. The
  column assertions alone would not: `pd.read_parquet(path).columns` returns the same
  tuple;
- **Spark** — a fake session whose frame raises on any attribute but `schema` and
  records `toPandas` as an action. The test asserts the action list is **empty**, and a
  companion asserts `load()` *does* populate it, so the negative test is measuring
  something.

## Consequences

- Adding a method to a `runtime_checkable` Protocol means an adapter that forgets it
  stops conforming. `TestProtocolConformance` asserts that structurally for the Spark
  adapter; the local ones are covered by mypy instead, because `build_source` is
  annotated `-> SourceAdapter`, which checks signatures rather than method names. The
  `PandasSource` gap — never returned by the registry — is what the new
  `test_the_protocol_requires_it` closes.
- `describe` is a local command. A `spark_table` source is refused, and the message
  says what is true — **no command describes one yet** — rather than naming a
  subcommand that does not exist: `pii-reduction-databricks` registers `run` and
  nothing else. Wiring `describe` into that surface is a small, named gap, recorded in
  `docs/18` §9.
- **Not verified against a real Unity Catalog table.** The Spark path is unit-tested
  against a fake session that asserts laziness; no workspace call has been made, and
  the claim that a metastore lookup is cheap is Spark's contract rather than this
  project's measurement.
- Column *names* now cross a boundary they did not before (stdout). `docs/09` lists
  `column` among the fields a log line may carry, so this is within policy — but the
  policy now has a second consumer. A test asserts the **shape** of the output: one
  header line plus exactly one line per column, each beginning with that column's name
  and carrying only marks computed from the configuration. A positive assertion, so it
  cannot pass vacuously — the first version was a denylist that passed when the command
  had not run at all.
- **A parquet footer carries per-column min/max statistics — real values.** Only
  `.names` is taken, and that is a **rule, not an accident**: a later increment that
  added types or statistics "for the adapters that could answer honestly" would put
  actual column extrema on a display surface, which `docs/09` classes unsafe. Raised by
  the privacy audit as a forward-looking risk; recorded here so the next author meets
  it as a rule rather than rediscovering it.
- `describe` now checks **all three** of `Pipeline._validate_source`'s schema
  preconditions — configured columns present, row id present, output column not already
  taken. The row id was missing from the first version while three documents claimed it
  was covered.

## Alternatives considered

**Add `columns()` returning a bare tuple.** Rejected: the answer needs to carry which
source it came from, or a caller holding two of them cannot tell them apart, and the
`missing()` helper is the operation every consumer actually wants.

**Let `load()` take a `columns=` argument and call it with none.** Rejected: it makes
"read nothing" a special case of "read", which is exactly the shape that stops being
true the first time an adapter optimises the general path.

**Build the profiler instead** (`docs/20` D8 — eligible share, parser-fallback rate,
language mix). That is the larger and more useful tool, and it *needs* this: profiling
a column means knowing the columns exist. This is the half that can be built without
reading data at all, and the profiler necessarily reads.
