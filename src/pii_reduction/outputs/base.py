"""Output adapter contract.

Outputs preserve row grain, append reduced columns, and persist run metrics
(``docs/01_ARCHITECTURE.md`` layer 10). Like sources, they are built from primitives
so this package never imports ``config``.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

import pandas as pd

__all__ = ["OutputAdapter"]


@runtime_checkable
class OutputAdapter(Protocol):
    @property
    def destination_type(self) -> str: ...

    def write(self, frame: pd.DataFrame, *, name: str) -> str:
        """Persist ``frame`` and return the location written."""
        ...
