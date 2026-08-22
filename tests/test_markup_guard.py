"""ADR-0027: markup is machine syntax, and a detected span must be clipped out of it.

Default tier. Both halves of the remedy are pure text arithmetic with no model behind
them, so they are checked on every push: the **guard** at the provider boundary
(`providers/base.py`) and the **check** over the written output
(`processing/fidelity.py`).

The failure class this exists for is the one no other check in this repository can
see. The parser/reconstructor contract makes everything *outside* a processable
segment structurally unreachable; a ServiceNow note body holding quoted HTML is
correctly offered for scanning, and a model returning ``code]<div`` as a PERSON at the
same 0.85 a real name gets destroys the tag entirely within that guarantee. The
over-redaction gate cannot see it either — a tag is not a protected token.

Every fixture below is invented. No text here comes from any real corpus.
"""

from __future__ import annotations

import ast
from dataclasses import replace
from pathlib import Path

import pytest

from pii_reduction.contracts.entities import EntityMatch
from pii_reduction.entities.taxonomy import (
    ADDRESS,
    EMAIL,
    PERSON,
    PHONE,
    markup_guarded_labels,
)
from pii_reduction.patterns import (
    MARKUP_HINT_PATTERN,
    markup_free_fragments,
    markup_regions,
)
from pii_reduction.processing.fidelity import markup_losses, markup_tag_counts
from pii_reduction.providers.base import BaseProvider

pytestmark = pytest.mark.unit

ZERO_WIDTH = "​"

#: Derived from this file, not from the working directory: the independence assertion
#: below is the point of ADR-0027's second half, and it must not depend on where
#: pytest was invoked from.
PACKAGE_DIR = Path(__file__).resolve().parents[1] / "src" / "pii_reduction"


class _SpanProvider(BaseProvider):
    """Returns exactly the spans it was handed, so the repair is what is under test."""

    name = "span_source"

    def __init__(self, spans: list[tuple[str, int, int]]) -> None:
        self._spans = spans

    def supported_entities(self) -> frozenset[str]:
        # ADDRESS is included although no shipped provider emits it (ADR-0002): it is
        # in `MARKUP_GUARDED_ENTITIES`, and its surface is the one guarded surface that
        # is legitimately digit-only, which the plausibility rules have to respect.
        return frozenset({PERSON, EMAIL, PHONE, ADDRESS})

    def _detect(
        self, text: str, *, language: str | None, entities: frozenset[str]
    ) -> list[EntityMatch]:
        return [
            EntityMatch(start=start, end=end, entity_type=label, provider=self.name, score=0.85)
            for label, start, end in self._spans
            if label in entities
        ]


def surfaces(text: str, label: str, start: int, end: int) -> list[str]:
    provider = _SpanProvider([(label, start, end)])
    return [text[m.start : m.end] for m in provider.detect(text, entities=(label,))]


def whole(text: str, label: str = PERSON) -> list[str]:
    return surfaces(text, label, 0, len(text))


