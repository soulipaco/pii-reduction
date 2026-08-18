"""Parser contract tests.

Fixtures are Python constants with explicit escapes rather than files: the round-trip
invariant is byte-exact, and a literal ``\\r\\n`` in source is immune to whatever git
or an editor decides to do with line endings on a given machine.

All content is synthetic; emails use RFC 2606 reserved domains (ADR-0003).
"""

from __future__ import annotations

import unicodedata

import pytest

from pii_reduction.config.registries import KNOWN_PARSERS
from pii_reduction.parsers import (
    ParserError,
    PlainTextParser,
    TranscriptParser,
    available_parsers,
    build_parser,
)
from pii_reduction.parsers.transcript import FALLBACK_NO_SPEAKER_PREFIX

pytestmark = pytest.mark.unit

GREEK_NAME_NFC = unicodedata.normalize("NFC", "Μαρία Παπαδοπούλου")
GREEK_NAME_NFD = unicodedata.normalize("NFD", GREEK_NAME_NFC)

TRANSCRIPTS: dict[str, str] = {
    "timestamped": (
        "2026-04-03 09:15:04 - Agent Smith: Hello Maria, how can I help?\n"
        "2026-04-03 09:15:13 - Guest: My email is maria@example.com.\n"
    ),
    "speaker_only": "Agent: Good morning.\nGuest: Hi, my number is +30 210 000 0000.\n",
    "colons_in_body": "Agent: The ratio is 3:1 and the reference is INC00128492.\n",
    "url_in_body": "Guest: See https://example.com/help for details.\n",
    "time_in_body": "Guest: Please call me at 09:15 tomorrow.\n",
    "empty_turn": "Agent Smith:\nGuest: Yes.\n",
    "blank_lines": "Agent: One.\n\nGuest: Two.\n\n",
    "malformed": "This line has no speaker delimiter at all.\nGuest: But this one does.\n",
    "no_delimiter": "Just a paragraph of free text with an email maria@example.com.",
    "crlf": "2026-04-03 09:15:04 - Agent Smith: Hello.\r\nGuest: Hi.\r\n",
    "mixed_newlines": "Agent: One.\r\nGuest: Two.\nAgent: Three.\r",
    "greek_speaker": f"{GREEK_NAME_NFC}: Το email μου είναι maria@example.com.\n",
    "greek_speaker_nfd": f"{GREEK_NAME_NFD}: Το email μου είναι maria@example.com.\n",
    "german_speaker": "Kundenberater Jürgen Müller: Guten Tag, wie kann ich helfen?\n",
    "no_trailing_newline": "Agent: One.\nGuest: Two.",
    "leading_blank_line": "\nAgent: One.\n",
    "empty": "",
    "whitespace_only": "   \n\t\n",
    "twelve_hour_timestamp": "2026/01/07 04:00:12 PM - Agent A: Issue resolved.\n",
}


def transcript_parser(**options: object) -> TranscriptParser:
    return TranscriptParser(dict(options) if options else None)


class TestRegistry:
    def test_registry_matches_what_configuration_accepts(self) -> None:
        assert available_parsers() == KNOWN_PARSERS

    def test_every_configurable_parser_can_be_built(self) -> None:
        for name in KNOWN_PARSERS:
            assert build_parser(name).name == name

    def test_unknown_parser_name_is_actionable(self) -> None:
        with pytest.raises(ParserError) as exc_info:
            build_parser("conversation_v9")
        assert "not registered" in str(exc_info.value)
        assert "transcript" in str(exc_info.value)


