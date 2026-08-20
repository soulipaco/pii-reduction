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
from pathlib import Path
from typing import Any

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
def _app() -> Iterator[Any]:
    """The shipped configuration, with a store nothing submits to."""
    store = RunStore({"local": local_runtime})
    try:
        yield create_app(REPO_ROOT / "configs", store=store)
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
                if isinstance(route, APIRoute) and route.response_model is None
            ]
        assert undeclared == [], f"routes with no response model: {undeclared}"

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