class TestMarkupRegions:
    """What counts as machine syntax. Bounded on purpose — a stray bracket in prose
    must not swallow a paragraph, and every alternation is newline-free so a scan of
    one line is exactly a scan of the whole text."""

    def test_html_and_bbcode_tags(self) -> None:
        text = "[code]<div class='x'>Grace Okafor</div>[/code]"
        found = [text[start:end] for start, end in markup_regions(text)]
        assert found == ["[code]<div class='x'>", "</div>[/code]"]

    def test_urls_and_entities_and_zero_width(self) -> None:
        text = f"see https://example.test/a?b=1 and &nbsp; and{ZERO_WIDTH}here"
        found = [text[start:end] for start, end in markup_regions(text)]
        assert found == ["https://example.test/a?b=1", "&nbsp;", ZERO_WIDTH]

    def test_ordinary_prose_has_no_regions(self) -> None:
        assert markup_regions("Grace Okafor called from +30 210 000 0000 about INC00128492.") == []

    def test_a_bracketed_timestamp_prefix_is_not_markup(self) -> None:
        # A transcript prefix is structure the *parser* owns. Reading it as markup here
        # would be a second, competing opinion about the same characters.
        assert markup_regions("[07:04] Agent: hello") == []

    def test_a_lone_angle_bracket_is_not_a_tag(self) -> None:
        assert markup_regions("profit < loss, and 3 > 2") == []

    def test_fragments_of_a_span_that_lies_wholly_inside_markup_are_empty(self) -> None:
        text = "<div class='alpha'>"
        assert markup_free_fragments(1, 4, markup_regions(text)) == []

    @pytest.mark.parametrize(
        "sample",
        [
            "<div class='x'>",
            "</p>",
            "[code]",
            "[/quote]",
            "[color=red]",
            "https://example.test/a",
            "www.example.test",
            "&nbsp;",
            "&#8203;",
            ZERO_WIDTH,
        ],
    )
    def test_the_cheap_hint_fires_on_everything_the_pattern_can_match(self, sample: str) -> None:
        """`markup_regions` returns nothing when the hint misses, so a new alternation
        added without a matching hint character turns the whole guard into a silent
        no-op with no test failing. This is that test."""
        assert MARKUP_HINT_PATTERN.search(sample), sample
        assert markup_regions(sample), sample


class TestTheGuardClips:
    def test_a_name_beside_a_closing_tag_still_loses_the_name(self) -> None:
        text = "<p>Grace Okafor</p>"
        assert whole(text) == ["Grace Okafor"]

    def test_a_span_lying_wholly_inside_markup_is_dropped(self) -> None:
        # The measured shape: the model reads "[code]<div" as a person's name.
        text = "[code]<div class='x'>note body"
        assert surfaces(text, PERSON, 0, text.index(" class")) == []

    def test_both_halves_of_a_name_split_by_a_tag_are_kept(self) -> None:
        # Same reasoning as the line-bounded split: keeping the longer half alone
        # leaves the other half in the output, and `leakage_rate` cannot see it.
        text = "Jürgen<br>Müller"
        assert whole(text) == ["Jürgen", "Müller"]

    def test_a_url_is_not_damaged(self) -> None:
        # The measured transcript shape: the model tags the link and the following
        # name as one span, and reduction eats the URL's leading characters.
        text = "Profile https://intranet.test/u/1 Grace Okafor"
        assert surfaces(text, PERSON, text.index("https"), len(text)) == ["Grace Okafor"]

    def test_a_clipped_fragment_loses_the_joiner_it_hung_on(self) -> None:
        text = "<a href='mailto:'>Grace Okafor</a>"
        assert whole(text) == ["Grace Okafor"]

    def test_a_tag_name_left_behind_is_not_redacted(self) -> None:
        # Once the angle brackets are clipped away a model reads `div` as a proper
        # noun. Nobody is named div.
        text = "<div>" + ZERO_WIDTH + "</div>"
        assert surfaces(text, PERSON, 1, 4) == []

    def test_an_emoticon_is_not_a_name(self) -> None:
        text = "<p>:)</p>"
        assert surfaces(text, PERSON, 3, 5) == []

    def test_a_real_surname_that_collides_with_a_tag_name_survives_untouched(self) -> None:
        # The vocabulary holds attribute names as well as tags, and several of them
        # are real surnames. It is consulted only for a span the clip shortened, so an
        # untouched one-word name in a markup-bearing cell is never dropped — dropping
        # it would be a leak, which is the error this guard must not commit.
        for surname in ("Small", "Link", "Name"):
            text = f"<p>{surname} called back</p>"
            start = text.index(surname)
            assert surfaces(text, PERSON, start, start + len(surname)) == [surname]