class TestRoundTrip:
    """``reconstruct(parse(text)) == text`` for every parser and every fixture."""

    @pytest.mark.parametrize("key", sorted(TRANSCRIPTS))
    def test_transcript_parser_round_trip(self, key: str) -> None:
        source = TRANSCRIPTS[key]
        parser = transcript_parser()
        assert parser.reconstruct(parser.parse(source)) == source

    @pytest.mark.parametrize("key", sorted(TRANSCRIPTS))
    def test_plain_text_parser_round_trip(self, key: str) -> None:
        source = TRANSCRIPTS[key]
        parser = PlainTextParser()
        assert parser.reconstruct(parser.parse(source)) == source

    @pytest.mark.parametrize("key", sorted(TRANSCRIPTS))
    def test_plain_text_parser_round_trip_when_splitting_lines(self, key: str) -> None:
        # The same invariant, on the same fixtures, including CRLF and mixed breaks.
        source = TRANSCRIPTS[key]
        parser = PlainTextParser({"split_lines": True})
        assert parser.reconstruct(parser.parse(source)) == source

    @pytest.mark.parametrize("key", sorted(TRANSCRIPTS))
    def test_segments_tile_the_source_exactly(self, key: str) -> None:
        source = TRANSCRIPTS[key]
        result = transcript_parser().parse(source)
        assert result.source_text() == source
        for segment in result.segments:
            assert segment.source_start is not None and segment.source_end is not None
            assert source[segment.source_start : segment.source_end] == segment.text

    def test_crlf_is_preserved_byte_for_byte(self) -> None:
        source = TRANSCRIPTS["crlf"]
        parser = transcript_parser()
        rebuilt = parser.reconstruct(parser.parse(source))
        assert rebuilt == source
        assert rebuilt.count("\r\n") == 2
        assert "\n\n" not in rebuilt

    def test_mixed_newline_conventions_survive(self) -> None:
        source = TRANSCRIPTS["mixed_newlines"]
        parser = transcript_parser()
        rebuilt = parser.reconstruct(parser.parse(source))
        assert rebuilt == source
        assert rebuilt.endswith("\r")

    def test_nfd_text_is_not_normalized(self) -> None:
        # ADR-0011: no Unicode normalization anywhere. NFC and NFD differ in length
        # and both must come back exactly as supplied.
        source = TRANSCRIPTS["greek_speaker_nfd"]
        parser = transcript_parser()
        rebuilt = parser.reconstruct(parser.parse(source))
        assert rebuilt == source
        assert rebuilt != TRANSCRIPTS["greek_speaker"]
        assert len(GREEK_NAME_NFD) > len(GREEK_NAME_NFC)


