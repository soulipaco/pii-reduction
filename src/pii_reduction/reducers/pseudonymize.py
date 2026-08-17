"""Deterministic pseudonymization: ``Maria Rossi`` becomes ``PERSON_7F2A91``.

The point is linkage without identity: the same person appearing in fifty rows gets
the same token, so counts, joins and journey analysis still work on reduced data,
while the original value is not recoverable from the output.

Design constraints, all from ``docs/04_PII_ENGINE.md`` and ``docs/06``:

* **Keyed hash, key from the environment only.** HMAC-SHA256 over the matched value.
  The key is read from the variable named by ``key_env`` and never from YAML, never
  from a default, and is never logged or included in the config fingerprint.
* **Configurable scope** — ``dataset``, ``project`` or ``global`` — mixed into the
  HMAC message, so the same name in two datasets yields different tokens under
  dataset scope. Scope choice is a linkability decision, not a formatting one.
* **No reverse mapping.** Nothing here can turn a token back into a value, and no
  mapping table is persisted. Reversible tokenization is explicitly out of scope
  (``docs/00_PROJECT_CHARTER.md``).
* **Collision handling.** Tokens are a truncated digest, so collisions are possible
  (with the 6-hex default, about a 1-in-2 chance somewhere after ~4,800 distinct
  values of one entity type — the birthday bound on 16.7M). Collisions are detected
  *within a process* by keeping digest-to-token pairs (digests, never plaintext) and
  raising rather than silently merging two identities. Across processes and Spark
  workers no such check is possible, so `token_length` is configurable and the
  benchmark reports distinct-token counts; treat 6 as a demo default, not a
  production one.

Determinism follows ADR-0011: the value is hashed exactly as it appears, with no
Unicode or case normalization, so ``Maria`` and ``maria`` are different subjects
unless ``case_sensitive: false`` is set deliberately.
"""

from __future__ import annotations

import hashlib
import hmac
import os
from typing import Any

from pii_reduction.contracts.entities import ResolvedEntity
from pii_reduction.reducers.base import BaseReducer
from pii_reduction.reducers.errors import PseudonymizationKeyError, ReducerError

__all__ = ["DEFAULT_KEY_ENV", "PseudonymizeReducer"]

DEFAULT_KEY_ENV = "PII_PSEUDONYMIZATION_KEY"

#: Minimum key length. Not a cryptographic bound — a floor that rules out the
#: single-word keys that make an HMAC over low-entropy values enumerable.
MIN_KEY_LENGTH = 32

SCOPES = frozenset({"dataset", "project", "global"})

DEFAULT_OPTIONS: dict[str, Any] = {
    "key_env": DEFAULT_KEY_ENV,
    "scope": "dataset",
    "token_length": 6,
    "case_sensitive": True,
    #: ``PERSON_7F2A91``; set to e.g. ``"-"`` for ``PERSON-7F2A91``.
    "separator": "_",
}


class PseudonymizeReducer(BaseReducer):
    """Keyed, deterministic, non-reversible tokens."""

    name = "pseudonymize"

    def __init__(
        self,
        options: dict[str, Any] | None = None,
        *,
        scope_value: str | None = None,
    ) -> None:
        merged = dict(DEFAULT_OPTIONS)
        unknown = sorted(set(options or {}) - set(DEFAULT_OPTIONS))
        if unknown:
            raise ReducerError(
                f"reducer {self.name!r}: unknown options {', '.join(unknown)} "
                f"(known: {', '.join(sorted(DEFAULT_OPTIONS))})"
            )
        merged.update(options or {})

        scope = merged["scope"]
        if scope not in SCOPES:
            raise ReducerError(
                f"reducer {self.name!r}: scope {scope!r} is not supported "
                f"(known: {', '.join(sorted(SCOPES))})"
            )
        token_length = int(merged["token_length"])
        if not 4 <= token_length <= 64:
            raise ReducerError(
                f"reducer {self.name!r}: token_length must be between 4 and 64, got {token_length}"
            )
        if scope != "global" and not scope_value:
            raise ReducerError(
                f"reducer {self.name!r}: scope {scope!r} requires a scope value "
                "(the dataset or project name) to be supplied by the caller"
            )

        key_env = str(merged["key_env"])
        key = os.environ.get(key_env)
        if not key:
            raise PseudonymizationKeyError(
                f"reducer {self.name!r}: no pseudonymization key found. Set the {key_env} "
                "environment variable; keys must never be stored in configuration"
            )
        if len(key) < MIN_KEY_LENGTH:
            # The point of keying is dictionary resistance over low-entropy values
            # like names and phone numbers; a short key does not provide it. The
            # message reports the length only, never the value.
            raise PseudonymizationKeyError(
                f"reducer {self.name!r}: the key in {key_env} is {len(key)} characters; at "
                f"least {MIN_KEY_LENGTH} are required. Tokens are derived from values with "
                "very little entropy (names, phone numbers), so a short key can be brute "
                "forced by enumerating candidates"
            )

        self.options = merged
        self._key = key.encode("utf-8")
        self._scope = scope
        self._scope_value = "" if scope == "global" else str(scope_value)
        self._token_length = token_length
        self._case_sensitive = bool(merged["case_sensitive"])
        self._separator = str(merged["separator"])
        #: digest -> token, for in-process collision detection. Holds no plaintext.
        self._seen: dict[str, str] = {}

    def token_for(self, entity_type: str, surface: str) -> str:
        """The token a value maps to. Same inputs and key always give the same token."""
        value = surface if self._case_sensitive else surface.casefold()
        message = "\x00".join((self._scope, self._scope_value, entity_type, value))
        digest = hmac.new(self._key, message.encode("utf-8"), hashlib.sha256).hexdigest()
        token = f"{entity_type}{self._separator}{digest[: self._token_length].upper()}"

        previous = self._seen.get(token)
        if previous is not None and previous != digest:
            raise ReducerError(
                f"reducer {self.name!r}: token collision for {entity_type} at token_length="
                f"{self._token_length}; two distinct values map to the same token. Increase "
                "token_length"
            )
        self._seen[token] = digest
        return token

    def _replacement(self, entity: ResolvedEntity, surface: str) -> str:
        return self.token_for(entity.entity_type, surface)
