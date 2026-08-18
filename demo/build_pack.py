"""Build a demo pack from a public dataset.

    python demo/build_pack.py support_tickets
    python demo/build_pack.py multilingual_utterances --out demo/packs/utterances

The source is downloaded on first use and verified against the checksums in
``demo/registry.yaml`` (ADR-0017); afterwards the cache under ``data/downloads/`` is
reused. Neither the download nor the pack is ever committed — both are gitignored, and
``version`` plus ``retrieval`` in the registry are what make the pack reproducible
instead.

The builder itself lives in :mod:`pii_reduction.synthetic.packs` because it is reusable
library code (``AGENTS.md`` rule 3). This file is only a runnable front door, matching
``demo/build_corpus.py``.
"""

from __future__ import annotations

import sys

from pii_reduction.cli import main

if __name__ == "__main__":
    sys.exit(main(["build-pack", *sys.argv[1:]]))