class TestTheGuardRefuses:
    """Where clipping would cost more than it buys."""

    def test_email_is_exempt_because_dropping_one_would_leak(self) -> None:
        # A string matching the email grammar is an email whatever sits beside it, and
        # the guard must never be the reason an address survives.
        text = "<td>grace.okafor@example.com</td>"
        assert whole(text, EMAIL) == [text]

    def test_phone_is_exempt_for_the_same_reason(self) -> None:
        text = "<td>+30 210 000 0000</td>"
        assert whole(text, PHONE) == [text]

    def test_the_exempt_set_is_derived_from_the_taxonomy(self) -> None:
        # Restating it in the provider layer is how the two definitions drift.
        assert markup_guarded_labels() == frozenset({PERSON, ADDRESS})

    def test_markup_free_text_is_returned_untouched(self) -> None:
        # The property that lets this ship on by default: on a corpus with no markup
        # the guard cannot move a published number, because it never fires.
        text = "Grace Okafor called about INC00128492."
        assert whole(text) == [text]

    def test_a_name_containing_a_stray_ampersand_word_survives(self) -> None:
        text = "Marks & Okafor"
        assert whole(text) == [text]


class TestTheGuardNeverLeaks:
    """The privacy audit of this increment found the guard leaking, and these are the
    cases it found. A guard against over-redaction that causes under-redaction has
    made the trade backwards."""

    def test_a_bracketed_display_name_is_not_a_tag(self) -> None:
        # Chat exports write `<display name>` at line start. Reading that as a tag made
        # the span "wholly inside markup" and discarded it — the name went out clean.
        text = "<Grace Okafor> please call"
        assert markup_regions(text) == []
        assert surfaces(text, PERSON, 1, 13) == ["Grace Okafor"]

    def test_an_unknown_tag_dialect_is_not_a_tag_either(self) -> None:
        # The cost of requiring a known element name, stated: an unknown dialect loses
        # its protection from over-redaction. That is the trade this project makes
        # everywhere else — the visible error over the invisible one.
        assert markup_regions("<custom-widget>x</custom-widget>") == []

    def test_a_name_inside_a_url_path_is_still_redacted(self) -> None:
        # Clipping leaves nothing here, and dropping the span would leak the name.
        # Redacting it damages the URL instead, which is the visible error.
        text = "Profile https://intranet.test/u/Grace.Okafor here"
        start = text.index("Grace.Okafor")
        provider = _SpanProvider([(PERSON, start, start + len("Grace.Okafor"))])
        assert [text[m.start : m.end] for m in provider.detect(text, entities=(PERSON,))] == [
            "Grace.Okafor"
        ]
        assert provider.drop_counter.as_dict() == {"span_source:markup_kept_inside_region": 1}

    def test_a_quoted_surname_in_a_cell_that_holds_a_url_survives(self) -> None:
        # Found by the architecture review: the edge trim ran *before* the "did the
        # clip shorten this?" test, so trimming the quotes counted as clipping and
        # re-opened the tag vocabulary to a span markup never touched.
        text = '<p>"Small" called back</p>'
        assert surfaces(text, PERSON, 3, 10) == ["Small"]

    def test_a_digit_only_span_outside_the_markup_survives(self) -> None:
        # The letter-count test is a statement about names. An ADDRESS surface is
        # legitimately digit-only, and ADDRESS is guarded too.
        text = "Deliver to 10-12 see http://example.test/a"
        assert surfaces(text, ADDRESS, 11, 16) == ["10-12"]

    def test_a_surface_that_is_itself_syntax_is_still_dropped(self) -> None:
        # The measured failure the guard was built for must keep failing closed.
        text = "[code]<div class='x'>note"
        assert surfaces(text, PERSON, 0, text.index(" class")) == []


