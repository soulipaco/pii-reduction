"""ADR-0029: the corpus that gives ADR-0027 a number.

ADR-0027 shipped a detection change with no corpus support at all — every corpus in
this repository is markup-free, so the failure class its guard exists for had no
measurement anywhere. This module is the check on that corpus: that it is reproducible, that it actually
contains what it claims to, that it round-trips, that the guard is load-bearing on it,
and that its gate file is loadable for both chains.

Default tier throughout, and deliberately: the corpus, the parsers, the guard and the
gate-file schema are all model-free. The *numbers* in `configs/markup_gates.yaml` are
run by CI — the deterministic set on every push, the hybrid set in the integration
workflow — rather than here, because running a benchmark inside the unit tier would put
a model behind the default `pytest`.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest
import yaml

from pii_reduction.cli import DEFAULT_MARKUP_PER_LANGUAGE, DEFAULT_SEED
from pii_reduction.contracts.entities import EntityMatch
from pii_reduction.entities.taxonomy import PERSON
from pii_reduction.evaluation.gates import load_gate_file
from pii_reduction.parsers.registry import build_parser
from pii_reduction.patterns import markup_free_fragments, markup_regions
from pii_reduction.processing.fidelity import markup_tag_counts
from pii_reduction.providers.base import BaseProvider
from pii_reduction.synthetic.corpus import Corpus, build_corpus, load_corpus
from pii_reduction.synthetic.errors import CorpusError
from pii_reduction.synthetic.markup_notes import MARKUP_TEMPLATES, markup_templates

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[1]
MARKUP_DIR = REPO_ROOT / "tests" / "fixtures" / "markup"
GATE_FILE = REPO_ROOT / "configs" / "markup_gates.yaml"


def _corpus() -> Corpus:
    return load_corpus(MARKUP_DIR)


def _entity_row(entity: object) -> tuple[object, ...]:
    return (
        entity.document_id,  # type: ignore[attr-defined]
        entity.entity_id,  # type: ignore[attr-defined]
        entity.entity_type,  # type: ignore[attr-defined]
        entity.start,  # type: ignore[attr-defined]
        entity.end,  # type: ignore[attr-defined]
        entity.surface,  # type: ignore[attr-defined]
        entity.language,  # type: ignore[attr-defined]
        entity.difficulty_tier,  # type: ignore[attr-defined]
    )


def _protected_row(token: object) -> tuple[object, ...]:
    return (
        token.document_id,  # type: ignore[attr-defined]
        token.token,  # type: ignore[attr-defined]
        token.kind,  # type: ignore[attr-defined]
        token.start,  # type: ignore[attr-defined]
        token.end,  # type: ignore[attr-defined]
    )


def _markup_step(workflow: str) -> str:
    """The one workflow step that names the markup gate file, so a `deterministic_presidio`
    somewhere else in the file cannot satisfy or break the assertions above."""
    steps = workflow.split("      - name: ")
    return next(step for step in steps if "configs/markup_gates.yaml" in step)


class _FixedSpanProvider(BaseProvider):
    """Returns exactly the spans it was handed, so the repair is what is under test."""

    name = "fixed_span"

    def __init__(self, spans: list[tuple[str, int, int]]) -> None:
        self._spans = spans

    def supported_entities(self) -> frozenset[str]:
        return frozenset({PERSON})

    def _detect(
        self, text: str, *, language: str | None, entities: frozenset[str]
    ) -> list[EntityMatch]:
        return [
            EntityMatch(start=start, end=end, entity_type=label, provider=self.name, score=0.85)
            for label, start, end in self._spans
            if label in entities
        ]


class TestTheCorpusIsReproducible:
    """Same seed, same size, byte-identical result (ADR-0011). CI checks the committed
    files against a fresh build, so a generator change that forgets to regenerate
    fails rather than drifting."""

    def test_the_committed_corpus_rebuilds_exactly(self) -> None:
        rebuilt = build_corpus(
            seed=DEFAULT_SEED,
            documents_per_language=DEFAULT_MARKUP_PER_LANGUAGE,
            templates=markup_templates,
            id_prefix="mk",
            profile="markup",
        )
        committed = load_corpus(MARKUP_DIR)
        assert [d.text for d in rebuilt.documents] == [d.text for d in committed.documents]
        assert [d.document_id for d in rebuilt.documents] == [
            d.document_id for d in committed.documents
        ]
        # **Fields, not lengths.** Comparing counts would let a generator change that
        # shifted every span by one, relabelled an entity or reassigned a split call
        # itself a byte-identical rebuild — while silently invalidating the ground
        # truth all eight gates are scored against. CI diffs the four files as bytes;
        # this is the same assertion without a subprocess.
        assert [_entity_row(e) for e in rebuilt.entities] == [
            _entity_row(e) for e in committed.entities
        ]
        assert [_protected_row(t) for t in rebuilt.protected] == [
            _protected_row(t) for t in committed.protected
        ]

        def shape(d: object) -> tuple[object, ...]:
            return (d.document_id, d.split, d.tier, d.language, d.document_type)  # type: ignore[attr-defined]

        assert [shape(d) for d in rebuilt.documents] == [shape(d) for d in committed.documents]

    def test_the_ids_cannot_be_confused_with_another_profile(self) -> None:
        # `doc` is the benchmark corpus, `inc` the incident corpus. A metric row or a
        # manifest that mixed two profiles would be unreadable.
        assert all(d.document_id.startswith("mk") for d in _corpus().documents)

    def test_the_profile_is_recorded(self) -> None:
        meta = json.loads((MARKUP_DIR / "meta.json").read_text(encoding="utf-8"))
        assert meta["profile"] == "markup"

    def test_an_unknown_language_is_refused_by_name(self) -> None:
        with pytest.raises(CorpusError, match="no markup templates for language"):
            markup_templates("fr")


class TestTheCorpusContainsWhatItClaims:
    """A markup corpus with no markup in it would pass every gate and measure nothing —
    which is the failure mode this whole corpus exists to prevent elsewhere."""

    def test_every_document_contains_markup(self) -> None:
        for document in _corpus().documents:
            assert markup_regions(document.text), document.document_id

    def test_every_language_carries_all_three_shapes(self) -> None:
        assert set(MARKUP_TEMPLATES) == {"en", "de", "el"}
        for language, specs in MARKUP_TEMPLATES.items():
            tiers = {spec.tier for spec in specs}
            assert tiers == {3, 4}, language
            assert len(specs) == 3, language

    def test_the_shapes_the_reference_implementation_measured_are_present(self) -> None:
        """Not shapes invented to be easy. Each of these destroyed real cells
        (`docs/20_ALTERNATIVE_RECONCILIATION.md`)."""
        texts = "\n".join(d.text for d in _corpus().documents)
        for shape in ("[code]<div", "</div>[/code]", "<br>", "&nbsp;", "&lt;", "[url=", "<a href="):
            assert shape in texts, shape

    def test_some_ground_truth_sits_inside_a_markup_region(self) -> None:
        """The attribute template puts a name inside an anchor tag. Redacting it there
        is correct, and it is the case that would leak if a span wholly inside a region
        were discarded — which is exactly the bug the ADR-0027 audit found."""
        corpus = _corpus()
        by_id = {d.document_id: d.text for d in corpus.documents}
        inside = [
            entity
            for entity in corpus.entities
            if not markup_free_fragments(
                entity.start, entity.end, markup_regions(by_id[entity.document_id])
            )
        ]
        assert inside, (
            "no entity lies wholly inside markup; the attribute template is not doing its job"
        )

    def test_protected_tokens_sit_beside_the_markup(self) -> None:
        """Both directions in one corpus: a destroyed tag is a fidelity failure, a
        destroyed asset tag is over-redaction. That only holds if the identifiers are
        actually *in* the markup-bearing text rather than in some quiet corner, so the
        property is asserted rather than the count."""
        corpus = _corpus()
        by_id = {d.document_id: d.text for d in corpus.documents}
        for token in corpus.protected:
            text = by_id[token.document_id]
            line_start = text.rfind("\n", 0, token.start) + 1
            line_end = text.find("\n", token.end)
            line = text[line_start : line_end if line_end >= 0 else len(text)]
            assert markup_regions(text), token.document_id
            # The token itself must survive reduction; the line it sits on is where a
            # span that ran into markup would reach it.
            assert token.token in line, token.document_id


class TestStructureIsPreserved:
    def test_every_document_round_trips_byte_for_byte(self) -> None:
        """AGENTS.md rule 5, on shapes no parser fixture covers.

        This corpus puts `<p>` tags, `[url=…]` blocks, a zero-width space and `&nbsp;`
        runs inside transcript bodies. It passes today; the test exists so it still
        does after the markup-stripping increment ADR-0029 points at, which is the one
        change most likely to break reconstruction.
        """
        for document in _corpus().documents:
            parser = build_parser(
                "transcript" if document.document_type == "transcript" else "plain_text", {}
            )
            parsed = parser.parse(document.text)
            assert parser.reconstruct(parsed, {}) == document.text, document.document_id


class TestTheGuardIsLoadBearingOnThisCorpus:
    """Model-free proof that the clip is doing work here, on the corpus's own text.

    A span covering `[code]<div` is what spaCy actually returns on this shape at 0.85
    (ADR-0027). Reducing it unclipped destroys the tag; the guard is the reason that
    does not happen. Shown on real corpus text rather than a hand-written string, and
    with no model, so it runs on every push.
    """

    def _note_document(self) -> str:
        for document in _corpus().documents:
            if "[code]<div" in document.text:
                return str(document.text)
        raise AssertionError("no document carries the [code]<div shape")

    def test_reducing_an_unclipped_span_destroys_a_tag(self) -> None:
        text = self._note_document()
        start = text.index("code]<div")
        unclipped = text[:start] + "<PERSON>" + text[start + len("code]<div") :]
        before = markup_tag_counts(text)
        after = markup_tag_counts(unclipped)
        assert sum((before - after).values()) > 0, "the premise of ADR-0027 does not hold here"

    def test_the_guard_leaves_the_tag_intact_on_the_same_span(self) -> None:
        """The other half of the comparison, through the real provider boundary.

        The same span the test above splices unclipped is handed to `detect()`, and
        what survives is spliced instead. No model: the provider returns the span
        spaCy was measured returning, so this is the guard under test and nothing else.
        """
        text = self._note_document()
        start = text.index("code]<div")
        end = start + len("code]<div")

        provider = _FixedSpanProvider([(PERSON, start, end)])
        survivors = provider.detect(text, language="en", entities=(PERSON,))

        reduced = text
        for match in sorted(survivors, key=lambda m: m.start, reverse=True):
            reduced = reduced[: match.start] + "<PERSON>" + reduced[match.end :]

        assert markup_tag_counts(reduced) == markup_tag_counts(text)
        # And it is the guard doing it, not an empty detector upstream.
        assert markup_free_fragments(start, end, markup_regions(text)) == []


class TestTheGateFile:
    def test_it_exists_and_covers_both_chains(self) -> None:
        gates = yaml.safe_load(GATE_FILE.read_text(encoding="utf-8"))
        assert set(gates["gate_sets"]) == {"deterministic_only", "deterministic_presidio"}

    @pytest.mark.parametrize("chain", ["deterministic_only", "deterministic_presidio"])
    def test_it_loads_through_the_loader_that_will_evaluate_it(self, chain: str) -> None:
        """`yaml.safe_load` proves the file is YAML, not that it is a gate file.

        Without this, `minimum:` for `min:`, a duplicate gate name, a missing `version`
        or an unknown key would sit undetected until the CI step that runs it failed —
        and for the hybrid set, that is a nightly. Same assertion the pack gate files
        get, and for the same reason.
        """
        gates = load_gate_file(GATE_FILE, chain)
        assert gates
        assert all(gate.min_support is not None for gate in gates), (
            "every gate must record the support it was measured over"
        )

    def test_the_recorded_corpus_parameters_are_the_ones_that_built_it(self) -> None:
        measured = yaml.safe_load(GATE_FILE.read_text(encoding="utf-8"))["measured"]
        assert measured["seed"] == DEFAULT_SEED
        assert measured["documents_per_language"] == DEFAULT_MARKUP_PER_LANGUAGE

    def test_both_chains_are_gated_in_the_workflow_that_can_run_them(self) -> None:
        """The deterministic set is model-free and runs on every push; the hybrid set
        needs models and runs nightly.

        The earlier version of this test forbade *any* workflow from naming this gate
        file, borrowing the packs' rule. That rule does not transfer: a pack needs a
        download, this corpus is committed, and the reason ADR-0029 gives for the
        corpus existing — that a regression should be a gate failure rather than a code
        review — is only true if something runs the gates. The architecture review of
        this increment caught the claim outrunning the automation.
        """
        workflows = REPO_ROOT / ".github" / "workflows"
        push_tier = (workflows / "ci.yml").read_text(encoding="utf-8")
        nightly = (workflows / "integration.yml").read_text(encoding="utf-8")

        assert "configs/markup_gates.yaml" in push_tier
        assert "deterministic_presidio" not in _markup_step(push_tier), (
            "the hybrid set needs models the push tier does not install"
        )
        assert "configs/markup_gates.yaml" in nightly
        assert "deterministic_presidio" in _markup_step(nightly)

    def test_the_corpus_is_rebuilt_and_diffed_by_ci(self) -> None:
        # ADR-0029 claims CI checks the committed corpus byte for byte. This is what
        # makes that claim true rather than aspirational.
        push_tier = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
        assert "build-markup" in push_tier
        assert "diff -r tests/fixtures/markup" in push_tier

    def test_the_corpus_shape_matches_what_the_gates_say_it_is(self) -> None:
        measured = yaml.safe_load(GATE_FILE.read_text(encoding="utf-8"))["measured"]
        with (MARKUP_DIR / "corpus.csv").open(encoding="utf-8", newline="") as handle:
            documents = sum(1 for _ in csv.DictReader(handle))
        assert str(documents) in measured["corpus"]
