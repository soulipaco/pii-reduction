"""ADR-0033: batching changes throughput and nothing else.

The shared provider contract already asserts `detect_batch` equals per-text `detect`
for three short strings (`tests/provider_contract.py`). That is the right place for the
*contract*, and it is nowhere near enough evidence for the *implementation*: the
Presidio adapter's batch path runs a different Presidio API, and the failure mode worth
fearing is a span that shifts on text nobody wrote a fixture for.

So the identity assertion is repeated here **over every processable segment of all
three committed corpora**, in all three languages, through the two configured Presidio
instances — including the Greek one, whose promotion (ADR-0020), left extension
(ADR-0021) and markup clip (ADR-0027) are exactly the post-processing a second code
path could drift from.

Integration tier: it needs the models. The default-tier half below needs none and
covers the base class's own batching rules.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from pii_reduction.contracts.entities import EntityMatch
from pii_reduction.parsers.plain_text import PlainTextParser
from pii_reduction.parsers.transcript import TranscriptParser
from pii_reduction.providers.base import BaseProvider
from pii_reduction.providers.errors import ProviderError

REPO_ROOT = Path(__file__).resolve().parents[1]
CORPORA = ("corpus", "incidents", "markup")
SCOPE = frozenset({"PERSON", "EMAIL", "PHONE"})


def corpus_segments() -> list[tuple[str, str]]:
    """`(language, segment text)` for every processable segment of every corpus.

    The parsers are the ones each corpus's dataset config names, so these are the
    exact strings the pipeline hands a provider — not a sample of the source text.
    """
    parsers = {"plain": PlainTextParser(), "transcript": TranscriptParser()}
    segments: list[tuple[str, str]] = []
    for corpus in CORPORA:
        frame = pd.read_csv(REPO_ROOT / "tests" / "fixtures" / corpus / "corpus.csv")
        for document_type, parser in parsers.items():
            for _, row in frame[frame["document_type"] == document_type].iterrows():
                segments.extend(
                    (str(row["language"]), segment.text)
                    for segment in parser.parse(str(row["text"])).processable_segments
                    if segment.text
                )
    return segments


class CountingProvider(BaseProvider):
    """A provider with no models, recording how it was called."""

    name = "counting"

    def __init__(self) -> None:
        self.scalar_calls = 0
        self.batch_calls = 0
        self.batch_sizes: list[int] = []

    def supported_entities(self) -> frozenset[str]:
        return frozenset({"PERSON"})

    def _detect(self, text, *, language, entities):  # type: ignore[no-untyped-def]
        self.scalar_calls += 1
        index = text.find("Ada")
        if index < 0:
            return []
        return [
            EntityMatch(
                start=index,
                end=index + 3,
                entity_type="PERSON",
                score=0.9,
                provider=self.name,
                language=language,
            )
        ]

    def _detect_batch(self, texts, *, languages, entities):  # type: ignore[no-untyped-def]
        self.batch_calls += 1
        self.batch_sizes.append(len(texts))
        return super()._detect_batch(texts, languages=languages, entities=entities)


class TestTheBaseClassRules:
    """What `detect_batch` guarantees regardless of whether a provider batches."""

    def test_an_empty_text_never_reaches_the_batch(self) -> None:
        """It short-circuits in `detect` too, and the two must not disagree.

        A provider's batch API is entitled to its own opinion about a zero-length
        document; dropping empties before the call is what stops that opinion from
        becoming a difference between the two entry points.
        """
        provider = CountingProvider()
        results = provider.detect_batch(["Ada called.", "", "no name"], languages=[None] * 3)
        assert provider.batch_sizes == [2]
        assert [len(found) for found in results] == [1, 0, 0]

    def test_results_come_back_in_the_order_they_went_in(self) -> None:
        provider = CountingProvider()
        texts = ["", "Ada called.", "", "nothing", "Ada again"]
        assert provider.detect_batch(texts, languages=[None] * 5) == [
            provider.detect(text) for text in texts
        ]

    def test_an_empty_scope_asks_the_provider_nothing(self) -> None:
        provider = CountingProvider()
        assert provider.detect_batch(["Ada called."], entities=frozenset()) == [[]]
        assert (provider.batch_calls, provider.scalar_calls) == (0, 0)

    def test_a_non_string_is_refused_the_same_way_detect_refuses_it(self) -> None:
        provider = CountingProvider()
        with pytest.raises(ProviderError, match="requires str"):
            provider.detect_batch(["fine", None])  # type: ignore[list-item]
        with pytest.raises(ProviderError, match="requires str"):
            provider.detect(None)  # type: ignore[arg-type]

    def test_a_provider_returning_the_wrong_number_of_results_is_an_error(self) -> None:
        class Truncating(CountingProvider):
            def _detect_batch(self, texts, *, languages, entities):  # type: ignore[no-untyped-def]
                return []

        with pytest.raises(ProviderError, match="_detect_batch returned"):
            Truncating().detect_batch(["Ada called.", "Ada again"])

    def test_the_default_implementation_is_still_one_call_per_text(self) -> None:
        """A provider with no batch path must not be made slower or different by this."""
        provider = CountingProvider()
        provider.detect_batch(["Ada called.", "Ada again", "nothing"], languages=[None] * 3)
        assert provider.scalar_calls == 3


class TestTheRepairChainIsReachableFromTheBatch:
    """ADR-0033's structural claim, pinned directly and without models.

    Everything else here compares `detect_batch` against `detect`, which would still
    pass if `_finalize` stopped being applied on *both* paths. This asserts the repair
    actually happens on the batch path: a raw span crossing a line break comes back
    split (ADR-0016), which only `_finalize` does.
    """

    class Sloppy(BaseProvider):
        """Returns one raw span straight across a line break, as a real model would."""

        name = "sloppy"

        def supported_entities(self) -> frozenset[str]:
            return frozenset({"PERSON"})

        def _detect(self, text, *, language, entities):  # type: ignore[no-untyped-def]
            return [
                EntityMatch(
                    start=0,
                    end=len(text),
                    entity_type="PERSON",
                    score=0.9,
                    provider=self.name,
                    language=language,
                )
            ]

    TEXT = "Ada Okonkwo\nMobile"

    def test_a_span_crossing_a_line_break_is_split_on_the_batch_path(self) -> None:
        provider = self.Sloppy()
        (batched,) = provider.detect_batch([self.TEXT])
        assert [(match.start, match.end) for match in batched] == [(0, 11), (12, 18)]
        assert batched == provider.detect(self.TEXT)

    def test_a_span_past_the_end_is_refused_on_the_batch_path_too(self) -> None:
        """`_validate` runs before any repair, on both entry points."""

        class Overrunning(TestTheRepairChainIsReachableFromTheBatch.Sloppy):
            def _detect(self, text, *, language, entities):  # type: ignore[no-untyped-def]
                return [
                    EntityMatch(
                        start=0,
                        end=len(text) + 5,
                        entity_type="PERSON",
                        score=0.9,
                        provider=self.name,
                        language=language,
                    )
                ]

        with pytest.raises(ProviderError):
            Overrunning().detect_batch(["Ada Okonkwo"])


@pytest.mark.integration
class TestPresidioBatchingIsOutputIdentical:
    """The assertion ADR-0033 rests on, over real text and the shipped instances."""

    @staticmethod
    def _instances() -> tuple[tuple[BaseProvider, set[str]], tuple[BaseProvider, set[str]]]:
        from pii_reduction.providers.presidio_provider import PresidioProvider

        latin = PresidioProvider({"models": {"en": "en_core_web_md", "de": "de_core_news_md"}})
        greek = PresidioProvider(
            {
                "models": {"el": "xx_ent_wiki_sm"},
                "promote": ["LOCATION", "ORGANIZATION"],
                "extend_person_left": True,
            }
        )
        return (latin, {"en", "de"}), (greek, {"el"})

    def test_every_segment_of_every_corpus_detects_the_same_either_way(self) -> None:
        segments = corpus_segments()
        assert len(segments) > 300, "the corpora shrank; this test is no longer evidence"
        for provider, languages in self._instances():
            selected = [(language, text) for language, text in segments if language in languages]
            assert selected, f"no segments for {sorted(languages)}"
            scalar = [
                provider.detect(text, language=language, entities=SCOPE)
                for language, text in selected
            ]
            batched = provider.detect_batch(
                [text for _, text in selected],
                languages=[language for language, _ in selected],
                entities=SCOPE,
            )
            assert batched == scalar

    def test_a_mixed_language_batch_answers_per_text(self) -> None:
        """`analyze_iterator` takes one language per call, so the adapter groups.

        The shipped pipeline never sends a mixed batch — a row's language is resolved
        once, before any segment is detected — but the contract allows one, and a
        language this instance does not serve must yield an empty list rather than
        borrow its neighbour's model.
        """
        segments = corpus_segments()
        (latin, _), _ = self._instances()
        batched = latin.detect_batch(
            [text for _, text in segments],
            languages=[language for language, _ in segments],
            entities=SCOPE,
        )
        scalar = [
            latin.detect(text, language=language, entities=SCOPE) for language, text in segments
        ]
        assert batched == scalar
        greek_positions = [
            index for index, (language, _) in enumerate(segments) if language == "el"
        ]
        assert greek_positions, "the corpora no longer contain Greek"
        assert all(batched[index] == [] for index in greek_positions)