class TestTranscriptStructure:
    def test_timestamped_prefix_is_immutable_and_body_is_processable(self) -> None:
        result = transcript_parser().parse(TRANSCRIPTS["timestamped"])
        prefixes = [s.text for s in result.segments if s.segment_type == "transcript_prefix"]
        bodies = [s.text for s in result.segments if s.processable]
        assert prefixes == [
            "2026-04-03 09:15:04 - Agent Smith:",
            "2026-04-03 09:15:13 - Guest:",
        ]
        assert bodies == [" Hello Maria, how can I help?", " My email is maria@example.com."]

    def test_speaker_only_prefix(self) -> None:
        result = transcript_parser().parse(TRANSCRIPTS["speaker_only"])
        assert [s.text for s in result.segments if not s.processable and s.text.strip()] == [
            "Agent:",
            "Guest:",
        ]

    def test_twelve_hour_timestamp_is_part_of_the_prefix(self) -> None:
        result = transcript_parser().parse(TRANSCRIPTS["twelve_hour_timestamp"])
        prefixes = [s.text for s in result.segments if s.segment_type == "transcript_prefix"]
        assert prefixes == ["2026/01/07 04:00:12 PM - Agent A:"]

    def test_body_colons_do_not_start_a_new_split(self) -> None:
        result = transcript_parser().parse(TRANSCRIPTS["colons_in_body"])
        bodies = [s.text for s in result.segments if s.processable]
        assert bodies == [" The ratio is 3:1 and the reference is INC00128492."]

    def test_url_in_body_is_not_treated_as_a_speaker_delimiter(self) -> None:
        result = transcript_parser().parse(TRANSCRIPTS["url_in_body"])
        bodies = [s.text for s in result.segments if s.processable]
        assert bodies == [" See https://example.com/help for details."]

    def test_time_in_body_is_not_treated_as_a_speaker_delimiter(self) -> None:
        result = transcript_parser().parse(TRANSCRIPTS["time_in_body"])
        bodies = [s.text for s in result.segments if s.processable]
        assert bodies == [" Please call me at 09:15 tomorrow."]

    def test_bare_url_line_falls_back_to_body(self) -> None:
        result = transcript_parser().parse("https://example.com/help\n")
        assert result.fallbacks == (FALLBACK_NO_SPEAKER_PREFIX,)
        assert [s.text for s in result.segments if s.processable] == ["https://example.com/help"]

    def test_empty_turn_produces_an_empty_body(self) -> None:
        result = transcript_parser().parse(TRANSCRIPTS["empty_turn"])
        bodies = [s.text for s in result.segments if s.processable]
        assert bodies == ["", " Yes."]

    def test_blank_lines_are_preserved_as_structure(self) -> None:
        source = TRANSCRIPTS["blank_lines"]
        parser = transcript_parser()
        result = parser.parse(source)
        assert parser.reconstruct(result) == source
        assert [s.text for s in result.segments if s.processable] == [" One.", " Two."]

    def test_malformed_line_becomes_one_body_and_records_the_fallback(self) -> None:
        result = transcript_parser().parse(TRANSCRIPTS["malformed"])
        assert result.fallback_used
        assert result.fallbacks == (FALLBACK_NO_SPEAKER_PREFIX,)
        bodies = [s.text for s in result.segments if s.processable]
        assert bodies == ["This line has no speaker delimiter at all.", " But this one does."]

    def test_text_without_any_delimiter_is_entirely_processable(self) -> None:
        source = TRANSCRIPTS["no_delimiter"]
        result = transcript_parser().parse(source)
        assert [s.text for s in result.segments if s.processable] == [source]
        assert result.fallbacks == (FALLBACK_NO_SPEAKER_PREFIX,)

    def test_greek_speaker_stays_in_the_prefix(self) -> None:
        result = transcript_parser().parse(TRANSCRIPTS["greek_speaker"])
        prefixes = [s.text for s in result.segments if s.segment_type == "transcript_prefix"]
        assert prefixes == [f"{GREEK_NAME_NFC}:"]

    def test_german_speaker_stays_in_the_prefix(self) -> None:
        result = transcript_parser().parse(TRANSCRIPTS["german_speaker"])
        prefixes = [s.text for s in result.segments if s.segment_type == "transcript_prefix"]
        assert prefixes == ["Kundenberater Jürgen Müller:"]

    def test_long_prose_before_a_colon_is_not_a_speaker(self) -> None:
        line = "I told the customer that we would follow up with them tomorrow: he agreed.\n"
        result = transcript_parser().parse(line)
        assert result.fallbacks == (FALLBACK_NO_SPEAKER_PREFIX,)

    def test_empty_string_yields_one_empty_processable_segment(self) -> None:
        parser = transcript_parser()
        result = parser.parse("")
        assert len(result.segments) == 1
        assert result.segments[0].text == ""
        assert result.segments[0].processable
        assert parser.reconstruct(result) == ""

    def test_leading_blank_line_is_preserved(self) -> None:
        source = TRANSCRIPTS["leading_blank_line"]
        parser = transcript_parser()
        assert parser.reconstruct(parser.parse(source)) == source

    def test_segment_metadata_records_the_line_number(self) -> None:
        result = transcript_parser().parse(TRANSCRIPTS["timestamped"])
        bodies = [s for s in result.segments if s.processable]
        assert [s.metadata["line_no"] for s in bodies] == [0, 1]


