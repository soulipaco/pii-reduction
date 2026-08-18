"""Download the public datasets a demo pack is built from.

    python demo/download_datasets.py                     # every registered dataset
    python demo/download_datasets.py bitext_customer_support

Each file is fetched from a pinned commit revision and checked against the SHA-256
recorded in ``demo/registry.yaml`` (ADR-0017). Nothing downloaded here is committed:
``data/downloads/`` is gitignored, and a pack is rebuilt from source rather than stored.

The licence gate runs before any transfer. A dataset with no registry entry, a
non-permissive licence, a source carrying real personal data, or one recorded under
``rejected:`` is refused — with, in the last case, the reason it was rejected, so the
decision is not quietly re-taken.

``build_pack.py`` fetches what it needs on its own; this script exists for the case
where downloading and building want to be separate steps — a slow link, a proxy, or a
machine that will build several packs.
"""

from __future__ import annotations

import sys

from pii_reduction.cli import main
from pii_reduction.synthetic.packs import DEFAULT_REGISTRY
from pii_reduction.synthetic.registry import load_registry

if __name__ == "__main__":
    keys = sys.argv[1:] or sorted(load_registry(DEFAULT_REGISTRY))
    sys.exit(max(main(["fetch-dataset", key]) for key in keys))
