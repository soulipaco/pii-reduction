"""Retrieve a public dataset file, and refuse anything that is not the file we recorded.

ADR-0017: public corpora are fetched as named files at a **pinned commit revision** and
checked against a SHA-256 held in ``demo/registry.yaml``, rather than through the
``datasets`` library. The whole mechanism is :mod:`urllib` plus :mod:`hashlib`, which is
the point — the alternative added ten transitive dependencies to fetch three files.

What the checksum buys is the Increment D exit criterion itself. "Reproducible from
documented commands" is a claim about bytes, and a recorded digest is the only form of
it the code can assert on every run: if upstream republishes a file, the build stops
and someone re-measures on purpose instead of a benchmark number quietly changing
meaning.

Two refusals are deliberate:

* **A cached file whose digest does not match is refused, never re-downloaded.**
  Re-fetching would make a truncated or tampered cache self-healing and invisible.
* **Only ``https://`` is accepted.** The URL comes out of a YAML file, so the fetcher
  must not be talkable into reading a local path or an unencrypted host by editing it.

Nothing here is reached by any test that touches the network: the logic is exercised
against ``file://`` URLs and temporary directories, so CI stays offline (ADR-0009).
"""

from __future__ import annotations

import hashlib
import shutil
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from pii_reduction.synthetic.errors import DatasetDownloadError

__all__ = [
    "CHUNK_BYTES",
    "DEFAULT_CACHE_DIR",
    "RemoteFile",
    "digest_of",
    "fetch",
]

#: Where downloads land. Already excluded by ``.gitignore`` — no raw data is ever
#: committed (``docs/02_PUBLIC_DATA_STRATEGY.md``).
DEFAULT_CACHE_DIR = Path("data/downloads")

CHUNK_BYTES = 1 << 20

_HEX = frozenset("0123456789abcdef")


@dataclass(frozen=True)
class RemoteFile:
    """One file of one dataset, identified by what it *is* rather than where it is.

    ``path`` is the repository-relative path inside the source dataset, and doubles as
    the path inside the cache. It has to: MASSIVE's German and Greek files are both
    named ``0000.parquet`` and differ only in their directory, so a cache keyed on the
    base name would serve one language's text for the other.
    """

    url: str
    path: str
    sha256: str
    size_bytes: int
    #: What this file is *for*, so a reader can select it without parsing the path —
    #: how the Greek half of MASSIVE is told from the German one.
    role: str = ""

    def __post_init__(self) -> None:
        if not self.url.startswith("https://"):
            raise DatasetDownloadError(
                f"file {self.path!r}: url must be https (got {self.url!r}). The registry "
                "is a text file; a fetcher that honoured any scheme in it could be "
                "pointed at a local path or a plaintext host by an edit (ADR-0017)"
            )
        digest = self.sha256.lower()
        if len(digest) != 64 or not set(digest) <= _HEX:
            raise DatasetDownloadError(
                f"file {self.path!r}: sha256 must be 64 hex characters, got {self.sha256!r}"
            )
        if self.size_bytes <= 0:
            raise DatasetDownloadError(
                f"file {self.path!r}: bytes must be positive, got {self.size_bytes}"
            )
        pure = PurePosixPath(self.path)
        if pure.is_absolute() or ".." in pure.parts or not self.path:
            raise DatasetDownloadError(
                f"file path {self.path!r} must be relative and must not climb out of the "
                "cache directory"
            )

    def cached_at(self, cache_dir: str | Path = DEFAULT_CACHE_DIR) -> Path:
        return Path(cache_dir).joinpath(*PurePosixPath(self.path).parts)


def digest_of(path: str | Path) -> str:
    """SHA-256 of a file, read in chunks so a large corpus is not held in memory."""
    hasher = hashlib.sha256()
    with Path(path).open("rb") as handle:
        while chunk := handle.read(CHUNK_BYTES):
            hasher.update(chunk)
    return hasher.hexdigest()


def fetch(
    remote: RemoteFile,
    *,
    cache_dir: str | Path = DEFAULT_CACHE_DIR,
    allow_download: bool = True,
) -> Path:
    """Return a local path holding exactly the recorded bytes, downloading if needed.

    ``allow_download=False`` turns this into a cache lookup, which is what a machine
    with no network — or a run that must prove it added nothing — should use.
    """
    target = remote.cached_at(cache_dir)
    if target.is_file():
        _verify(remote, target, cached=True)
        return target
    if not allow_download:
        raise DatasetDownloadError(
            f"file {remote.path!r} is not in the cache at {target} and downloading is "
            "disabled. Run the fetch without --offline, or point --cache at a "
            "directory that already holds it"
        )

    target.parent.mkdir(parents=True, exist_ok=True)
    # Downloaded beside the target and renamed on success, so an interrupted transfer
    # cannot leave a short file that later looks like a corrupt cache entry.
    partial = target.with_name(target.name + ".partial")
    try:
        with urllib.request.urlopen(remote.url, timeout=120) as response, partial.open("wb") as out:
            shutil.copyfileobj(response, out, CHUNK_BYTES)
    except urllib.error.HTTPError as error:
        partial.unlink(missing_ok=True)
        raise DatasetDownloadError(
            f"file {remote.path!r}: {remote.url} returned HTTP {error.code}. The pinned "
            "revision may have been removed upstream; check the retrieval block in the "
            "registry against the source repository"
        ) from error
    except OSError as error:
        # URLError is an OSError, and so is a full disk. Both are "the transfer did not
        # happen", and neither is worth a traceback in a CLI.
        partial.unlink(missing_ok=True)
        raise DatasetDownloadError(
            f"file {remote.path!r}: could not retrieve {remote.url} ({error.__class__.__name__})"
        ) from error

    _verify(remote, partial, cached=False)
    partial.replace(target)
    return target


def _verify(remote: RemoteFile, path: Path, *, cached: bool) -> None:
    """Size first, then digest — the cheap check names the common failure faster."""
    size = path.stat().st_size
    actual = digest_of(path)
    if size == remote.size_bytes and actual == remote.sha256.lower():
        return
    if not cached:
        path.unlink(missing_ok=True)
        raise DatasetDownloadError(
            f"file {remote.path!r}: downloaded {size} bytes with digest {actual}, "
            f"expected {remote.size_bytes} bytes and {remote.sha256}. The upstream file "
            "changed at a revision that was supposed to be immutable — re-record the "
            "retrieval block and re-measure any published number built from it"
        )
    raise DatasetDownloadError(
        f"file {remote.path!r}: the cached copy at {path} has digest {actual}, expected "
        f"{remote.sha256}. It is not re-downloaded automatically, because a cache that "
        "silently repairs itself hides both a corrupted file and a tampered one. "
        "Delete it and fetch again"
    )