class TestTheClipRunsLast:
    """The ADR-0021 extension widens a span leftward over one capitalised token, and a
    token can end in a tag. Clipping before the extension would be undone by it."""

    def test_the_extension_cannot_widen_a_span_back_into_a_tag(self) -> None:
        text = "Γιώργος</b> Δημητρίου"
        provider = _SpanProvider([(PERSON, text.index("Δημητρίου"), len(text))])
        provider.extend_person_left = True
        surviving = [text[m.start : m.end] for m in provider.detect(text, entities=(PERSON,))]
        # No span may contain the tag, whatever the extension did. Widening across it
        # produces two clipped fragments rather than one span swallowing `</b>`, which
        # is over-redaction of a neighbouring token — ADR-0021's accepted visible
        # error — instead of structural damage, which is not.
        assert all("<" not in surface and ">" not in surface for surface in surviving)
        assert "Δημητρίου" in surviving


class TestTheGuardIsCounted:
    """A repair nobody can see is a coverage change nobody can notice (ADR-0004's
    argument for the drop counter, applied to spans)."""

    def test_a_clip_is_recorded(self) -> None:
        text = "<p>Grace Okafor</p>"
        provider = _SpanProvider([(PERSON, 0, len(text))])
        provider.detect(text, entities=(PERSON,))
        assert provider.drop_counter.as_dict() == {"span_source:markup_clipped": 1}

    def test_a_drop_is_recorded_separately(self) -> None:
        text = "[code]<div class='x'>body"
        provider = _SpanProvider([(PERSON, 0, text.index(" class"))])
        provider.detect(text, entities=(PERSON,))
        assert provider.drop_counter.as_dict() == {"span_source:markup_dropped": 1}


class TestTheOutputCheck:
    """The independent half. It must catch damage the guard did not prevent, and it
    must never fire on a correct redaction."""

    def test_a_destroyed_tag_is_counted(self) -> None:
        loss = markup_losses(["<p>Grace Okafor</p>"], ["<PERSON></p>"])
        assert (loss.rows, loss.tags) == (1, 1)

    def test_a_correct_redaction_is_not_a_loss(self) -> None:
        loss = markup_losses(["<p>Grace Okafor</p>"], ["<p><PERSON></p>"])
        assert not loss

    def test_a_name_redacted_inside_an_attribute_is_not_a_loss(self) -> None:
        # Stripping replacement labels from both sides is what keeps this symmetric.
        loss = markup_losses(["<a title='Peter Novak'>x</a>"], ["<a title='<PERSON>'>x</a>"])
        assert not loss

    def test_an_rfc_bracketed_address_may_be_redacted(self) -> None:
        # `<grace@example.com>` is content, not a tag. Asserting that every angle
        # bracket survives would forbid a correct redaction.
        loss = markup_losses(["mail <grace.okafor@example.com> now"], ["mail <EMAIL> now"])
        assert not loss

    def test_a_bracketed_name_in_prose_is_not_defended_as_a_tag(self) -> None:
        loss = markup_losses(["ask <Grace Okafor> about it"], ["ask <PERSON> about it"])
        assert not loss

    def test_a_null_output_is_not_a_loss(self) -> None:
        # The quarantine path writes None deliberately (ADR-0023).
        assert not markup_losses(["<p>x</p>"], [None])

    def test_pseudonymised_output_is_not_a_loss(self) -> None:
        loss = markup_losses(["<p>Grace Okafor</p>"], ["<p>PERSON_A1B2C3</p>"])
        assert not loss

    def test_bbcode_is_covered(self) -> None:
        assert markup_tag_counts("[code]x[/code]") == {"code": 2}


