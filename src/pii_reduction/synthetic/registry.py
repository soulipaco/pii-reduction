"""The public-dataset registry, and the licence checks that make it binding.

``docs/02_PUBLIC_DATA_STRATEGY.md`` requires a registry entry per dataset recording
licence, provenance, redistribution and whether the source contains real PII. A file
nobody reads is documentation; this module makes it a gate, so a pack cannot be built
from a corpus whose licence was never checked.

Three refusals are deliberate and cannot be configured away:

* an **unknown dataset** — building from a corpus with no entry is exactly how an
  unlicensed source gets into a published benchmark;
* a **non-permissive licence** — the repository is MIT (ADR-0007), and a
  non-commercial corpus poisons everything derived from it, as
  ``el_core_news_lg`` already demonstrated for models;
* a source that **contains real PII** — injected ground truth would then sit beside
  real personal data, and the pack could not be published at all.

The registry deliberately also records what was *rejected*, so a later session does not
re-litigate a dataset that was already ruled out.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from pii_reduction.synthetic.errors import CorpusError, DatasetDownloadError
from pii_reduction.synthetic.fetch import RemoteFile

__all__ = [
    "ALLOWED_LICENCES",
    "DatasetEntry",
    "RetrievalSpec",
    "load_registry",
    "load_rejected",
    "require_publishable",
]

#: Where a ``huggingface`` retrieval block resolves its files from. Kept here rather
#: than in each entry so the registry records the *pin* — repository, revision, path,
#: digest — and not a URL somebody could edit into pointing somewhere else.
HUGGINGFACE_FILE_URL = "https://huggingface.co/datasets/{repository}/resolve/{revision}/{path}"

#: Licences a derived pack may carry given this repository is MIT (ADR-0007).
#: Named "allowed" rather than "permissive" on purpose: CDLA-Sharing-1.0 is
#: share-alike, so it is permitted but its obligation travels to anything built from
#: it, and the entry must set ``share_alike`` to say so.
ALLOWED_LICENCES = frozenset(
    {"MIT", "Apache-2.0", "BSD-3-Clause", "CC-BY-4.0", "CC0-1.0", "CDLA-Sharing-1.0"}
)

_REQUIRED_FIELDS = (
    "name",
    "source_url",
    "license",
    "redistribution_allowed",
    "contains_real_pii",
    "retrieval_method",
    "version",
    "document_type",
    "languages",
)

_KNOWN_RETRIEVAL = frozenset({"manual", "script", "huggingface", "kaggle", "other"})


@dataclass(frozen=True)
class RetrievalSpec:
    """How to obtain the dataset's files, pinned so that "the same source" means it.

    Held in the registry rather than in code because licence and provenance belong in
    one record: a session that bumps a revision must walk past ``license`` and
    ``contains_real_pii`` to do it (ADR-0017).
    """

    repository: str
    revision: str
    files: tuple[RemoteFile, ...]

    def file_for(self, role: str) -> RemoteFile:
        """The file playing ``role`` — how a reader picks the Greek half of MASSIVE."""
        for remote in self.files:
            if remote.role == role:
                return remote
        raise CorpusError(
            f"retrieval block has no file with role {role!r} "
            f"(roles: {', '.join(remote.role for remote in self.files) or 'none'})"
        )


@dataclass(frozen=True)
class DatasetEntry:
    """One registry entry. Every field here is a licence or provenance fact."""

    key: str
    name: str
    source_url: str
    license: str
    redistribution_allowed: bool
    contains_real_pii: bool | str
    retrieval_method: str
    version: str
    document_type: str
    languages: tuple[str, ...]
    difficulty_tier: int = 1
    share_alike: bool = False
    license_url: str = ""
    notes: str = ""
    #: The licence obligates attribution (CC BY and friends). Recorded so the obligation
    #: travels into a pack's meta rather than living only in a comment nobody reads when
    #: a pack is finally published.
    attribution_required: bool = False
    #: Optional at load time, required to fetch anything. Validating its shape here and
    #: its presence at the point of use keeps a registry that documents a manually
    #: obtained corpus legal, while still refusing to download from an unpinned entry.
    retrieval: RetrievalSpec | None = None

    def require_retrieval(self) -> RetrievalSpec:
        if self.retrieval is None:
            raise CorpusError(
                f"dataset {self.key!r}: retrieval_method is {self.retrieval_method!r} but "
                "the entry has no 'retrieval:' block, so there is nothing to download. "
                "Record repository, revision and one file per entry with its sha256 "
                "(ADR-0017)"
            )
        return self.retrieval

    @property
    def publishable(self) -> bool:
        """May a pack built from this be committed or published?"""
        return (
            self.redistribution_allowed
            and self.contains_real_pii is False
            and self.license in ALLOWED_LICENCES
        )


def load_registry(path: str | Path) -> dict[str, DatasetEntry]:
    """Load and validate every entry. A malformed registry fails here, not mid-build."""
    registry_path = Path(path)
    if not registry_path.is_file():
        raise CorpusError(f"dataset registry not found: {registry_path}")
    try:
        loaded = yaml.safe_load(registry_path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise CorpusError(
            f"file {str(registry_path)!r}: invalid YAML ({exc.__class__.__name__})"
        ) from exc
    if not isinstance(loaded, dict):
        raise CorpusError(f"file {str(registry_path)!r}: expected a mapping at the top level")

    datasets = loaded.get("datasets")
    if not isinstance(datasets, dict) or not datasets:
        raise CorpusError(f"file {str(registry_path)!r}: no 'datasets' mapping")

    return {key: _entry(key, value, path=registry_path) for key, value in datasets.items()}


def _entry(key: str, raw: Any, *, path: Path) -> DatasetEntry:
    context = f"file {str(path)!r}: dataset {key!r}"
    if not isinstance(raw, dict):
        raise CorpusError(f"{context}: expected a mapping, got {type(raw).__name__}")

    missing = [field for field in _REQUIRED_FIELDS if field not in raw]
    if missing:
        raise CorpusError(
            f"{context}: missing required field(s) {', '.join(missing)}. "
            "docs/02_PUBLIC_DATA_STRATEGY.md requires the full provenance record"
        )
    if raw["retrieval_method"] not in _KNOWN_RETRIEVAL:
        raise CorpusError(
            f"{context}: retrieval_method {raw['retrieval_method']!r} is not one of "
            f"{', '.join(sorted(_KNOWN_RETRIEVAL))}"
        )
    languages = raw["languages"]
    if not isinstance(languages, list) or not languages:
        raise CorpusError(f"{context}: 'languages' must be a non-empty list")
    if raw["license"] not in ALLOWED_LICENCES:
        raise CorpusError(
            f"{context}: licence {raw['license']!r} is not on the permitted list "
            f"({', '.join(sorted(ALLOWED_LICENCES))}). This repository is MIT "
            "(ADR-0007); a restrictive source licence travels to everything built "
            "from it. Record it under 'rejected:' with the reason instead"
        )

    return DatasetEntry(
        key=key,
        name=str(raw["name"]),
        source_url=str(raw["source_url"]),
        license=str(raw["license"]),
        redistribution_allowed=_strict_bool(raw, "redistribution_allowed", context=context),
        contains_real_pii=raw["contains_real_pii"],
        retrieval_method=str(raw["retrieval_method"]),
        version=str(raw["version"]),
        document_type=str(raw["document_type"]),
        languages=tuple(str(language) for language in languages),
        difficulty_tier=int(raw.get("difficulty_tier", 1)),
        share_alike=_strict_bool(raw, "share_alike", context=context, default=False),
        license_url=str(raw.get("license_url", "")),
        notes=str(raw.get("notes", "")),
        attribution_required=_strict_bool(
            raw, "attribution_required", context=context, default=False
        ),
        retrieval=_retrieval(
            raw.get("retrieval"), method=str(raw["retrieval_method"]), context=context
        ),
    )


def _retrieval(raw: Any, *, method: str, context: str) -> RetrievalSpec | None:
    """Parse and pin-check a ``retrieval:`` block (ADR-0017).

    The revision must be a full 40-character commit hash. A branch name would look
    like a pin and behave like a moving target — which is exactly the failure the
    checksums exist to catch, discovered a download too late.
    """
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise CorpusError(f"{context}: 'retrieval' must be a mapping, got {type(raw).__name__}")
    if method != "huggingface":
        # The block resolves to a huggingface.co URL. Accepting it under another method
        # would point the fetcher at the wrong host and report the resulting 404 as
        # "the pinned revision may have been removed upstream", which is the kind of
        # quiet wrongness this module exists to eliminate.
        raise CorpusError(
            f"{context}: a 'retrieval' block is only understood for "
            f"retrieval_method 'huggingface', not {method!r}. A dataset obtained another "
            "way records how in 'notes' and is fetched by hand"
        )

    missing = [field for field in ("repository", "revision", "files") if field not in raw]
    if missing:
        raise CorpusError(f"{context}: retrieval is missing {', '.join(missing)}")

    repository = str(raw["repository"])
    revision = str(raw["revision"])
    if len(revision) != 40 or not set(revision.lower()) <= frozenset("0123456789abcdef"):
        raise CorpusError(
            f"{context}: retrieval revision {revision!r} is not a full commit hash. A "
            "branch or tag can move, and a pack rebuilt from a moved source is not the "
            "pack whose numbers were published (ADR-0017)"
        )

    files = raw["files"]
    if not isinstance(files, list) or not files:
        raise CorpusError(f"{context}: retrieval 'files' must be a non-empty list")

    remotes: list[RemoteFile] = []
    roles: list[str] = []
    for entry in files:
        if not isinstance(entry, dict):
            raise CorpusError(f"{context}: each retrieval file must be a mapping")
        absent = [field for field in ("path", "sha256", "bytes", "role") if field not in entry]
        if absent:
            raise CorpusError(
                f"{context}: retrieval file {entry.get('path', '?')!r} is missing "
                f"{', '.join(absent)}"
            )
        path = str(entry["path"])
        try:
            remotes.append(
                RemoteFile(
                    url=HUGGINGFACE_FILE_URL.format(
                        repository=repository, revision=revision, path=path
                    ),
                    path=f"{repository}/{path}",
                    sha256=str(entry["sha256"]),
                    size_bytes=int(entry["bytes"]),
                    role=str(entry["role"]),
                )
            )
        except DatasetDownloadError as error:
            # A malformed entry is a bad *registry*, not a failed download. Reported as
            # the former, with the file that caused it, so the fault is not misattributed
            # to a transfer that never started.
            raise CorpusError(f"{context}: {error}") from error
        roles.append(str(entry["role"]))

    if len(set(roles)) != len(roles):
        raise CorpusError(
            f"{context}: retrieval roles must be distinct, got {', '.join(roles)}. A "
            "reader selects its file by role, so a duplicate silently hands it the "
            "wrong one"
        )
    return RetrievalSpec(repository=repository, revision=revision, files=tuple(remotes))


def load_rejected(path: str | Path) -> dict[str, str]:
    """Datasets ruled out, mapped to the reason. Documentation the code can read.

    ``require_publishable`` consults it so a rejected key is answered with *why* rather
    than with "unknown dataset" — the difference between a decision and an oversight,
    and the difference between a session that respects it and one that re-litigates it.
    """
    loaded = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    rejected = loaded.get("rejected") if isinstance(loaded, dict) else None
    if not isinstance(rejected, dict):
        return {}
    return {
        key: str(value.get("reason", "")).strip() if isinstance(value, dict) else ""
        for key, value in rejected.items()
    }


def _strict_bool(
    raw: dict[str, Any], key: str, *, context: str, default: bool | None = None
) -> bool:
    """Refuse anything that is not literally true or false.

    ``bool("unknown")`` is ``True``, and ``docs/02_PUBLIC_DATA_STRATEGY.md`` documents
    ``unknown`` as a legal value for ``redistribution_allowed`` — so a coercing read
    turns the one value meaning "nobody checked" into "yes, publish it". The same
    applies to ``share_alike``, where a typo would silently mark a share-alike source
    as free of obligations.
    """
    if key not in raw and default is not None:
        return default
    value = raw.get(key)
    if value is not True and value is not False:
        raise CorpusError(
            f"{context}: {key!r} must be true or false, got {value!r}. "
            "'unknown' is not a licence to publish — record the dataset under "
            "'rejected:' until someone establishes the answer"
        )
    return value


def require_publishable(key: str, *, path: str | Path) -> DatasetEntry:
    """Return the entry for ``key``, refusing anything a pack may not be built from.

    The refusal is the point. Every reason below is one that cannot be fixed by trying
    again, so failing at the point of use — rather than after a download and an
    injection run — is what keeps an unlicensed corpus out of a published benchmark.
    """
    registry = load_registry(path)
    entry = registry.get(key)
    if entry is None:
        rejected = load_rejected(path)
        if key in rejected:
            raise CorpusError(
                f"dataset {key!r} was examined and rejected, not overlooked. Recorded "
                f"reason: {' '.join(rejected[key].split())[:400]}"
            )
        raise CorpusError(
            f"dataset {key!r} has no registry entry (known: {', '.join(sorted(registry))}). "
            "docs/02_PUBLIC_DATA_STRATEGY.md requires licence and provenance to be "
            "recorded before a dataset is used"
        )
    if entry.contains_real_pii is not False:
        raise CorpusError(
            f"dataset {key!r}: contains_real_pii is {entry.contains_real_pii!r}. A pack "
            "may not be built from a source carrying real personal data, whatever its "
            "licence says"
        )
    if not entry.redistribution_allowed:
        raise CorpusError(
            f"dataset {key!r}: redistribution is not permitted, so a derived pack "
            "cannot be published. Measure it locally or choose another source"
        )
    return entry
