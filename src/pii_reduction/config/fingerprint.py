"""Configuration fingerprint.

A benchmark number is only reproducible if you can say exactly which settings
produced it, so run metadata carries a stable hash of the effective non-secret
configuration (``docs/06_CONFIGURATION_CONTRACT.md``). Two rules make it useful:

* it must be stable across processes and dict ordering — hence canonical JSON with
  sorted keys, and no reliance on Python's hash randomization;
* it must never contain secret material — keys whose names look secret-bearing are
  removed from the hash input entirely rather than masked.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from pii_reduction.config.resolved import ResolvedDataset

__all__ = ["SECRET_KEY_HINTS", "config_fingerprint", "fingerprint_material"]

#: Substrings that mark a key as potentially secret-bearing. Matching keys are
#: dropped from the hash material (and from any persisted config snapshot).
SECRET_KEY_HINTS: tuple[str, ...] = (
    "token",
    "secret",
    "password",
    "passwd",
    "credential",
    "private_key",
    "api_key",
    "access_key",
    "client_secret",
    "host",
)


def _is_secret_key(key: str) -> bool:
    lowered = key.lower()
    return any(hint in lowered for hint in SECRET_KEY_HINTS)


def _strip_secrets(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _strip_secrets(v) for k, v in value.items() if not _is_secret_key(str(k))}
    if isinstance(value, list):
        return [_strip_secrets(item) for item in value]
    return value


def fingerprint_material(resolved: ResolvedDataset) -> dict[str, Any]:
    """The exact structure that gets hashed, for debugging and for config snapshots."""
    dumped: dict[str, Any] = resolved.model_dump(mode="json")
    return dict(_strip_secrets(dumped))


def config_fingerprint(resolved: ResolvedDataset) -> str:
    """Stable SHA-256 over the effective non-secret configuration."""
    payload = json.dumps(
        fingerprint_material(resolved),
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
