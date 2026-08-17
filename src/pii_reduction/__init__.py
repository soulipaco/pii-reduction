"""Databricks PII reduction accelerator.

Layer boundaries and dependency direction are defined in ``docs/01_ARCHITECTURE.md``.
The short version: everything depends on :mod:`pii_reduction.contracts`, and
:mod:`pii_reduction.contracts` depends on nothing inside this package.
"""

__all__ = ["__version__"]

__version__ = "0.1.0"