class TestTheCheckStopsTheRun:
    """Fidelity, not recall: structural damage blocks the write (ADR-0027).

    The pipeline is driven with a provider whose spans the test controls, because the
    point is what the *validation stage* does with a damaged output — not whether any
    real recognizer produces one.
    """

    @staticmethod
    def _pipeline_over(tmp_path: Path, body: str, spans: list[tuple[str, int, int]]):  # type: ignore[no-untyped-def]
        import pandas as pd

        from pii_reduction.config import load_resolved_dataset
        from pii_reduction.processing import build_pipeline
        from pii_reduction.sources import PandasSource
        from tests.conftest import write_configs
        from tests.pipeline_fixtures import DATASET_YAML, PROJECT_YAML, write_dataset_csv

        source_path = tmp_path / "input" / "demo.csv"
        write_dataset_csv(source_path)
        configs = write_configs(
            tmp_path,
            # The fixture's scope is EMAIL/PHONE; PERSON is added so the guarded and
            # the exempt case can be driven through the same configuration.
            project_yaml=PROJECT_YAML.replace(
                "entities: [EMAIL, PHONE]", "entities: [EMAIL, PERSON, PHONE]"
            ),
            dataset_yaml=DATASET_YAML.replace(
                "entities: [EMAIL, PHONE]", "entities: [EMAIL, PERSON, PHONE]"
            ).format(
                source_path=source_path.as_posix(),
                destination_path=(tmp_path / "output").as_posix(),
            ),
        )
        pipeline = build_pipeline(load_resolved_dataset(configs, "demo_smoke"))
        processor = pipeline._processors[0]
        chain = processor.default_chain
        processor.default_chain = replace(chain, providers=(_SpanProvider(spans),))
        processor.routing = {}
        processor.fallback_chain = processor.default_chain
        frame = pd.DataFrame(
            [{"row_id": "row_0001", "language": "en", "kind": "plain", "body": body}]
        )
        return pipeline, PandasSource(frame, name="demo_smoke").load()

    def test_an_exempt_email_span_over_a_tag_is_caught_by_the_output_check(
        self, tmp_path: Path
    ) -> None:
        # The guard deliberately does not touch EMAIL, so the damage reaches the
        # output — and the independent check is what notices. Both halves are needed.
        from pii_reduction.processing import ProcessingError

        body = "<td>grace.okafor@example.com</td>"
        pipeline, dataset = self._pipeline_over(tmp_path, body, [(EMAIL, 0, len(body))])
        with pytest.raises(ProcessingError) as exc_info:
            pipeline.process(dataset)
        message = str(exc_info.value)
        assert "markup" in message
        assert "grace.okafor@example.com" not in message
        assert "<td>" not in message

    def test_a_guarded_person_span_leaves_the_tags_intact(self, tmp_path: Path) -> None:
        body = "<td>Grace Okafor</td>"
        pipeline, dataset = self._pipeline_over(tmp_path, body, [(PERSON, 0, len(body))])
        outcome = pipeline.process(dataset)
        reduced = outcome.frame["body_pii_redacted"].iloc[0]
        assert reduced == "<td><PERSON></td>"


class TestTheCheckIsIndependentOfTheGuard:
    """A validator that imports the detector's idea of markup rubber-stamps a shared
    mistake — and the failure both halves exist for was a fixed pattern set meeting a
    dialect it did not know."""

    def test_the_fidelity_module_does_not_import_the_pattern_module(self) -> None:
        source = (PACKAGE_DIR / "processing" / "fidelity.py").read_text(encoding="utf-8")
        imported = {
            node.module
            for node in ast.walk(ast.parse(source))
            if isinstance(node, ast.ImportFrom) and node.module
        } | {
            alias.name
            for node in ast.walk(ast.parse(source))
            if isinstance(node, ast.Import)
            for alias in node.names
        }
        assert not any(name.startswith("pii_reduction") for name in imported), imported

    def test_the_two_vocabularies_are_not_the_same_object(self) -> None:
        from pii_reduction.patterns import MARKUP_TOKEN_VOCABULARY
        from pii_reduction.processing.fidelity import KNOWN_MARKUP_TAGS

        assert MARKUP_TOKEN_VOCABULARY is not KNOWN_MARKUP_TAGS
        # They overlap heavily — both describe HTML — but neither is derived from the
        # other, and the guard's list carries attribute names the check must not treat
        # as tags.
        assert "href" in MARKUP_TOKEN_VOCABULARY
        assert "href" not in KNOWN_MARKUP_TAGS