class TestTransformation:
    def test_reconstruct_substitutes_only_processable_segments(self) -> None:
        source = TRANSCRIPTS["timestamped"]
        parser = transcript_parser()
        result = parser.parse(source)
        body = result.processable_segments[1]
        rebuilt = parser.reconstruct(result, {body.segment_id: " My email is <EMAIL>."})
        assert "2026-04-03 09:15:13 - Guest: My email is <EMAIL>." in rebuilt
        assert "maria@example.com" not in rebuilt
        # Prefixes and line breaks are untouched.
        assert rebuilt.startswith("2026-04-03 09:15:04 - Agent Smith: Hello Maria")
        assert rebuilt.endswith("\n")

    def test_prefixes_stay_byte_identical_when_every_body_is_replaced(self) -> None:
        source = TRANSCRIPTS["crlf"]
        parser = transcript_parser()
        result = parser.parse(source)
        rebuilt = parser.reconstruct(
            result, {segment.segment_id: " <REDACTED>" for segment in result.processable_segments}
        )
        assert rebuilt == ("2026-04-03 09:15:04 - Agent Smith: <REDACTED>\r\nGuest: <REDACTED>\r\n")

    def test_transforming_a_non_processable_segment_is_refused(self) -> None:
        parser = transcript_parser()
        result = parser.parse(TRANSCRIPTS["timestamped"])
        prefix = next(s for s in result.segments if not s.processable)
        with pytest.raises(ParserError) as exc_info:
            parser.reconstruct(result, {prefix.segment_id: "hacked"})
        assert "not processable" in str(exc_info.value)

    def test_unknown_segment_id_is_refused(self) -> None:
        parser = transcript_parser()
        result = parser.parse(TRANSCRIPTS["speaker_only"])
        with pytest.raises(ParserError) as exc_info:
            parser.reconstruct(result, {"line_9999_body": "x"})
        assert "line_9999_body" in str(exc_info.value)

    def test_plain_text_substitution(self) -> None:
        parser = PlainTextParser()
        result = parser.parse("Contact maria@example.com today.")
        segment = result.segments[0]
        assert (
            parser.reconstruct(result, {segment.segment_id: "Contact <EMAIL> today."})
            == "Contact <EMAIL> today."
        )


class TestParserOptions:
    def test_unknown_option_is_actionable(self) -> None:
        with pytest.raises(ParserError) as exc_info:
            transcript_parser(speaker_delimiter=":")
        assert "speaker_delimiter" in str(exc_info.value)
        assert "speaker_delimiters" in str(exc_info.value)

    def test_plain_text_parser_rejects_unknown_options(self) -> None:
        with pytest.raises(ParserError) as exc_info:
            PlainTextParser({"line_mode": "auto"})
        assert "line_mode" in str(exc_info.value)
        assert "split_lines" in str(exc_info.value)

    def test_split_lines_must_be_a_boolean(self) -> None:
        with pytest.raises(ParserError, match="must be true or false"):
            PlainTextParser({"split_lines": "yes"})


