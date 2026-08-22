"""ADR-0035: the control panel, and the properties that keep it a *client*.

The page itself is not unit-testable in a useful sense — it is a browser program, and
it was driven in a real browser during the increment. What *is* testable, and what
matters when somebody edits it six months from now, is the set of claims the ADR makes
about it:

* it ships inside the wheel, so a Databricks App that installs the package gets it;
* it makes no external request, so it loads where there is no egress;
* it reads no template, interpolates nothing, and is byte-identical for every caller;
* it is optional, and turning it off leaves the API exactly as it was;
* it adds no endpoint that returns data.

Default tier: reading a file and inspecting an ASGI app. No models, no browser.
"""

from __future__ import annotations

import re
import subprocess
import sys
import zipfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from pii_reduction.service.api import create_app
from pii_reduction.service.cli import main
from pii_reduction.service.runs import RunStore
from pii_reduction.service.runtimes.local import local_runtime

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[1]
PAGE = REPO_ROOT / "src" / "pii_reduction" / "service" / "static" / "index.html"

#: Anything that would make the browser fetch from somewhere other than this service.
#: `//host` is included because a protocol-relative URL is the one that looks local.
EXTERNAL_REFERENCE = re.compile(r"""(?:src|href)\s*=\s*["'](?:https?:)?//""", re.IGNORECASE)

#: Client-side persistence. The page holds nothing between loads, so a shared browser
#: cannot leak one operator's dataset names to the next person at the machine.
PERSISTENCE = ("localStorage", "sessionStorage", "document.cookie", "indexedDB")


def executable_source() -> str:
    """The page with its comments removed.

    The comments explain *why* `innerHTML` and `localStorage` are not used, so a naive
    substring scan finds the very words it is looking for and fails on the explanation.
    Stripping them is what makes these assertions about the program rather than about
    the prose. Truncating at `//` is safe because `test_it_makes_no_external_request`
    asserts the raw source contains no `://` **at all** — not merely no `src`/`href`
    attribute pointing at one, which would have made this justification circular.
    """
    source = PAGE.read_text(encoding="utf-8")
    source = re.sub(r"<!--.*?-->", "", source, flags=re.DOTALL)
    source = re.sub(r"/\*.*?\*/", "", source, flags=re.DOTALL)
    return re.sub(r"//.*", "", source)


@contextmanager
def app(ui: bool = True) -> Iterator[Any]:
    store = RunStore({"local": local_runtime})
    try:
        yield create_app(REPO_ROOT / "configs", store=store, ui=ui)
    finally:
        store.shutdown()


@pytest.fixture
def client() -> Iterator[TestClient]:
    with app() as built, TestClient(built) as test_client:
        yield test_client


class TestThePageItself:
    def test_it_exists_and_is_one_file(self) -> None:
        assert PAGE.is_file()
        assert PAGE.parent.name == "static"

    def test_it_makes_no_external_request(self) -> None:
        """A Databricks App may have no egress, and a CDN is a supply chain.

        This is the property that makes the page load in the environment it was
        written for — and the one an "just add a chart library" edit would break.
        """
        source = PAGE.read_text(encoding="utf-8")
        # **The strong form, and the one the property actually needs.** An attribute
        # scan misses `fetch("https://…")`, `new Image().src = …`, a CSS `url()` and an
        # `@import`. The page contains no scheme separator at all, which forbids every
        # one of them at once — and is what makes `executable_source()`'s `//` stripping
        # safe rather than circular.
        assert "://" not in source, "the page gained a URL"
        assert EXTERNAL_REFERENCE.search(source) is None
        for token in ("cdn.", "unpkg", "jsdelivr", "googleapis", "fonts.g"):
            assert token not in source, f"external dependency: {token}"

    def test_there_is_exactly_one_place_it_can_reach_the_network(self) -> None:
        """One `fetch`, inside the `api()` helper, which only ever takes a relative path.

        A second call site is not wrong in itself — it is the thing to *look at*, and a
        failure here is the review prompt.
        """
        source = executable_source()
        assert source.count("fetch(") == 1, "network access should go through api()"
        assert "XMLHttpRequest" not in source
        assert "sendBeacon" not in source
        assert "EventSource" not in source
        assert "WebSocket" not in source

    def test_it_stores_nothing_on_the_client(self) -> None:
        source = executable_source()
        for token in PERSISTENCE:
            assert token not in source, f"client-side persistence: {token}"

    def test_it_never_assigns_api_values_as_markup(self) -> None:
        """`innerHTML` is how a service that returns no text still executes a string.

        The page builds every node with `textContent`. This is a blunt instrument —
        it forbids the API outright — and that is the point: there is no case here
        where markup assignment is the right tool, so the rule needs no judgement.
        """
        source = executable_source()
        for token in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write"):
            assert token not in source, f"markup assignment: {token}"

    def test_it_evaluates_nothing(self) -> None:
        source = executable_source()
        assert "eval(" not in source
        assert "new Function" not in source


