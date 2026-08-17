"""Benchmark regression gates: quality floors on the committed corpus.

A gate names one row of the benchmark report — a metric at a slice — and a bound it
must satisfy. Gate values are *measured*, never invented: each one is locked from a
baseline run and recorded in a versioned file so that changing it is a reviewed,
visible act (ADR-0009, ``CONTRIBUTING.md``).

Three failure modes matter more than the comparison itself, and each is a failure
here rather than a silent pass:

* a gate whose selector matches **no** row — the metric was renamed, the slice
  vanished, or the chain never ran. A gate that measures nothing must never be green.
* a gate whose selector matches **several** rows — then it is ambiguous which number
  was checked, so it is not a gate.
* a slice whose **support shrank** below what the gate was measured against. A floor
  is trivially satisfiable on a smaller corpus, so support is part of the claim.

Gates are quality floors only. ADR-0009 forbids wall-clock assertions here: runtime
varies with the machine, and a flaky gate gets weakened rather than investigated.

The comparison itself (:func:`evaluate_gates`) is pure and takes rows in memory;
only :func:`load_gate_file` touches the filesystem, so the interesting logic stays
testable without a corpus, a model or a YAML file.

The YAML reading here deliberately duplicates ``config.loader.load_yaml_mapping``
rather than importing it. Reusing it would create ``evaluation -> config``, and since
``processing -> config``, that edge is the first step toward the import direction
plan §3 forbids. The duplication is a few lines; the alternative costs this package
its single outward edge to ``contracts``. Do not "fix" it by importing the other one.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from pii_reduction.contracts.errors import PiiReductionError
from pii_reduction.evaluation.report import MetricRow

__all__ = [
    "DISPLAY_TOLERANCE",
    "Gate",
    "GateConfigurationError",
    "GateReport",
    "GateResult",
    "evaluate_gates",
    "load_gate_file",
]

#: Gate values are written at three decimals — the same precision the benchmark table
#: and the published documentation use — so "the gate file matches the published
#: numbers" is literally checkable. This tolerance is half of that last digit, which
#: keeps a floor of 1.000 from failing on floating-point representation while staying
#: far below any achievable regression: the smallest slice that carries a gate has 6
#: ground-truth entities, so one missed entity moves the metric by at least 0.16.
DISPLAY_TOLERANCE = 5e-4

#: Selector fields, in the order they appear in a rendered gate description.
SELECTORS = ("entity_type", "language", "document_type", "difficulty_tier")

_GATE_KEYS = frozenset(
    {"name", "metric", "min", "max", "support", *SELECTORS},
)
_FILE_KEYS = frozenset({"version", "measured", "gate_sets"})
_GATE_SET_KEYS = frozenset({"description", "gates"})

#: The gate file's schema version. Validated rather than merely recorded: a version
#: key nobody checks promises a forward compatibility the loader does not provide.
SUPPORTED_VERSION = 1


class GateConfigurationError(PiiReductionError):
    """A gate file is malformed, or a gate cannot be interpreted."""


@dataclass(frozen=True)
class Gate:
    """One bound on one metric at one slice.

    ``minimum``/``maximum`` are inclusive within :data:`DISPLAY_TOLERANCE`. At least
    one of them must be set — a gate with neither asserts nothing.

    Selectors default to ``"*"``, which is the aggregate row the benchmark emits for
    that dimension, not a wildcard: ``entity_type="*"`` selects the overall row, and
    ``entity_type="EMAIL"`` selects EMAIL's. This is deliberate. A wildcard would let
    one gate quietly cover a changing number of rows.
    """

    name: str
    metric: str
    entity_type: str = "*"
    language: str = "*"
    document_type: str = "*"
    difficulty_tier: str = "*"
    minimum: float | None = None
    maximum: float | None = None
    min_support: int | None = None

    def __post_init__(self) -> None:
        if self.minimum is None and self.maximum is None:
            raise GateConfigurationError(
                f"gate {self.name!r}: needs at least one of 'min' or 'max'; a gate with "
                "neither asserts nothing"
            )
        if self.minimum is not None and self.maximum is not None and self.minimum > self.maximum:
            raise GateConfigurationError(
                f"gate {self.name!r}: min {self.minimum} is above max {self.maximum}"
            )

    @property
    def slice_description(self) -> str:
        """The selected slice, naming only the dimensions that are not the aggregate."""
        parts = [
            f"{field}={getattr(self, field)}" for field in SELECTORS if getattr(self, field) != "*"
        ]
        return ", ".join(parts) if parts else "overall"

    @property
    def bound_description(self) -> str:
        bounds = []
        if self.minimum is not None:
            bounds.append(f">= {self.minimum:.3f}")
        if self.maximum is not None:
            bounds.append(f"<= {self.maximum:.3f}")
        return " and ".join(bounds)

    def selects(self, row: MetricRow) -> bool:
        return row.metric_name == self.metric and all(
            getattr(row, field) == getattr(self, field) for field in SELECTORS
        )


@dataclass(frozen=True)
class GateResult:
    """The outcome of checking one gate. ``passed`` is the only thing CI reads."""

    gate: Gate
    passed: bool
    reason: str
    observed: float | None = None
    support: int | None = None


@dataclass(frozen=True)
class GateReport:
    gate_set: str
    results: tuple[GateResult, ...]

    @property
    def failures(self) -> tuple[GateResult, ...]:
        return tuple(result for result in self.results if not result.passed)

    @property
    def passed(self) -> bool:
        return not self.failures

    def render(self) -> str:
        """Plain-text report; every gate is listed, passing ones included.

        Showing the passing gates is the point: it is how a reader confirms that the
        gate set actually ran, rather than trusting an empty failure list.
        """
        lines = [f"benchmark gates: {self.gate_set}", "=" * (len(self.gate_set) + 17)]
        for result in self.results:
            mark = "PASS" if result.passed else "FAIL"
            observed = "—" if result.observed is None else f"{result.observed:.3f}"
            support = "—" if result.support is None else str(result.support)
            lines.append(
                f"[{mark}] {result.gate.name}: {result.gate.metric} "
                f"({result.gate.slice_description}) = {observed} "
                f"support={support} · requires {result.gate.bound_description}"
            )
            if not result.passed:
                lines.append(f"       {result.reason}")
        failed = len(self.failures)
        lines.append("")
        lines.append(
            f"{len(self.results) - failed}/{len(self.results)} gates passed"
            + ("" if not failed else f" — {failed} FAILED")
        )
        return "\n".join(lines)


def evaluate_gates(
    rows: Sequence[MetricRow], gates: Iterable[Gate], *, gate_set: str
) -> GateReport:
    """Check every gate against the benchmark rows. Pure: no I/O, no globals."""
    results = [_evaluate_one(rows, gate) for gate in gates]
    if not results:
        raise GateConfigurationError(
            f"gate set {gate_set!r} contains no gates; an empty gate set would report "
            "success without checking anything"
        )
    return GateReport(gate_set=gate_set, results=tuple(results))


def _evaluate_one(rows: Sequence[MetricRow], gate: Gate) -> GateResult:
    selected = [row for row in rows if gate.selects(row)]

    if not selected:
        return GateResult(
            gate=gate,
            passed=False,
            reason=(
                f"no benchmark row matched metric {gate.metric!r} at "
                f"{gate.slice_description}. The metric or slice no longer exists, or the "
                "chain did not run — a gate that measures nothing is a failure, not a pass"
            ),
        )
    if len(selected) > 1:
        return GateResult(
            gate=gate,
            passed=False,
            reason=(
                f"{len(selected)} benchmark rows matched metric {gate.metric!r} at "
                f"{gate.slice_description}; a gate must identify exactly one row"
            ),
        )

    row = selected[0]
    observed, support = row.metric_value, row.support

    if gate.min_support is not None and support < gate.min_support:
        return GateResult(
            gate=gate,
            passed=False,
            observed=observed,
            support=support,
            reason=(
                f"support fell to {support} from the {gate.min_support} this gate was "
                "measured against; the floor is not comparable on a smaller slice"
            ),
        )
    if gate.minimum is not None and observed < gate.minimum - DISPLAY_TOLERANCE:
        return GateResult(
            gate=gate,
            passed=False,
            observed=observed,
            support=support,
            reason=f"{observed:.3f} is below the floor of {gate.minimum:.3f}",
        )
    if gate.maximum is not None and observed > gate.maximum + DISPLAY_TOLERANCE:
        return GateResult(
            gate=gate,
            passed=False,
            observed=observed,
            support=support,
            reason=f"{observed:.3f} is above the ceiling of {gate.maximum:.3f}",
        )
    return GateResult(
        gate=gate, passed=True, reason="within bounds", observed=observed, support=support
    )


def load_gate_file(path: Path, gate_set: str) -> tuple[Gate, ...]:
    """Load one named gate set from the versioned gate file.

    The file holds every chain's gates so that the comparison between chains stays in
    one reviewable place; the caller selects the set matching the chain it ran, which
    is what stops a hybrid-chain result being checked against deterministic floors.
    """
    if not path.is_file():
        raise GateConfigurationError(f"benchmark gate file not found: {path}")
    try:
        loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise GateConfigurationError(
            f"file {str(path)!r}: invalid YAML ({exc.__class__.__name__})"
        ) from exc
    if not isinstance(loaded, dict):
        raise GateConfigurationError(
            f"file {str(path)!r}: expected a YAML mapping at the top level, "
            f"got {type(loaded).__name__}"
        )

    # The same argument as `_parse_gate`'s unknown-key check, one level up: a
    # misspelled top-level key would otherwise be accepted in silence.
    _reject_unknown(loaded, _FILE_KEYS, context=f"file {str(path)!r}", what="top-level key")

    version = loaded.get("version")
    if version != SUPPORTED_VERSION:
        raise GateConfigurationError(
            f"file {str(path)!r}: gate file version {version!r} is not supported "
            f"(this build reads version {SUPPORTED_VERSION})"
        )

    sets = loaded.get("gate_sets")
    if not isinstance(sets, dict) or not sets:
        raise GateConfigurationError(f"file {str(path)!r}: no 'gate_sets' mapping")
    section = sets.get(gate_set)
    if section is None:
        raise GateConfigurationError(
            f"file {str(path)!r}: no gate set {gate_set!r} (defined: {', '.join(sorted(sets))})"
        )
    if not isinstance(section, dict):
        raise GateConfigurationError(
            f"file {str(path)!r}: gate set {gate_set!r} must be a mapping, "
            f"got {type(section).__name__}"
        )

    _reject_unknown(
        section,
        _GATE_SET_KEYS,
        context=f"file {str(path)!r}: gate set {gate_set!r}",
        what="key",
    )

    raw_gates = section.get("gates")
    if not isinstance(raw_gates, list) or not raw_gates:
        raise GateConfigurationError(f"file {str(path)!r}: gate set {gate_set!r} defines no gates")

    gates = tuple(
        _parse_gate(entry, path=path, gate_set=gate_set, index=index)
        for index, entry in enumerate(raw_gates)
    )
    names = [gate.name for gate in gates]
    duplicated = sorted({name for name in names if names.count(name) > 1})
    if duplicated:
        raise GateConfigurationError(
            f"file {str(path)!r}: gate set {gate_set!r} has duplicate gate names: "
            f"{', '.join(duplicated)}"
        )
    return gates


def _reject_unknown(
    mapping: dict[str, Any], allowed: frozenset[str], *, context: str, what: str
) -> None:
    unexpected = sorted(set(mapping) - allowed)
    if unexpected:
        raise GateConfigurationError(
            f"{context}: unknown {what}s {', '.join(unexpected)} "
            f"(allowed: {', '.join(sorted(allowed))})"
        )


def _parse_gate(entry: Any, *, path: Path, gate_set: str, index: int) -> Gate:
    context = f"file {str(path)!r}: gate set {gate_set!r} gate #{index}"
    if not isinstance(entry, dict):
        raise GateConfigurationError(f"{context}: expected a mapping, got {type(entry).__name__}")

    _reject_unknown(entry, _GATE_KEYS, context=context, what="key")
    for required in ("name", "metric"):
        if not isinstance(entry.get(required), str) or not entry[required]:
            raise GateConfigurationError(
                f"{context}: '{required}' is required and must be a string"
            )

    return Gate(
        name=entry["name"],
        metric=entry["metric"],
        entity_type=_selector(entry, "entity_type", context=context),
        language=_selector(entry, "language", context=context),
        document_type=_selector(entry, "document_type", context=context),
        difficulty_tier=_selector(entry, "difficulty_tier", context=context),
        minimum=_bound(entry, "min", context=context),
        maximum=_bound(entry, "max", context=context),
        min_support=_support(entry, context=context),
    )


def _selector(entry: dict[str, Any], key: str, *, context: str) -> str:
    value = entry.get(key, "*")
    # Tiers are written as bare integers in YAML but are strings in the report grain.
    if isinstance(value, int) and not isinstance(value, bool):
        return str(value)
    if not isinstance(value, str):
        raise GateConfigurationError(
            f"{context}: {key!r} must be a string, got {type(value).__name__}"
        )
    return value


def _bound(entry: dict[str, Any], key: str, *, context: str) -> float | None:
    value = entry.get(key)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise GateConfigurationError(f"{context}: {key!r} must be a number")
    return float(value)


def _support(entry: dict[str, Any], *, context: str) -> int | None:
    value = entry.get("support")
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise GateConfigurationError(f"{context}: 'support' must be an integer")
    return value
