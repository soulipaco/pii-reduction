"""Shape of a normalized entity label.

The contracts layer validates only the *shape* of a label (upper-snake, e.g.
``PERSON``), never its membership in the taxonomy. Membership belongs to
:mod:`pii_reduction.entities`, which owns the taxonomy — and ``contracts`` must not
import any other package in this repository (``docs/01_ARCHITECTURE.md``, dependency
direction). Providers, config validation and the reconciler all check membership via
``entities.taxonomy``; this type is what stops a provider-native string such as
``EMAIL_ADDRESS`` or ``PER`` from *looking* normalized when it is not.
"""

from __future__ import annotations

from typing import Annotated

from pydantic import StringConstraints

__all__ = ["NORMALIZED_LABEL_PATTERN", "NormalizedLabel"]

NORMALIZED_LABEL_PATTERN = r"^[A-Z][A-Z0-9_]*$"

NormalizedLabel = Annotated[str, StringConstraints(pattern=NORMALIZED_LABEL_PATTERN)]