class TestItIsServed:
    def test_both_paths_answer_with_the_page(self, client: TestClient) -> None:
        for path in ("/", "/ui"):
            response = client.get(path)
            assert response.status_code == 200, path
            assert response.headers["content-type"].startswith("text/html")
            assert "<title>PII reduction" in response.text

    def test_what_is_served_is_what_is_on_disk(self, client: TestClient) -> None:
        """Byte-identical, so "it interpolates nothing" is a fact rather than a habit.

        A page assembled per request is a page that could assemble a caller's input
        into itself; this one cannot, because it is never assembled.
        """
        assert client.get("/ui").text == PAGE.read_text(encoding="utf-8")

    def test_it_is_identical_for_every_caller(self, client: TestClient) -> None:
        first = client.get("/ui", headers={"x-forwarded-user": "someone"})
        second = client.get("/ui", headers={"x-forwarded-user": "someone-else"})
        assert first.text == second.text

    def test_the_api_is_unchanged_when_it_is_off(self) -> None:
        with app(ui=False) as built, TestClient(built) as client:
            assert client.get("/ui").status_code == 404
            assert client.get("/").status_code == 404
            assert client.get("/health").status_code == 200
            assert client.get("/templates").status_code == 200

    def test_it_is_resolved_from_the_package_not_the_repository(self) -> None:
        """A Databricks App runs from an arbitrary working directory.

        A page found relative to the *repository* would 500 there. This asserts the
        resolution rule only — under an editable install it compares the file to
        itself, which is why the wheel is checked separately below.
        """
        import pii_reduction.service as service_package

        installed = Path(service_package.__file__).parent / "static" / "index.html"
        assert installed.is_file()
        assert installed.read_text(encoding="utf-8") == PAGE.read_text(encoding="utf-8")

    @pytest.mark.packaging
    def test_it_is_actually_inside_a_built_wheel(self, tmp_path: Path) -> None:
        """The claim ADR-0035 rests on, checked against a real wheel.

        `pyproject.toml` declares the asset explicitly, but hatchling's file selection
        also honours `.gitignore` — so an ordinary ignore line could drop it with every
        other test still green, and the failure would surface as a hosted App that
        fails to start. Marked `packaging` because it shells out to the build backend;
        the default tier stays fast.
        """
        subprocess.run(
            [sys.executable, "-m", "build", "--wheel", "--outdir", str(tmp_path), str(REPO_ROOT)],
            check=True,
            capture_output=True,
        )
        wheels = sorted(tmp_path.glob("*.whl"))
        assert wheels, "no wheel was built"
        with zipfile.ZipFile(wheels[-1]) as built:
            assert "pii_reduction/service/static/index.html" in built.namelist()
            packaged = built.read("pii_reduction/service/static/index.html").decode("utf-8")
        assert packaged == PAGE.read_text(encoding="utf-8")


