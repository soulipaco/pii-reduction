"""The three mechanisms behind the Greek PERSON gap (ADR-0019, plan §8 Q4).

These are **characterisation tests of the model**, which is unusual and deliberate. The
Greek numbers have been explained as a licensing consequence since ADR-0007; Q4 found
that the model usually *finds* the tokens and then assigns the wrong label or the wrong
boundary. That diagnosis is what a later session will build a remedy on, so it is pinned
here rather than left in a document.

If a model bump fixes one of these, the test fails, and Greek is re-measured
deliberately — the same discipline `configs/benchmark_gates.yaml` applies to the
numbers. A failure here is not a regression; it is an instruction to re-read ADR-0019.

Marked `integration`: needs the presidio extra and `xx_ent_wiki_sm`, so it runs in the
nightly job with the pinned models, never on a push (ADR-0009).

Every value asserted on is **drawn** from the committed pools and templates (ADR-0014,
ADR-0003) rather than copied into this file, so a pool change cannot leave these tests
asserting on a value that exists nowhere.
"""

from __future__ import annotations

import pytest

from pii_reduction.synthetic.templates import templates_for
from pii_reduction.synthetic.values import PERSONS, PHONES

pytestmark = [pytest.mark.integration]

GREEK = tuple(person.name for person in PERSONS["el"])
GERMAN = tuple(person.name for person in PERSONS["de"])
GREEK_PHONE = PHONES["el"][0]


def _corpus_line(marker: str) -> str | None:
    """A Greek template line carrying ``marker``, so a carrier cannot drift from it.

    Returns ``None`` rather than raising. A bare ``next()`` would turn "somebody edited
    the Greek templates" — the exact change the guard in this file exists to catch —
    into a ``StopIteration`` at import, erroring every test here including the one
    written to explain why.
    """
    return next(
        (
            line
            for spec in templates_for("el")
            for line in spec.template.splitlines()
            if marker in line
        ),
        None,
    )


#: The corpus's own tier-4 Greek line, and the tier-1 line that carries the άνω τελεία.
GREEK_TURN = _corpus_line("Ονομάζομαι")
GREEK_ANO_TELEIA_LINE = _corpus_line("·")


@pytest.fixture(scope="module")
def nlp():  # type: ignore[no-untyped-def]
    spacy = pytest.importorskip("spacy")
    try:
        return spacy.load("xx_ent_wiki_sm")
    except OSError:  # pragma: no cover - model not installed
        pytest.skip("xx_ent_wiki_sm is not installed")


def exact_person(nlp, text: str, name: str) -> bool:  # type: ignore[no-untyped-def]
    start, end = text.index(name), text.index(name) + len(name)
    return any(
        entity.start_char == start and entity.end_char == end and entity.label_ == "PER"
        for entity in nlp(text).ents
    )


def overlapping(nlp, text: str, name: str):  # type: ignore[no-untyped-def]
    start, end = text.index(name), text.index(name) + len(name)
    return [
        entity for entity in nlp(text).ents if entity.start_char < end and start < entity.end_char
    ]


def mislabelled(nlp, text: str, name: str) -> str | None:  # type: ignore[no-untyped-def]
    """The label on an *exactly* placed span that is not PER, if there is one."""
    start, end = text.index(name), text.index(name) + len(name)
    for entity in nlp(text).ents:
        if entity.start_char == start and entity.end_char == end and entity.label_ != "PER":
            return str(entity.label_)
    return None


