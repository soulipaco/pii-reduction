"""Regenerate the committed synthetic corpus.

    python demo/build_corpus.py --out tests/fixtures/corpus --seed 42

The generator itself lives in :mod:`pii_reduction.synthetic` because it is reusable
library code (``AGENTS.md`` rule 3): Increment D reuses the same injection engine at
volume against public datasets. This file is only a runnable front door.

Same seed and size give a byte-identical corpus and manifest (ADR-0011). Regenerating
with different values is a deliberate act that shows up as a diff in
``tests/fixtures/corpus/``.
"""

from __future__ import annotations

import sys

from pii_reduction.cli import main

if __name__ == "__main__":
    sys.exit(main(["build-corpus", *sys.argv[1:]]))
