"""Listing the files a template offers, when it offers a directory (ADR-0036).

**The whole point is that the caller still cannot name a source.** A template that
sets ``select_file`` declares a *directory* — a Unity Catalog volume path, or any
filesystem path — and the caller picks one file from what is in it. That is the same
shape as picking a column from a declared menu: the operator chose the place, the
caller chose from what the place contains.

This module is the only one in ``service/`` that reads a **data** directory rather
than the configuration directory, so the rules it enforces are written here rather
than assumed:

* **the name is a name, never a path** — no separator, no ``..``, no absolute form,
  no trailing dot and no reserved device name, the last two because Windows
  canonicalises them and a name that is checked must be the name that is opened;
* **the resolved file must be inside the declared directory**, checked after
  resolution rather than before, so a symlink cannot step outside it either;
* **the listing is one level deep** and filtered to the template's own source type,
  so it cannot become a way to walk a volume;
* **it never opens a file.** Names and nothing else — ADR-0026 forbids a preview
  endpoint, and this must not become one by accident.
"""

from __future__ import annotations

import re
from pathlib import Path, PurePath

from pii_reduction.config.registries import PATH_SOURCE_SUFFIXES
from pii_reduction.service.errors import InvalidRequestError
from pii_reduction.service.models import SOURCE_FILE_PATTERN

__all__ = ["list_offered_files", "resolve_offered_file"]

#: Compiled once. The pattern itself lives with the request contracts
#: (`models.SOURCE_FILE_PATTERN`), because that is where a reader looks for what a
#: request may contain; this module is where it is enforced on the way out as well.
_FILE_NAME_RE = re.compile(SOURCE_FILE_PATTERN)

#: Windows device names, which are **paths that are not files**.
#:
#: `COM1`, `NUL`, `CON` and friends pass the pattern above and resolve to something
#: inside the directory, so containment says yes — but opening one reaches a device
#: rather than a file: `NUL` is an empty stream, `COM1` is a serial port a read can
#: block on. Not a traversal and not a disclosure; a way to make a run behave
#: strangely, which is enough reason to refuse a name nobody legitimately wants.
#:
#: **Refused on every platform, not only Windows.** A configuration built on Linux may
#: be run on Windows and the reverse — the two must agree about what is acceptable, or
#: the answer depends on where the service happens to be deployed.
_WINDOWS_DEVICE_NAMES = frozenset(
    {"con", "prn", "aux", "nul"}
    | {f"com{digit}" for digit in "123456789"}
    | {f"lpt{digit}" for digit in "123456789"}
)


def _is_offerable_name(name: str, source_type: str) -> bool:
    """Whether this service will both list and accept ``name`` for this source type.

    **One predicate, used by the listing and by resolution**, so a picker cannot offer
    a name the builder would refuse — or, worse, accept one it never offered. An
    earlier draft filtered by suffix on the way out and not on the way back, which let
    a caller name a file the operator's directory happened to contain but the listing
    had deliberately withheld. That breaks ADR-0036's whole argument: "the caller chose
    from what the place contains" is only true if both directions agree.

    Beyond the pattern, three rules, each closing a *canonicalisation* gap rather than
    a traversal — those are where traversal bugs are born, because two spellings of one
    file mean the name that was checked is not the name that is opened.
    """
    # `fullmatch`, not `match`: see `models.SOURCE_FILE_PATTERN`. `$` would admit a trailing
    # newline here that pydantic's engine refuses, and the two must agree.
    if not _FILE_NAME_RE.fullmatch(name):
        return False
    # Windows strips a trailing dot when opening, so `report.csv.` opens `report.csv` —
    # two names, one file, and the listing would only ever show one of them.
    if name.endswith("."):
        return False
    if name.split(".")[0].lower() in _WINDOWS_DEVICE_NAMES:
        return False
    return PurePath(name).suffix.lower() in PATH_SOURCE_SUFFIXES.get(source_type, ())


def list_offered_files(directory: Path, source_type: str) -> tuple[str, ...]:
    """File names in ``directory`` this source type can read. Sorted, one level deep.

    A missing or unreadable directory answers **empty** rather than raising: an inbox
    that has not been created yet is an ordinary state on a workspace, and a 500
    naming a path would put an operator's directory in a response body. Whether the
    directory exists is the operator's problem, and `describe`/`run` say so with the
    real message when a run is attempted.
    """
    if not PATH_SOURCE_SUFFIXES.get(source_type):
        return ()

    def predicate(name: str) -> bool:
        return _is_offerable_name(name, source_type)

    try:
        entries = list(directory.iterdir())
    except OSError:
        return ()
    return tuple(
        sorted(entry.name for entry in entries if entry.is_file() and predicate(entry.name))
    )


def resolve_offered_file(directory: Path, name: str, source_type: str) -> Path:
    """The path for ``name`` inside ``directory``, or an actionable refusal.

    **The containment check is done after resolution, and that is the load-bearing
    part.** The pattern already rejects a separator, so `../etc/passwd` never gets
    here — but a *symlink* inside the directory has a name like any other, and only
    resolving both sides catches it pointing somewhere else.

    ``source_type`` is required rather than optional so that adding a caller of this
    function cannot accidentally skip the suffix rule, which is the one that keeps the
    offer and the acceptance the same set.
    """
    if not _is_offerable_name(name, source_type):
        offered = ", ".join(PATH_SOURCE_SUFFIXES.get(source_type, ())) or "(none)"
        raise InvalidRequestError(
            "source_file must be a plain file name this source type can read — no "
            "directory separator, no '..', no leading or trailing dot, not a reserved "
            f"device name, and one of: {offered}"
        )
    root = directory.resolve()
    candidate = (root / name).resolve()
    if not candidate.is_relative_to(root):
        # Reached only by a symlink, since the pattern excludes every textual route
        # out. The message names neither path: one of them came from a request, and
        # the other is the operator's.
        raise InvalidRequestError("source_file does not resolve inside the offered directory")
    return candidate