class TestItIsMostlyNotADetectionFailure:
    """The premise the diagnosis rests on: the model usually sees the names."""

    def test_a_neutral_greek_sentence_finds_most_of_the_pool(self, nlp) -> None:  # type: ignore[no-untyped-def]
        found = sum(exact_person(nlp, f"Ο πελάτης είναι {name}.", name) for name in GREEK)
        assert found >= 6, (
            f"{found}/8 — the pool is better recognised than the corpus numbers suggest; "
            "if this drops, ADR-0019's diagnosis needs redoing"
        )

    def test_german_is_perfect_on_the_same_model(self, nlp) -> None:  # type: ignore[no-untyped-def]
        # The contrast that makes the Greek result a Greek result rather than a model
        # result: same model, same sentence shape, same kind of pool.
        found = sum(exact_person(nlp, f"Der Kontoinhaber ist {name}.", name) for name in GERMAN)
        assert found == 8

    def test_a_neutral_sentence_never_goes_silent(self, nlp) -> None:  # type: ignore[no-untyped-def]
        silent = [name for name in GREEK if not overlapping(nlp, f"Ο πελάτης είναι {name}.", name)]
        assert not silent, f"model returned no span at all for {silent}"

    def test_but_the_bare_name_does(self, nlp) -> None:  # type: ignore[no-untyped-def]
        """The other half of the same claim, so its scope cannot quietly widen.

        Silence is the *minority* case — 4 of the 40 Greek probes in ADR-0019 — not the
        absent one. Two of those four are here and two are in the tier-3 `Από:` form,
        which is why the ADR says better detection would move tier 3 rather than nothing.
        """
        silent = [name for name in GREEK if not overlapping(nlp, name, name)]
        assert len(silent) == 2, f"{len(silent)}/8 silent with no context at all, expected 2"

    def test_the_key_value_form_is_where_detection_work_would_pay(self, nlp) -> None:  # type: ignore[no-untyped-def]
        """The one claim in ADR-0019 that a remedy would be budgeted against.

        The tier-3 `Από: {name}` line is the only carrier where the model goes silent
        with context present, and it is the sole evidence for "better detection would
        move tier 3". Left unpinned it is a sentence in a document; pinned, a model bump
        that changes it fails here.
        """
        silent = [name for name in GREEK if not overlapping(nlp, f"Από: {name}", name)]
        assert len(silent) == 2, (
            f"{len(silent)}/8 silent in the key/value form, expected 2. ADR-0019 ranks "
            "detection last of three remedies on the strength of this number"
        )


class TestMechanismOneSpanAbsorption:
    """A capitalised token before the name is swallowed into the span — all of tier 4."""

    #: The corpus clause without its timestamp and speaker prefix. Reduced on purpose,
    #: since the prefix is another capitalised token and therefore the variable under
    #: study; the full line is covered below and behaves identically.
    TURN = "Ονομάζομαι {name}, τηλέφωνο " + GREEK_PHONE + "."

    def test_the_synthetic_transcript_phrasing_finds_nothing_exactly(self, nlp) -> None:  # type: ignore[no-untyped-def]
        assert sum(exact_person(nlp, self.TURN.format(name=n), n) for n in GREEK) == 0

    def test_the_real_template_line_behaves_the_same(self, nlp) -> None:  # type: ignore[no-untyped-def]
        # Built from `templates_for("el")`, prefix and all: the extra capitalised tokens
        # change nothing, so the reduced carrier above is a fair stand-in.
        if GREEK_TURN is None:
            pytest.skip("the Greek transcript template no longer uses Ονομάζομαι")
        line = GREEK_TURN.replace("{PHONE}", GREEK_PHONE)
        found = sum(exact_person(nlp, line.replace("{PERSON}", n), n) for n in GREEK)
        assert found == 0

    def test_but_the_span_covers_the_name_plus_the_verb(self, nlp) -> None:  # type: ignore[no-untyped-def]
        # Which is why strict matching scores it as a miss *and* a false positive, and
        # why this is a boundary problem in the ADR-0016 family rather than a detection
        # problem. There is no line break here, so line-scoped span repair cannot see it.
        absorbed = 0
        for name in GREEK:
            text = self.TURN.format(name=name)
            for entity in overlapping(nlp, text, name):
                if entity.text.startswith("Ονομάζομαι") and name.split()[0] in entity.text:
                    absorbed += 1
                    break
        assert absorbed >= 7, f"only {absorbed}/8 absorbed the preceding verb"

    def test_lower_casing_the_verb_recovers_most_of_it(self, nlp) -> None:  # type: ignore[no-untyped-def]
        # Isolates the trigger to the capitalisation, not to the word.
        lowered = "ονομάζομαι {name}, τηλέφωνο " + GREEK_PHONE + "."
        assert sum(exact_person(nlp, lowered.format(name=n), n) for n in GREEK) >= 5