class TestPlainTextLineSplitting:
    """``split_lines`` exists to stop NER spans running across a line break.

    Handed a key/value block as one segment, spaCy returns ``Grace Okafor\\nMobile``
    for the PERSON — the name is found but the span swallows the next line's first
    word, which strict matching scores as both a miss and a false positive. Splitting
    lines makes the boundary exact.

    Measured in session 5 on the ``deterministic_presidio`` chain: English tier-3
    PERSON strict recall 0.000 -> 1.000 on the dev+calibration splits (support 3).
    The whole-corpus figure for the same slice is 0.333 (support 6) — two of the six
    happen to sit on a line whose following word the model does not absorb. The two
    numbers describe different scopes, not different behaviour.
    """

    def test_off_by_default_so_prose_is_unaffected(self) -> None:
        # Wrapped prose must not be split: a name broken across the wrap would then
        # be undetectable. Free text is what this parser is named for.
        result = PlainTextParser().parse("Maria\nRossi called.")
        assert len(result.segments) == 1
        assert result.segments[0].processable

    def test_each_line_becomes_its_own_processable_segment(self) -> None:
        result = PlainTextParser({"split_lines": True}).parse(
            "Customer: Grace Okafor\nMobile number: 000\nDepartment: Support"
        )
        bodies = [s.text for s in result.segments if s.processable]
        assert bodies == [
            "Customer: Grace Okafor",
            "Mobile number: 000",
            "Department: Support",
        ]

    def test_line_breaks_are_non_processable_and_survive_byte_exact(self) -> None:
        source = "a\r\nb\rc\nd"
        result = PlainTextParser({"split_lines": True}).parse(source)
        breaks = [s.text for s in result.segments if not s.processable]
        assert breaks == ["\r\n", "\r", "\n"]
        assert result.source_text() == source

    def test_empty_lines_are_kept(self) -> None:
        # Dropping them would break the tiling the round-trip depends on.
        result = PlainTextParser({"split_lines": True}).parse("one\n\nthree")
        assert [s.text for s in result.segments] == ["one", "\n", "", "\n", "three"]

    @pytest.mark.parametrize("source", ["", "x", "\n", "\r\n", "a\nb\n"])
    def test_offsets_slice_true_against_the_source(self, source: str) -> None:
        result = PlainTextParser({"split_lines": True}).parse(source)
        for segment in result.segments:
            assert source[segment.source_start : segment.source_end] == segment.text

    @pytest.mark.parametrize("key", sorted(TRANSCRIPTS))
    def test_segments_tile_every_fixture_exactly(self, key: str) -> None:
        # The same tiling assertion the transcript parser gets, over the same fixtures
        # — CRLF, mixed breaks and NFD Greek included, where ad-hoc strings would not
        # exercise the offsets that actually go wrong.
        source = TRANSCRIPTS[key]
        result = PlainTextParser({"split_lines": True}).parse(source)
        for segment in result.segments:
            assert source[segment.source_start : segment.source_end] == segment.text
        assert result.source_text() == source

    def test_crlf_survives_a_substitution_byte_for_byte(self) -> None:
        # The CRLF round trip only proves the *untransformed* path. Reduction is the
        # path that matters, and a break rebuilt as a bare \n would be a silent
        # corruption of every Windows-authored document.
        parser = PlainTextParser({"split_lines": True})
        source = "Customer: Grace Okafor\r\nDepartment: Support\r\n"
        result = parser.parse(source)
        first = result.processable_segments[0]
        rebuilt = parser.reconstruct(result, {first.segment_id: "Customer: <PERSON>"})
        assert rebuilt == "Customer: <PERSON>\r\nDepartment: Support\r\n"
        assert rebuilt.count("\r\n") == source.count("\r\n")
        assert "\n" not in rebuilt.replace("\r\n", "")

    def test_break_segments_are_named_as_breaks(self) -> None:
        # segment_id reaches the audit table; a break numbered as a line would make
        # the audit disagree with the transcript parser about what the number means.
        result = PlainTextParser({"split_lines": True}).parse("a\nb")
        assert [s.segment_id for s in result.segments] == ["line_0000", "break_0000", "line_0001"]

    def test_a_line_can_be_transformed_without_touching_the_others(self) -> None:
        parser = PlainTextParser({"split_lines": True})
        result = parser.parse("Customer: Grace Okafor\nDepartment: Support")
        first = result.processable_segments[0]
        assert parser.reconstruct(result, {first.segment_id: "Customer: <PERSON>"}) == (
            "Customer: <PERSON>\nDepartment: Support"
        )

    def test_alternative_delimiter(self) -> None:
        parser = transcript_parser(speaker_delimiters=[">"])
        result = parser.parse("Agent> Hello.\n")
        assert [s.text for s in result.segments if s.segment_type == "transcript_prefix"] == [
            "Agent>"
        ]

    def test_preserve_prefix_false_makes_the_whole_line_processable(self) -> None:
        parser = transcript_parser(preserve_prefix=False)
        source = TRANSCRIPTS["speaker_only"]
        result = parser.parse(source)
        assert [s.text for s in result.segments if s.processable] == [
            "Agent: Good morning.",
            "Guest: Hi, my number is +30 210 000 0000.",
        ]
        assert parser.reconstruct(result) == source

    def test_unsupported_fallback_policy_is_refused(self) -> None:
        with pytest.raises(ParserError) as exc_info:
            transcript_parser(fallback="drop_line")
        assert "drop_line" in str(exc_info.value)

    def test_speaker_length_limit_is_configurable(self) -> None:
        line = "A very long speaker name that goes on and on: body\n"
        assert transcript_parser().parse(line).fallback_used
        assert (
            not transcript_parser(max_speaker_length=80, max_speaker_words=12)
            .parse(line)
            .fallback_used
        )


class TestCallerContract:
    def test_none_is_rejected_rather_than_silently_handled(self) -> None:
        for parser in (PlainTextParser(), transcript_parser()):
            with pytest.raises(ParserError) as exc_info:
                parser.parse(None)  # type: ignore[arg-type]
            assert "Null values are handled by the field processor" in str(exc_info.value)

    def test_parse_does_not_mutate_the_source(self) -> None:
        source = TRANSCRIPTS["timestamped"]
        before = source
        transcript_parser().parse(source)
        assert source == before
