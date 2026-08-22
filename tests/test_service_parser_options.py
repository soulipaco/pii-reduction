"""ADR-0034: which knobs a caller may turn, and what stops the tables from drifting.

The fact is split across two layers on purpose, and each half has its own guard here:

* **Validity** — `config/registries.py`'s `KNOWN_PARSER_OPTIONS` says which options a
  parser accepts. Engine knowledge, restated because `config/` may not import
  `parsers/`, and pinned by an **equality** so a new option fails a test rather than
  passing unnoticed.
* **Policy** — `service/knobs.py` says which of those a caller may set over HTTP.
  Every parser boolean must be in exactly one of `OFFERABLE_PARSER_OPTIONS` or
  `CONSIDERED_AND_NOT_OFFERED`, so silence cannot be mistaken for an oversight.

Plus the boundary itself: ADR-0034's claim is that a caller may move a *quality* knob
and never a *privacy* one, and the request models are where that is enforced.

Default tier: no models, no HTTP, no Spark.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from pii_reduction.config.registries import KNOWN_PARSER_OPTIONS, KNOWN_PARSERS
from pii_reduction.parsers.key_value import DEFAULT_OPTIONS as KEY_VALUE_OPTIONS
from pii_reduction.parsers.plain_text import DEFAULT_OPTIONS as PLAIN_TEXT_OPTIONS
from pii_reduction.parsers.registry import build_parser
from pii_reduction.parsers.transcript import DEFAULT_OPTIONS as TRANSCRIPT_OPTIONS
from pii_reduction.service import models as service_models
from pii_reduction.service.knobs import (
    CONSIDERED_AND_NOT_OFFERED,
    OFFERABLE_OPTION_NAMES,
    OFFERABLE_PARSER_OPTIONS,
    OFFERED_OPTION_CAPTIONS,
    OFFERED_OPTION_DEFAULTS,
)
from pii_reduction.service.models import ServiceModel
from pii_reduction.service.templates import DatasetTemplate

pytestmark = pytest.mark.unit

#: The real option tables, by parser name — the source of truth both restatements
#: are compared against.
REAL_OPTIONS = {
    "plain_text": PLAIN_TEXT_OPTIONS,
    "transcript": TRANSCRIPT_OPTIONS,
    "key_value": KEY_VALUE_OPTIONS,
}

#: The five settings that stay server-side (ADR-0026 rule 4, restated by ADR-0034).
PRIVACY_SWITCHES = ("source", "destination", "failure_mode", "preserve_original", "projection")


def real_booleans(parser_name: str) -> frozenset[str]:
    return frozenset(
        option for option, value in REAL_OPTIONS[parser_name].items() if isinstance(value, bool)
    )


class TestValidityMatchesTheParsers:
    """`config/registries.py` vs the parsers. An equality, in both directions."""

    def test_every_parser_has_an_option_table(self) -> None:
        assert set(KNOWN_PARSER_OPTIONS) == KNOWN_PARSERS == set(REAL_OPTIONS)

    @pytest.mark.parametrize("parser_name", sorted(REAL_OPTIONS))
    def test_the_table_equals_the_parsers_own_options(self, parser_name: str) -> None:
        """Equality, not a subset: an option added to a parser fails here.

        A subset check would let a new parser option exist that configuration silently
        refuses, which is worse than the run-time error this validation replaced.
        """
        assert KNOWN_PARSER_OPTIONS[parser_name] == frozenset(REAL_OPTIONS[parser_name])

    @pytest.mark.parametrize("parser_name", sorted(REAL_OPTIONS))
    def test_the_parser_really_accepts_every_listed_option(self, parser_name: str) -> None:
        """Construct it for real, with the parser's own default. The strongest form."""
        for option in KNOWN_PARSER_OPTIONS[parser_name]:
            build_parser(parser_name, {option: REAL_OPTIONS[parser_name][option]})


