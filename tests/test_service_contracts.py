"""The property that makes the service layer safe: its models cannot hold text.

ADR-0026's rule 2 is satisfied by absence rather than by filtering — "no endpoint
returns text" is true because no response model has a field that could carry any.
A filter is a thing that can be wrong; an absent field cannot. This module asserts
that, over **every** model in `service/models.py` discovered by reflection, so
adding one that could is a decision somebody has to make against a failing test
rather than a line nobody notices in review.

It also asserts the two import-boundary halves that the rung rule reduces to, and the
routing surface itself: no route whose path or name suggests it hands back content.
"""

from __future__ import annotations

import inspect
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Any, get_args, get_origin

import pytest
from fastapi.routing import APIRoute
from pydantic import BaseModel

from pii_reduction.service import models as service_models
from pii_reduction.service.api import create_app
from pii_reduction.service.runs import RunStore
from pii_reduction.service.runtimes.local import local_runtime

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[1]

#: Field names that would carry content rather than metadata. Substring matching, so
#: `sample_reduced`, `original_text` and `preview_rows` are all caught — the shapes
#: ADR-0026 names as the ones somebody adds the day before a demo.
#: Matched against the field name's underscore-separated **segments**, so
#: `started_at` and `entities_reduced` are not false positives while `sample_reduced`
#: and `span_start` are caught. A few are matched as substrings as well, because
#: `sampletext` and `previewrows` are the names somebody actually writes.
FORBIDDEN_SEGMENTS = (
    "text",
    "texts",
    "content",
    "contents",
    "sample",
    "samples",
    "preview",
    "excerpt",
    "snippet",
    "snippets",
    "value",
    "values",
    "body",
    "original",
    "originals",
    "raw",
    # Free prose is the other way content arrives — an unbounded string a developer
    # fills from an exception, a row, or a "helpful" detail.
    "message",
    "messages",
    "reason",
    "detail",
    "details",
    # `docs/09` governs span offsets and lengths at least as strictly as reduced
    # output: rendering *where* something was found renders part of the thing.
    "offset",
    "offsets",
    "span",
    "spans",
    "length",
    "lengths",
    # The offsets in this package are called `start` and `end`
    # (`contracts/spans.py`), so the words above would have missed them. Checked
    # against the current models: `started_at`, `submitted_at` and `completed_at`
    # split to `{started, at}` and friends, so none is a false positive.
    "start",
    "end",
    # `ProcessedFieldResult` names its relayed message `error` — so this is the
    # likeliest name for the one thing the design forbids, precisely because it is
    # the name of the field somebody would copy it from.
    "error",
    "errors",
)

#: Matched anywhere in the name, not only as a segment.
FORBIDDEN_SUBSTRINGS = ("text", "content", "sample", "preview", "excerpt", "snippet")

#: `config_yaml` is the one field that carries a document, and it is a *configuration*
#: document: every input to it came from a server-side template or from a request
#: model that itself cannot hold text. Exempted by name, with the reason, rather than
#: by loosening the rule.
EXEMPT_FIELDS = {
    # The generated configuration document. No token matches it, so this entry is
    # **defensive rather than triggered** — it is here so that a reader auditing the
    # exemption list sees the one field that holds a document and can check the
    # reasoning: every input to it is either server-side template data or a request
    # field that is pattern-bounded and checked against the template's menu, so it
    # cannot carry caller prose.
    ("BuiltConfigResponse", "config_yaml"),
    # A boolean: `AGENTS.md` rule 4's "are the original columns kept". It matches
    # "original" and carries nothing. Exempted by name rather than by narrowing the
    # token list, because "original" is exactly the word a leaking field would use.
    ("ColumnSummary", "preserve_original"),
    # The one free-prose field in the API. It carries a message this layer or the
    # configuration layer *composed* — never one relayed from below, which the
    # handlers in `api.py` reduce to a category. It is exempted rather than
    # forbidden because an API with no way to say what went wrong is worse; the
    # constraint lives in the handlers, and `test_service_layer.py` pins both the
    # non-echo of request bodies and the non-relay of engine messages.
    ("ErrorBody", "message"),
    # A category — a stable identifier this layer chose from a fixed set, never a
    # relayed message. It matches "error" for the same reason `error` is on the list.
    ("RunRecord", "error_category"),
    # The envelope's single key, holding an `ErrorBody` whose own `message` is
    # exempted above with the reasoning. Named here so the list shows every place
    # prose can reach a caller.
    ("ErrorResponse", "error"),
}


@contextmanager
def _app(ui: bool = True) -> Iterator[Any]:
    """The shipped configuration, with a store nothing submits to."""
    store = RunStore({"local": local_runtime})
    try:
        yield create_app(REPO_ROOT / "configs", store=store, ui=ui)
    finally:
        store.shutdown()