class TestMechanismTwoLabelConfusion:
    """An exact span with the wrong label. ADR-0004 correctly refuses to map it."""

    CARRIER = "Ο πελάτης είναι {name}."

    def test_two_names_come_back_with_an_exact_span_and_the_wrong_label(self, nlp) -> None:  # type: ignore[no-untyped-def]
        wrong = {
            name: label
            for name in GREEK
            if (label := mislabelled(nlp, self.CARRIER.format(name=name), name))
        }
        assert len(wrong) == 2, f"expected 2 mislabelled names in this carrier, got {wrong}"
        assert set(wrong.values()) == {"ORG", "LOC"}, (
            f"the labels changed: {wrong}. ADR-0019 records ORG and LOC here and MISC in "
            "other carriers; a remedy that promoted only one of them would miss the rest"
        )

    def test_the_failure_is_not_predicted_by_the_genitive_ending(self, nlp) -> None:  # type: ignore[no-untyped-def]
        """The claim ADR-0019's first draft got wrong, pinned so it stays right.

        A `-ου` surname is not what fails: most of them are labelled correctly. Any rule
        keyed on the ending would fire on names that need no help and miss the ones that
        do — the word-list trap the identifier guard was built to avoid.
        """
        genitive = [name for name in GREEK if name.split()[-1].endswith(("ου", "ών"))]
        correct = [
            name for name in genitive if exact_person(nlp, self.CARRIER.format(name=name), name)
        ]
        assert len(correct) >= 3, (
            f"only {len(correct)} of {len(genitive)} genitive surnames were labelled PER; "
            "if this drops, re-read ADR-0019 mechanism 2 before building a rule on it"
        )


class TestMechanismThreeTheAnoTeleia:
    """A legitimate Greek punctuation mark halves detection. The corpus keeps it."""

    #: Drawn from the corpus, not restated: this is the tier-1 template the άνω τελεία
    #: actually appears in, with its tail replaced per case. Restating it as a literal
    #: would let a template rewrite leave these tests passing against text that is in no
    #: corpus, while the published "halves detection" claim lost its subject.
    CARRIER = (GREEK_ANO_TELEIA_LINE or "").split("·")[0].replace("{PERSON}", "{name}") + "{tail}"

    def hits(self, nlp, tail: str) -> int:  # type: ignore[no-untyped-def]
        return sum(exact_person(nlp, self.CARRIER.format(name=n, tail=tail), n) for n in GREEK)

    def test_the_middle_dot_costs_half_the_detections(self, nlp) -> None:  # type: ignore[no-untyped-def]
        with_dot = self.hits(nlp, "· δεν απαιτείται ενέργεια.")
        with_comma = self.hits(nlp, ", δεν απαιτείται ενέργεια.")
        # "Half" literally — 3 against 6 as measured — asserted as a ratio so the test
        # pins the size of the effect and not merely its direction.
        assert with_dot * 2 <= with_comma, (
            f"ano teleia {with_dot}/8 vs comma {with_comma}/8 — the gap ADR-0019 measured "
            "has narrowed; re-read it before trusting the Greek tier-1 number"
        )

    def test_other_punctuation_does_not(self, nlp) -> None:  # type: ignore[no-untyped-def]
        # Isolates the mark itself rather than "a clause follows the name". The Greek
        # question mark is included because ADR-0019 and plan §8 both claim it.
        assert self.hits(nlp, ". Δεν απαιτείται ενέργεια.") >= 6
        assert self.hits(nlp, ", δεν απαιτείται ενέργεια.") >= 6
        assert self.hits(nlp, "; δεν απαιτείται ενέργεια.") >= 6

    def test_the_greek_code_point_also_breaks_the_token(self, nlp) -> None:  # type: ignore[no-untyped-def]
        # U+0387 is the proper ano teleia; the corpus uses U+00B7. With U+0387 the
        # tokenizer glues the mark to the surname, so the span is wrong as well as the
        # label — worth knowing before anyone "fixes" the corpus by switching code point.
        glued = nlp(f"είναι {GREEK[0]}· δεν")
        assert any(token.text.endswith("·") and len(token.text) > 1 for token in glued)
