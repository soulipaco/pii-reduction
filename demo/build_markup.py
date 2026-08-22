"""Regenerate the committed markup corpus.

    python demo/build_markup.py --out tests/fixtures/markup --seed 42

Like the incident-notes corpus and unlike the packs under `demo/packs/`, this needs no
download: there is no external source, only the generator in
:mod:`pii_reduction.synthetic.markup_notes` and its seed. That is also why it is
committed — a corpus nobody can fetch has to live somewhere, and committing it lets CI
check it byte for byte.

It exists because ADR-0027 shipped a detection change with **no corpus support at all**
(ADR-0029). It is **not** a public-dataset pack and must never be published or quoted
as one: its prose is ours, so it says nothing about performance on real text. What it
measures honestly is whether machine syntax survives reduction.

Same seed and size give a byte-identical corpus and manifest (ADR-0011). Regenerating
with different values is a deliberate act that shows up as a diff in
``tests/fixtures/markup/``.
"""

from __future__ import annotations

import sys

from pii_reduction.cli import main

if __name__ == "__main__":
    sys.exit(main(["build-markup", *sys.argv[1:]]))