def _service_models() -> list[type[BaseModel]]:
    found = [
        obj
        for _, obj in inspect.getmembers(service_models, inspect.isclass)
        if issubclass(obj, BaseModel) and obj.__module__ == service_models.__name__
    ]
    # A reflection-based guard that finds nothing passes vacuously.
    assert len(found) >= 10, f"expected the service models, found {len(found)}"
    return found


class TestModelsCannotCarryText:
    def test_no_model_has_a_field_that_could_hold_content(self) -> None:
        offenders: list[str] = []
        for model in _service_models():
            for field_name in model.model_fields:
                if (model.__name__, field_name) in EXEMPT_FIELDS:
                    continue
                lowered = field_name.lower()
                segments = set(lowered.split("_"))
                matched = sorted(
                    {token for token in FORBIDDEN_SEGMENTS if token in segments}
                    | {token for token in FORBIDDEN_SUBSTRINGS if token in lowered}
                )
                if matched:
                    offenders.append(f"{model.__name__}.{field_name} (matched {matched})")
        assert offenders == [], (
            "a service model gained a field that could carry text (ADR-0026 rule 2). "
            f"If it genuinely cannot, exempt it by name with the reason: {offenders}"
        )

    def test_every_model_forbids_unknown_keys(self) -> None:
        # `extra="forbid"` is what makes the absence of a field a *refusal* rather
        # than a silently ignored key — the mechanism behind rule 4's "a caller
        # cannot name a source".
        loose = [
            model.__name__
            for model in _service_models()
            if model.model_config.get("extra") != "forbid"
        ]
        assert loose == [], f"models that would silently accept extra keys: {loose}"


class TestTheRoutingSurface:
    #: Routes that legitimately have no response model, by exact path and with the
    #: reason. The control panel (ADR-0035) serves one static asset compiled into the
    #: wheel — identical for every caller, interpolating nothing, and describing no
    #: contract a client codes against, which is why it is also out of the OpenAPI
    #: schema. Anything else appearing here is a metadata endpoint that lost its
    #: declared shape, which is the hole this test exists to keep shut.
    UI_ROUTES = frozenset({"/", "/ui"})

    def test_every_route_declares_a_response_model(self) -> None:
        """A route with no `response_model` is a route with no enforced shape.

        FastAPI serializes whatever the handler returns; the OpenAPI schema for such
        a path is `{}`. It is the one hole through which a metadata endpoint grows a
        field nobody declared.
        """
        with _app() as app:
            undeclared = [
                route.path
                for route in app.routes
                if isinstance(route, APIRoute)
                and route.response_model is None
                and route.path not in self.UI_ROUTES
            ]
        assert undeclared == [], f"routes with no response model: {undeclared}"

    def test_the_exempt_routes_are_only_the_control_panel(self) -> None:
        """The exemption must not quietly cover a route somebody adds next to it.

        Asserted as an equality against what the app actually exposes, so removing
        the UI or adding a third HTML route both fail here.
        """
        with _app() as app:
            exempt = {
                route.path
                for route in app.routes
                if isinstance(route, APIRoute) and route.response_model is None
            }
        assert exempt == self.UI_ROUTES

    def test_the_control_panel_is_absent_from_the_api_schema(self) -> None:
        """The schema describes the API. A page is not part of it."""
        with _app() as app:
            assert set(app.openapi()["paths"]) & self.UI_ROUTES == set()

    def test_the_service_can_be_started_without_it(self) -> None:
        """`--no-ui`: an HTML surface is a decision an operator may decline."""
        with _app(ui=False) as app:
            paths = {route.path for route in app.routes if isinstance(route, APIRoute)}
        assert paths & self.UI_ROUTES == set()
        # And the API is unchanged by its absence.
        assert "/health" in paths and "/configs" in paths

    def test_no_route_offers_content(self) -> None:
        with _app() as app:
            paths = {route.path for route in app.routes if isinstance(route, APIRoute)}
        forbidden = ("preview", "sample", "detect", "reduce", "download", "result", "rows", "text")
        offenders = [path for path in paths if any(token in path.lower() for token in forbidden)]
        assert offenders == [], (
            f"a route appeared whose shape ADR-0026 forbids by name: {offenders}"
        )

    def test_the_documented_endpoints_all_exist(self) -> None:
        """The complement of the test above: absence proves nothing on its own."""
        with _app() as app:
            paths = {route.path for route in app.routes if isinstance(route, APIRoute)}
        assert {
            "/health",
            "/entities",
            "/templates",
            "/datasets",
            "/datasets/{name}",
            "/configs",
            "/runs",
            "/runs/{run_id}",
        } <= paths


