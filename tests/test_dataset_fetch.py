"""Retrieval is only reproducible if it refuses everything that is not what we recorded.

ADR-0017 makes a recorded SHA-256 the mechanism behind Increment D's "reproducible from
documented commands". These tests are therefore mostly about refusals: a changed file, a
corrupted cache, a URL that is not https, a path that climbs out of the cache.

**Nothing here touches the network.** The transfer is exercised with a stubbed opener,
so CI stays offline and a HuggingFace outage cannot turn a push red.
"""

from __future__ import annotations

import hashlib
import io
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from pii_reduction.synthetic.errors import DatasetDownloadError
from pii_reduction.synthetic.fetch import RemoteFile, digest_of, fetch

pytestmark = pytest.mark.unit

PAYLOAD = b"instruction,response\nhello,hi there\n"
DIGEST = hashlib.sha256(PAYLOAD).hexdigest()
URL = "https://huggingface.co/datasets/example/corpus/resolve/" + "a" * 40 + "/data.csv"


def remote(**overrides: object) -> RemoteFile:
    fields: dict[str, object] = {
        "url": URL,
        "path": "example/corpus/data.csv",
        "sha256": DIGEST,
        "size_bytes": len(PAYLOAD),
    }
    fields.update(overrides)
    return RemoteFile(**fields)  # type: ignore[arg-type]


def stub_opener(payload: bytes):  # type: ignore[no-untyped-def]
    def opener(url: str, timeout: int = 0) -> io.BytesIO:
        return io.BytesIO(payload)

    return opener


class TestTheRecordIsValidated:
    def test_a_non_https_url_is_refused(self) -> None:
        # The URL is built from a text file. A fetcher that honoured any scheme in it
        # could be pointed at a local path or a plaintext host by an edit.
        with pytest.raises(DatasetDownloadError, match="must be https"):
            remote(url="http://huggingface.co/x")

    def test_a_digest_that_is_not_a_digest_is_refused(self) -> None:
        with pytest.raises(DatasetDownloadError, match="64 hex characters"):
            remote(sha256="not-a-digest")

    def test_a_zero_size_is_refused(self) -> None:
        with pytest.raises(DatasetDownloadError, match="must be positive"):
            remote(size_bytes=0)

    @pytest.mark.parametrize("path", ["/etc/passwd", "../../secrets", ""])
    def test_a_path_cannot_climb_out_of_the_cache(self, path: str) -> None:
        with pytest.raises(DatasetDownloadError, match="must be relative"):
            remote(path=path)

    def test_the_cache_path_keeps_the_whole_source_path(self, tmp_path: Path) -> None:
        # MASSIVE's German and Greek files are both named 0000.parquet. A cache keyed on
        # the base name would serve one language's text for the other.
        german = remote(path="massive/de-DE/validation/0000.parquet")
        greek = remote(path="massive/el-GR/validation/0000.parquet")
        assert german.cached_at(tmp_path) != greek.cached_at(tmp_path)


class TestTheCache:
    def test_a_matching_cached_file_is_returned_without_a_transfer(self, tmp_path: Path) -> None:
        target = remote().cached_at(tmp_path)
        target.parent.mkdir(parents=True)
        target.write_bytes(PAYLOAD)
        # allow_download=False proves no transfer was needed.
        assert fetch(remote(), cache_dir=tmp_path, allow_download=False) == target

    def test_a_corrupted_cache_entry_is_refused_and_left_alone(self, tmp_path: Path) -> None:
        """It is not silently re-downloaded, which is the whole point.

        A cache that repairs itself hides a truncated file and a tampered one equally
        well, and the second is the one that matters.
        """
        target = remote().cached_at(tmp_path)
        target.parent.mkdir(parents=True)
        target.write_bytes(PAYLOAD + b"tampered")

        with pytest.raises(DatasetDownloadError, match="Delete it and fetch again"):
            fetch(remote(), cache_dir=tmp_path)
        assert target.read_bytes() == PAYLOAD + b"tampered"

    def test_offline_says_what_is_missing(self, tmp_path: Path) -> None:
        with pytest.raises(DatasetDownloadError, match="downloading is disabled"):
            fetch(remote(), cache_dir=tmp_path, allow_download=False)


class TestTheTransfer:
    def test_a_good_download_lands_and_verifies(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(urllib.request, "urlopen", stub_opener(PAYLOAD))
        path = fetch(remote(), cache_dir=tmp_path)
        assert path.read_bytes() == PAYLOAD
        assert digest_of(path) == DIGEST
        assert not list(tmp_path.rglob("*.partial"))

    def test_a_changed_upstream_file_fails_loudly_and_leaves_nothing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # The failure ADR-0017 exists for: a "pinned" revision that no longer holds the
        # bytes a published number was measured on.
        monkeypatch.setattr(urllib.request, "urlopen", stub_opener(PAYLOAD + b"!"))
        with pytest.raises(DatasetDownloadError, match="re-record the retrieval block"):
            fetch(remote(), cache_dir=tmp_path)
        # The empty directory may stay; a half-written file must not, or the next run
        # would read it as a corrupt cache entry rather than as a failed transfer.
        assert not [path for path in tmp_path.rglob("*") if path.is_file()]

    def test_a_missing_revision_is_reported_as_such(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def raiser(url: str, timeout: int = 0) -> io.BytesIO:
            raise urllib.error.HTTPError(url, 404, "Not Found", {}, None)  # type: ignore[arg-type]

        monkeypatch.setattr(urllib.request, "urlopen", raiser)
        with pytest.raises(DatasetDownloadError, match="HTTP 404"):
            fetch(remote(), cache_dir=tmp_path)

    def test_a_dead_link_is_a_message_not_a_traceback(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def raiser(url: str, timeout: int = 0) -> io.BytesIO:
            raise urllib.error.URLError("no route to host")

        monkeypatch.setattr(urllib.request, "urlopen", raiser)
        with pytest.raises(DatasetDownloadError, match="could not retrieve"):
            fetch(remote(), cache_dir=tmp_path)
