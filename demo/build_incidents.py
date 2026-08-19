"""Regenerate the committed incident-notes stress corpus.

    python demo/build_incidents.py --out tests/fixtures/incidents --seed 42

Unlike the packs under `demo/packs/`, this needs no download: there is no external
source, only the generator in :mod:`pii_reduction.synthetic.incidents` and its seed.
That is also why it is committed rather than rebuilt on demand — a corpus nobody can
fetch has to live somewhere, and committing it lets CI check it byte for byte.

It exists to stress the over-redaction gate, which was thinly supported before it
(ADR-0022). It is **not** a public-dataset pack and must never be published or quoted
as one: its prose is ours, so it says nothing about performance on real text.

Same seed and size give a byte-identical corpus and manifest (ADR-0011). Regenerating
with different values is a deliberate act that shows up as a diff in
``tests/fixtures/incidents/``.
"""

from __future__ import annotations

import sys

from pii_reduction.cli import main

if __name__ == "__main__":
    sys.exit(main(["build-incidents", *sys.argv[1:]]))
