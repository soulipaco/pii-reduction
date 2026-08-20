"""Session construction: profile, environment, or ambient — never a hard-coded host.

Four routes are supported, because workspaces differ in which ones they permit.
:func:`resolve_auth_route` tries them in **this** order — which is not the order they
are introduced below, and the difference is deliberate; see its docstring:

1. **An explicit ``profile=`` argument** — someone saying what they want, so it wins
   outright.
2. **Ambient compute credentials**, when the process is already running on Databricks
   (a notebook or a job): the runtime authenticates itself, and an existing session
   is reused rather than a second one built through Connect.
3. **A named CLI profile** in ``DATABRICKS_CONFIG_PROFILE``. The nicest of the
   credential-carrying routes where it is available: credentials live in the CLI's
   auth store and rotate without touching this project.
4. **Environment credentials** — ``DATABRICKS_HOST`` plus either ``DATABRICKS_TOKEN``
   or an OAuth service principal
   (``DATABRICKS_CLIENT_ID``/``DATABRICKS_CLIENT_SECRET``). This is the route for
   organisations whose policy blocks the Databricks CLI, where a personal access
   token or a service principal is the only option (session 10; ADR-0006 always
   allowed "CLI profiles **or env**", this implements the second half).

What does **not** change with the route: this module has no ``host`` or ``token``
parameter, and it never will. A signature that accepted a secret invites committing
one (`AGENTS.md` rule 1), and a value passed as an argument ends up in tracebacks,
shell history and job definitions. Credentials reach the SDK the way the SDK already
reads them — from the environment — and this module only decides whether enough of
them are present to try, then says so in terms of variable *names*, never values.
"""

from __future__ import annotations

import os
from typing import Any, Literal

from pii_reduction.databricks.errors import DatabricksError, require_spark_session

__all__ = ["AuthRoute", "get_session", "resolve_auth_route"]

PROFILE_ENV = "DATABRICKS_CONFIG_PROFILE"
SERVERLESS_ENV = "DATABRICKS_SERVERLESS_COMPUTE_ID"
HOST_ENV = "DATABRICKS_HOST"
TOKEN_ENV = "DATABRICKS_TOKEN"
CLIENT_ID_ENV = "DATABRICKS_CLIENT_ID"
CLIENT_SECRET_ENV = "DATABRICKS_CLIENT_SECRET"
#: Set by the Databricks runtime itself; its presence means the process is running
#: on compute that can authenticate without any credential of ours.
RUNTIME_ENV = "DATABRICKS_RUNTIME_VERSION"

#: The route that will be used. A label, never a credential — safe to log, print and
#: record in a run's metadata. A closed set rather than ``str`` so a typo in a
#: comparison is a type error instead of a silently-false branch.
AuthRoute = Literal["profile", "env_token", "env_oauth", "ambient"]


def _has(name: str) -> bool:
    """Whether an environment variable holds something. The value is never read out."""
    return bool(os.environ.get(name))


def resolve_auth_route(profile: str | None = None) -> tuple[AuthRoute, str | None]:
    """Pick an authentication route, or refuse with the options spelled out.

    Returns the route's name and the profile to use (``None`` for the routes that do
    not use one). Separated from :func:`get_session` so the decision is testable
    without Databricks Connect installed and without any credential present.

    **Order matters, and ambient beats an inherited profile.** An explicit
    ``profile=`` argument is someone saying what they want, so it wins outright.
    After that, running *on* Databricks decides: a ``DATABRICKS_CONFIG_PROFILE``
    inherited into a notebook's environment would otherwise route a process that
    already has a session through Connect, and make it set a serverless compute
    override the runtime never asked for.
    """
    if profile:
        return "profile", profile
    if _has(RUNTIME_ENV):
        return "ambient", None
    chosen = os.environ.get(PROFILE_ENV)
    if chosen:
        return "profile", chosen
    if _has(HOST_ENV) and _has(TOKEN_ENV):
        return "env_token", None
    if _has(HOST_ENV) and _has(CLIENT_ID_ENV) and _has(CLIENT_SECRET_ENV):
        return "env_oauth", None
    raise DatabricksError(
        "no Databricks credentials found. Use whichever your workspace permits: "
        f"(1) a CLI profile — set {PROFILE_ENV} or pass profile=, listed by "
        "`databricks auth profiles`; "
        f"(2) environment credentials — {HOST_ENV} plus {TOKEN_ENV}, or {HOST_ENV} "
        f"plus {CLIENT_ID_ENV}/{CLIENT_SECRET_ENV} for a service principal, which is "
        "the route to use where policy blocks the CLI; "
        "(3) nothing at all, when running on Databricks compute, which authenticates "
        "itself. Set these in your shell or a secret store — never in a config file, "
        "a notebook cell, or this repository (AGENTS.md rule 1)"
    )


def get_session(profile: str | None = None, *, serverless: bool = True) -> Any:
    """A ``DatabricksSession`` built from whichever credentials are available.

    There is deliberately no host or token parameter — see the module docstring.

    ``serverless=True`` targets serverless compute, which is the only compute a
    serverless-only workspace has. The environment variable route is used rather
    than a builder API so the same code works across the Connect client generations
    the dedicated venv may hold (15.x and 16.x behave differently here). It is left
    alone when the process is already running on Databricks, where the runtime has
    chosen the compute and overriding it would be wrong.
    """
    route, chosen = resolve_auth_route(profile)
    if route == "ambient":
        # On Databricks the runtime has already built a session and chosen the
        # compute. Reusing it is what makes route 3 genuinely "nothing at all":
        # without this, running here would still require Databricks Connect to be
        # importable, which is not something a notebook or job should have to
        # arrange. Falls through when there is somehow no active session.
        active = _active_session()
        if active is not None:
            return active
    if chosen is not None:
        os.environ[PROFILE_ENV] = chosen
    if serverless and route != "ambient":
        os.environ.setdefault(SERVERLESS_ENV, "auto")
    session_builder = require_spark_session().builder
    return session_builder.getOrCreate()


def _active_session() -> Any | None:
    """The session this process already has, if any.

    Imported inside the function so that importing this package never pulls in
    ``pyspark`` — ``tests/test_package.py`` asserts exactly that in a subprocess.
    """
    try:
        from pyspark.sql import SparkSession
    except ImportError:
        return None
    return SparkSession.getActiveSession()
