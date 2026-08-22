# ADR-0035: The control panel ships with the service, as one static file

**Status:** accepted · **Date:** 2026-08-22 · **Session:** 14

## Context

ADR-0026 ruled that rung 4 is a thin HTTP API and that **a UI is a client of it**. That
was the right call and it is not reversed here. But "a UI is a client" left a gap
nobody named: *which* client, shipped by whom, and does one exist at all?

Without one, the platform's usable surface is `curl` and the OpenAPI page. ADR-0034 has
just made the engine's accuracy knobs reachable through the API — and a knob nobody can
see is not much better than a knob that is not there. The templates declare menus
precisely so a picker can render them; nothing rendered them.

There is also a smaller thing worth stating, because it is the first surface someone
new to this project meets: `GET /docs` already exists. FastAPI generates it from the
same models that validate the requests, and it is genuinely useful. It also **loads
Swagger UI from a CDN**, so it is blank on a deployment with no egress, and it is
third-party JavaScript running on an origin that can call this API. That is a fine
default for a development tool and a poor one for the only front door.

## Decision

**Ship a control panel inside the package: one static HTML file, served by the same
FastAPI process at `/` and `/ui`, on by default and disableable with `--no-ui`.**

It remains a *client* in the sense ADR-0026 meant. It holds no logic the API does not,
it computes nothing, and every value it shows it fetched from an endpoint a `curl` user
can call. What changes is that the client now ships with the thing it is a client of,
so hosting the service hosts a usable surface.

### Five properties, each with a reason and a test

| property | why | pinned by |
|---|---|---|
| **One file, no build step** | a Databricks App runs a Python process — no npm, no bundler. A page needing either does not exist where it matters most | a `packaging`-marked test **builds a wheel and reads the asset out of it**, byte-compared to the source, and CI runs it on every push |
| **No external request** | no CDN, no font host, no framework. A deployment with no egress renders it fully, and there is no third-party JavaScript on an origin that can call this API | the page contains no `://` **at all** and exactly one `fetch(`; `connect-src 'self'` makes the browser enforce it too |
| **Byte-identical for every caller** | read once at startup and served verbatim. A page that is *assembled* is a page that could assemble a caller's input into itself | a test compares the response to the file, and two responses with different headers to each other |
| **`textContent`, never `innerHTML`** | a configuration value is not markup. This is how a service that returns no text still manages to execute somebody's string | a test forbids `innerHTML`, `outerHTML`, `insertAdjacentHTML`, `document.write`, `eval`; and `el()` **throws** on `href`, `src`, `style` or any `on*` attribute, so the sink cannot be reached even by an edit |
| **No client-side storage** | no `localStorage`, no cookies, no history entries carrying a name. A shared browser cannot leak one operator's dataset names to the next person at the machine | a test forbids the storage APIs |
| **It remembers nothing the server knows** | a client that keeps its own copy of a default silently overrides one when it changes — and because the page sends every offered option explicitly, that copy would be written into saved configurations | `GET /templates` reports each option's engine default **and its caption**; both are pinned against the parsers by value, and the page renders what it is told |

### Serving markup is not "returning text"

`docs/09` and `AGENTS.md` rule 8 govern **source text, reduced text and detected
values**. This route returns a static asset compiled into the wheel — identical for
every caller, interpolating nothing, carrying no data from any dataset. The distinction
is not a loophole, and the test suite is what keeps it from becoming one: byte-identity
with the on-disk file means the route *cannot* carry a value even if someone later
wanted it to.

The page then displays exactly what the API returns to the same browser — and the API
returns no text, enforced by a reflection test over every model. **So the page cannot
show data even by mistake: there is nothing to show.**

One clause of precision on that, because it is otherwise one shade too absolute:
`ErrorBody.message` is the API's single exempted free-prose field, and the page renders
it into the error banner. It is composed by the service layer rather than read from a
dataset — but the property there comes from handler discipline (the 422 handler
substitutes `<key>` for any caller-supplied path segment; unexpected exceptions are
reported by category), pinned in `tests/test_service_layer.py`, not from the absence of
a field. Everything else on the page is absence.

### It is optional, and the API does not depend on it

`create_app(..., ui=False)` and `pii-reduction-service --no-ui`. An HTML surface is a
decision an operator may decline — for a deployment that is purely an integration
point, or one whose review has not covered a browser surface. A test asserts the API is
unchanged in that mode.

**On by default**, because the alternative is a hosted service whose front door is
`curl`, and the point of hosting was to have a front door.

### It is exempt from the response-model guard, by exact path