class TestItAddsNoDisclosure:
    def test_it_introduces_no_endpoint_that_could_return_data(self, client: TestClient) -> None:
        """The page is the only thing the UI adds. Everything else it shows, it fetches.

        `POST /ui` and friends must not exist — a page route that accepted anything
        would be an inbound surface nobody declared.
        """
        for path in ("/", "/ui"):
            for method in ("post", "put", "patch", "delete"):
                assert getattr(client, method)(path).status_code == 405, f"{method} {path}"

    def test_the_page_refuses_to_be_framed(self, client: TestClient) -> None:
        """The panel has two state-changing controls, so clickjacking is the risk.

        A cross-site form cannot reach `POST /configs` or `POST /runs` — both need a
        JSON body, which triggers a preflight — but a hostile page could frame the
        panel and overlay it, and on a hosted App the platform's cookie is sent
        automatically. One tricked click would then trigger a run under the service's
        own credentials, which is the confused-deputy shape ADR-0026 exists to prevent
        arriving through the browser instead of the request body.
        """
        for path in ("/", "/ui"):
            headers = client.get(path).headers
            assert headers["x-frame-options"] == "DENY", path
            assert "frame-ancestors 'none'" in headers["content-security-policy"], path

    def test_the_no_egress_property_is_enforced_by_the_browser_too(
        self, client: TestClient
    ) -> None:
        """`connect-src 'self'` makes it a runtime rule, not only a grep assertion."""
        policy = client.get("/ui").headers["content-security-policy"]
        assert "default-src 'self'" in policy
        assert "connect-src 'self'" in policy
        assert "form-action 'none'" in policy
        assert client.get("/ui").headers["x-content-type-options"] == "nosniff"

    def test_it_is_absent_from_the_openapi_document(self, client: TestClient) -> None:
        paths = set(client.get("/openapi.json").json()["paths"])
        assert "/ui" not in paths and "/" not in paths

    def test_every_path_it_fetches_is_a_declared_api_path(self, client: TestClient) -> None:
        """What the page calls must be what the API documents.

        Extracted from the source rather than assumed, so a page that starts calling
        an undocumented path fails here. This is also how a reviewer sees, without
        reading the JavaScript, exactly which endpoints the UI can reach.
        """
        source = PAGE.read_text(encoding="utf-8")
        called = {match.group(1) for match in re.finditer(r'api\("(/[a-z]*)', source)}
        declared = set(client.get("/openapi.json").json()["paths"])
        # `/runs/{id}` and `/datasets/{name}` are built by concatenation, so the
        # extracted prefix is the collection path — which is declared either way.
        assert called, "no API calls found; the extraction pattern has drifted"
        assert called <= declared, f"page calls undeclared path(s): {sorted(called - declared)}"


class TestTheFlagReachesTheApp:
    """`--no-ui` is the operator's only control over whether an HTML surface exists.

    Every other test here calls `create_app(ui=...)` directly, so a regression that
    dropped `ui=args.ui` from the CLI's own `create_app` call would leave the whole
    suite green and ship a panel to a deployment that asked for none. These drive
    `main()` with the serve step injected, which is where that wiring actually lives.
    """

    @staticmethod
    def served_app(*flags: str) -> Any:
        captured: dict[str, Any] = {}
        exit_code = main(
            ["--configs", str(REPO_ROOT / "configs"), *flags],
            serve=lambda built, **_: captured.update(app=built),
        )
        assert exit_code == 0
        return captured["app"]

    @staticmethod
    def paths(built: Any) -> set[str]:
        return {route.path for route in built.routes if isinstance(route, APIRoute)}

    def test_the_default_serves_the_panel(self) -> None:
        assert {"/", "/ui"} <= self.paths(self.served_app())

    def test_no_ui_does_not(self) -> None:
        served = self.paths(self.served_app("--no-ui"))
        assert served & {"/", "/ui"} == set()
        assert {"/health", "/configs", "/runs"} <= served