class TestRequestFieldTypesAreBounded:
    """The guard the name-based test above cannot be: what a field's *type* admits.

    `test_no_model_has_a_field_that_could_hold_content` matches field **names**
    against a forbidden vocabulary. That catches `text`, `body`, `content` — and is
    blind to a field called `parser_options` whose values are `str`, or `Any`, or
    `object`. ADR-0034 added the first `dict` to a request model, and the claim it
    rests on ("the annotation is the guard") was true of the runtime and pinned by
    nothing general.

    So: every leaf type reachable from a **request** model must be one a caller cannot
    put prose in. A bare `str` is allowed only with a `pattern` constraint, which is
    what bounds every name this API accepts. `Any` and `object` are never allowed.

    Responses are deliberately out of scope. They carry operator-authored
    configuration — paths, table types, error categories — which is bounded by
    `docs/09`'s *Safe to log* rule rather than by a pattern, and applying this rule to
    them would forbid `ErrorBody.message`.
    """

    #: Leaf types a request field may use. `bool`/`int`/`datetime`/`StrEnum` cannot
    #: hold prose; `str` is admitted only when a pattern constrains it (checked below).
    ALLOWED_LEAVES = (bool, int, float, str, datetime, type(None))

    @staticmethod
    def _request_models() -> list[type[BaseModel]]:
        found = [
            model
            for model in _service_models()
            if model.__name__.endswith("Request") and model.__name__ != "ServiceModel"
        ]
        assert len(found) >= 3, f"expected the request models, found {len(found)}"
        return found

    def _leaves(self, annotation: object) -> list[object]:
        """Every concrete type inside an annotation, unwrapping generics and unions.

        `Annotated[str, Field(...)]` is unwrapped to its **first** argument only: the
        rest are constraint objects, and treating them as types would report every
        pattern-constrained field as unbounded — the opposite of the truth.
        """
        origin = get_origin(annotation)
        if origin is None:
            return [annotation]
        args = get_args(annotation)
        if origin is Annotated:
            return self._leaves(args[0])
        return [leaf for arg in args for leaf in self._leaves(arg)]

    def test_no_request_field_admits_an_unbounded_value(self) -> None:
        offenders: list[str] = []
        for model in self._request_models():
            for field_name, field in model.model_fields.items():
                for leaf in self._leaves(field.annotation):
                    if isinstance(leaf, type) and issubclass(leaf, (StrEnum, BaseModel)):
                        continue
                    if leaf is Ellipsis or leaf is None:
                        continue
                    if leaf not in self.ALLOWED_LEAVES:
                        offenders.append(f"{model.__name__}.{field_name}: {leaf!r}")
        assert offenders == [], (
            "a request model gained a field whose type admits an unbounded value "
            "(ADR-0034 rule 1: a caller's choice is a selection, never a free-form "
            f"value). Bound it, or extend ALLOWED_LEAVES with the reason: {offenders}"
        )

    def test_every_string_a_request_accepts_is_pattern_bounded(self) -> None:
        """A bare `str` in a request is the shape ADR-0034 rule 1 exists to prevent.

        Every string this API accepts is a *name* — of a template, a dataset, a
        column, an entity label, a run id — and each is pattern-checked. A `str` with
        no pattern would be the first one that is not.
        """
        unbounded: list[str] = []
        for model in self._request_models():
            for field_name, field in model.model_fields.items():
                if str not in self._leaves(field.annotation):
                    continue
                constrained = self._has_pattern(field.metadata) or self._nested_pattern(
                    field.annotation
                )
                if not constrained:
                    unbounded.append(f"{model.__name__}.{field_name}")
        assert unbounded == [], f"request string field(s) with no pattern constraint: {unbounded}"

    @staticmethod
    def _has_pattern(metadata: object) -> bool:
        """True when a metadata entry carries a regex constraint.

        Pydantic v2 wraps `Field(pattern=...)` in `_PydanticGeneralMetadata`, whose
        `pattern` attribute holds the expression — reached through `FieldInfo.metadata`
        rather than sitting on the annotation. Read by attribute rather than by type so
        an internal rename degrades to "unconstrained" (a failing test) instead of to
        "constrained" (a silent pass).
        """
        for entry in metadata if isinstance(metadata, (list, tuple)) else ():
            if getattr(entry, "pattern", None) is not None:
                return True
        return False

    @classmethod
    def _nested_pattern(cls, annotation: object) -> bool:
        """True when a pattern sits on an `Annotated[str, Field(pattern=...)]` inside.

        A tuple item and a dict key carry their constraint on the inner annotation
        rather than on the outer field, which is where `entities` and `parser_options`
        put theirs.
        """
        for arg in get_args(annotation):
            for meta in get_args(arg)[1:]:
                if cls._has_pattern(getattr(meta, "metadata", None)):
                    return True
            if cls._nested_pattern(arg):
                return True
        return False