`tests/test_service_contracts.py` requires every route to declare a `response_model` —
the guard that stops a metadata endpoint growing an undeclared field. The two page
routes are exempt **by exact path**, with a companion test asserting the exempt set is
*equal* to `{"/", "/ui"}`, so a third route added beside them fails rather than
inheriting the exemption.

## Consequences

- **Hosting rung 4 now delivers something a person can use.** The App start command is
  unchanged; the page comes with the wheel. Verified in the wheel build:
  `pii_reduction/service/static/index.html` is present.
- **Local and hosted are the same surface.** `pii-reduction-service --configs configs`
  then a browser at `127.0.0.1:8000` is exactly what the App serves. ADR-0025 keeps
  local a hard constraint, and this does not weaken it — there is no build step to run,
  no asset server, and no environment difference.
- **ADR-0034's knobs are visible**, with the honest framing attached — and the framing
  is **server-side**, in `service/knobs.py`, because a caption a client writes is a
  caption nobody reviewed. Each describes the *shape of text an option suits* and names
  the error it trades for; a test asserts every offered option has one and that none of
  them says "better", "improve" or "recommended". The entity table marks `ADDRESS` as
  detected by nothing, read from the API's own `detected_at_baseline` rather than from a
  hardcoded label (ADR-0002).
- **`/docs` stays**, and its CDN dependency is now documented rather than assumed. Two
  surfaces with different properties: the generated one is complete and needs egress;
  this one is partial and needs nothing.
- **Editing the page requires a restart**, because it is read once at startup like the
  configuration. Correct for a deployment, mildly annoying while developing it — the
  reason is that a per-request read turns a deleted file into a 500 on somebody's first
  visit rather than a service that refuses to start.
- **A browser client changes nothing about authentication, and that is worth stating.**
  The page has none, exactly like the API it calls. It is safe today for reasons that
  should not be assumed: the API is JSON-only, so a cross-origin `POST` triggers a
  preflight and no CORS middleware is installed; the app reads no cookie of its own.
  What a browser *does* add is framing, so the page is served with
  `frame-ancestors 'none'` and `X-Frame-Options: DENY` — without them a hostile page
  could overlay a framed panel and turn one tricked click from an authenticated
  operator into a run under the service's credentials. `connect-src 'self'` in the same
  policy makes the no-external-request property something the browser enforces rather
  than only something a test asserts about the file.
- **What a hosted panel shows is what a `curl` user could already read**, with a change
  of audience worth an operator's attention: the run history is process-wide and each
  run carries its destination paths. Recorded in `docs/19` with the two consequences.
- **It is a browser program, and browser programs are not unit-tested here.** The page
  was driven in a real browser during the increment: build a config with `split_lines`,
  save it, trigger a run, watch it reach `succeeded` over 102 rows; then again with
  `transcript` and `preserve_prefix: false`. Two rendering defects were found that way
  and only that way — a nested `outputs` object rendering as `[object Object]`, and a
  timestamp column reading a field name that does not exist.

## What would reopen this

- **A page that needs a framework.** If the panel grows past what vanilla JS carries
  comfortably, the honest move is a build step and a bundled asset — not a CDN. The
  no-external-request property is the one to preserve; "one file" is the current means.
- **Authentication.** The page has none, exactly like the API it calls: the bind
  address is the control locally, and the platform authenticates in front of it when
  hosted. A UI does not change that, and must not appear to.
- **Anything that would display data.** A side-by-side original/reduced view is the
  obvious request and it is governed: `docs/09` states seven conditions, one of which
  hosting was **measured** not to meet (`docs/19` — the App authorizes as its own
  service principal). It needs its own ADR, and this one does not create a precedent
  for it.

## Alternatives rejected

- **No UI at all — leave it to a client somebody else writes.** That is ADR-0026's
  letter, and after hosting it is the wrong reading: the service had no front door, and
  "somebody could write one" is not a front door.
- **A separate front-end project with a build step.** It would need npm in a
  Databricks App, a second deployment artifact, and a version skew between page and
  API that nothing checks. The page is a client of an API that already validates every
  request; a build pipeline buys nothing here.
- **Swagger UI (`/docs`) as the only surface.** It is an API explorer, not a control
  panel — it shows every field with equal weight, cannot render a template's menu as a
  picker, has nowhere to put "this option suits line-structured text, not prose", and
  needs a CDN.
- **`StaticFiles` mounted on a directory.** It serves *whatever is in the directory*,
  which is a different and weaker property than serving one known file. A single
  in-memory string cannot be made to serve something nobody put there deliberately.
- **Server-side templating (Jinja).** It would make the page a function of request
  state, which is precisely the property this ADR spends a test proving it does not
  have.