class TestPolicyIsExplicitForEveryBoolean:
    """`service/knobs.py` vs the parsers. Nothing is offered or withheld by silence."""

    @pytest.mark.parametrize("parser_name", sorted(REAL_OPTIONS))
    def test_every_boolean_is_either_offered_or_recorded_as_not_offered(
        self, parser_name: str
    ) -> None:
        """The gap an earlier draft had: `key_value.preserve_key` was in neither table.

        A reader could not tell whether it had been ruled out or overlooked. Adding a
        boolean to any parser now fails this test until somebody decides.
        """
        offered = OFFERABLE_PARSER_OPTIONS.get(parser_name, frozenset())
        withheld = CONSIDERED_AND_NOT_OFFERED.get(parser_name, frozenset())
        assert offered | withheld == real_booleans(parser_name)
        assert not (offered & withheld), "an option cannot be both offered and withheld"

    @pytest.mark.parametrize("parser_name", sorted(OFFERABLE_PARSER_OPTIONS))
    def test_nothing_non_boolean_is_offered(self, parser_name: str) -> None:
        """The `bool` annotation on the request model is only a guard if this holds."""
        assert OFFERABLE_PARSER_OPTIONS[parser_name] <= real_booleans(parser_name)

    def test_policy_never_offers_what_validity_does_not_know(self) -> None:
        for parser_name, options in OFFERABLE_PARSER_OPTIONS.items():
            assert options <= KNOWN_PARSER_OPTIONS[parser_name]

    def test_an_option_belongs_to_exactly_one_parser(self) -> None:
        """What lets the API report one parser per offered option without ambiguity.

        Also what makes the flat `OFFERED_OPTION_DEFAULTS` and `..._CAPTIONS` tables
        unambiguous: keying them by option name alone is only correct while this holds.
        """
        seen = [option for options in OFFERABLE_PARSER_OPTIONS.values() for option in options]
        assert len(seen) == len(set(seen))

    def test_the_reported_default_is_the_engines_own(self) -> None:
        """By **value**, against each parser's real `DEFAULT_OPTIONS` (ADR-0035).

        The control panel used to keep its own copy of `preserve_prefix: true`. It now
        renders what `GET /templates` reports, so a wrong value here would be a wrong
        checkbox — and, because the page sends every offered option explicitly, a
        saved configuration recording a default the engine no longer has.
        """
        assert set(OFFERED_OPTION_DEFAULTS) == OFFERABLE_OPTION_NAMES
        for parser_name, options in OFFERABLE_PARSER_OPTIONS.items():
            for option in options:
                assert OFFERED_OPTION_DEFAULTS[option] is REAL_OPTIONS[parser_name][option]

    def test_every_offered_option_has_a_caption(self) -> None:
        """So a third knob cannot ship as a bare toggle nobody can interpret.

        Server-side because `docs/19` requires these to describe the *shape of text an
        option suits* rather than to recommend one, and a caption a client writes is a
        caption nobody reviewed.
        """
        assert set(OFFERED_OPTION_CAPTIONS) == OFFERABLE_OPTION_NAMES
        for option, caption in OFFERED_OPTION_CAPTIONS.items():
            assert len(caption) > 40, option
            # The framing rule, as a blunt check: an option is a match for a shape of
            # text, never an improvement.
            lowered = caption.lower()
            for word in ("better", "improve", "recommended", "should enable"):
                assert word not in lowered, f"{option} caption recommends: {word}"


class TestTheTemplateMenu:
    @staticmethod
    def template(**extra: object) -> DatasetTemplate:
        return DatasetTemplate.model_validate(
            {
                "name": "t",
                "source": {"type": "csv", "path": "x.csv"},
                "destination": {"type": "csv", "path": "out/"},
                "columns": ["text"],
                **extra,
            }
        )

    def test_a_template_offers_nothing_by_default(self) -> None:
        """Opt-in, because the operator is the one who knows the shape of the text."""
        assert self.template().offered_parser_options() == ()

    def test_an_unofferable_option_is_refused_at_load(self) -> None:
        """The operator's typo is the operator's error, not the first caller's."""
        with pytest.raises(ValidationError, match="offerable parser option"):
            # A real transcript option, deliberately not offerable: it takes a list of
            # delimiters, so it is not a boolean.
            self.template(parser_options=["speaker_delimiters"])

    def test_an_option_no_offered_parser_accepts_is_refused_at_load(self) -> None:
        """An operator error deferred to a caller is still an operator error.

        Without this, a template offering `preserve_prefix` beside a `plain_text`-only
        parser list loads happily, advertises the option, and hands a 400 to every
        caller who picks it — one they cannot satisfy.
        """
        with pytest.raises(ValidationError, match="no parser this template offers"):
            self.template(parsers=["plain_text"], parser_options=["preserve_prefix"])

    def test_the_matching_pair_loads(self) -> None:
        template = self.template(parsers=["plain_text"], parser_options=["split_lines"])
        assert template.offered_parser_options() == ("split_lines",)


class TestTheRequestBoundary:
    """ADR-0034's line: a caller moves quality knobs, never privacy ones."""

    @staticmethod
    def request_models() -> list[type[ServiceModel]]:
        """Every request model, found by reflection rather than by a hand-written list.

        A hand-written list is how `RunRequest` came to be missing from an earlier
        draft of this test — which is exactly where "run this dataset, but write it
        over *there*" would be added.
        """
        return [
            value
            for name, value in vars(service_models).items()
            if isinstance(value, type)
            and issubclass(value, ServiceModel)
            and name.endswith(("Request",))
        ]

    def test_reflection_finds_the_request_models(self) -> None:
        names = {model.__name__ for model in self.request_models()}
        assert {"BuildConfigRequest", "ColumnRequest", "RunRequest"} <= names

    @pytest.mark.parametrize("field", PRIVACY_SWITCHES)
    def test_no_privacy_switch_is_a_field_on_any_request_model(self, field: str) -> None:
        for model in self.request_models():
            assert field not in model.model_fields, f"{model.__name__}.{field}"

    @pytest.mark.parametrize("field", PRIVACY_SWITCHES)
    def test_naming_one_anyway_is_refused_rather_than_ignored(self, field: str) -> None:
        """`extra="forbid"` — the difference between learning you cannot and believing
        you did."""
        with pytest.raises(ValidationError):
            service_models.ColumnRequest.model_validate(
                {"column": "text", "entities": ["PERSON"], field: "anything"}
            )

    @pytest.mark.parametrize("value", ["true", 1, [":"], {"a": 1}, None, ": ;--"])
    def test_a_non_boolean_option_value_never_reaches_the_builder(self, value: object) -> None:
        """The `bool` annotation is the guard against a free-form value.

        `1` and `"true"` are here deliberately: pydantic coerces some of these, and
        what matters is that nothing which is not boolean-shaped survives — a
        delimiter string or a path must not.
        """
        try:
            request = service_models.ColumnRequest(
                column="text",
                entities=("PERSON",),
                parser="plain_text",
                parser_options={"split_lines": value},
            )
        except ValidationError:
            return
        assert isinstance(request.parser_options["split_lines"], bool)
