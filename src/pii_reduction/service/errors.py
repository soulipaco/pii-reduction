"""Service-layer errors, and the categories they present to a caller.

Every message here is written to be shown to whoever called the API, so the rule that
governs it is `AGENTS.md` rule 8 as `docs/09` now extends it: a message may name a
dataset, a template, a column, a run id or an error category, and may not carry
source text, reduced text or a detected value. That is the same discipline the rest
of the package applies to log records — the difference is only that the audience is
further away.

``category`` exists so the API can answer with a stable machine-readable string
instead of a class name that a refactor can rename.
"""

from __future__ import annotations

from pii_reduction.contracts.errors import PiiReductionError

__all__ = [
    "InvalidRequestError",
    "RunJournalError",
    "RunNotFoundError",
    "RuntimeUnavailableError",
    "ServiceError",
    "UnknownDatasetError",
    "UnknownTemplateError",
]


class ServiceError(PiiReductionError):
    """Root of the service layer's own errors."""

    #: Stable identifier for the failure, safe to return over HTTP.
    category = "service_error"
    #: The status code the API answers with.
    status_code = 400


class UnknownTemplateError(ServiceError):
    category = "unknown_template"
    status_code = 404


class UnknownDatasetError(ServiceError):
    category = "unknown_dataset"
    status_code = 404


class RunNotFoundError(ServiceError):
    category = "unknown_run"
    status_code = 404


class InvalidRequestError(ServiceError):
    """A request the models accepted but the server-side policy refuses.

    Distinct from a schema violation, which the framework answers with a 422: this is
    "you named a column this template does not offer", which is a policy decision
    rather than a malformed body.
    """

    category = "invalid_request"
    status_code = 400


class RuntimeUnavailableError(ServiceError):
    """The named execution runtime is not wired into this process.

    The Databricks runtime is only present when the service was started with it, and
    it needs an extra that the core install does not carry — so "not available" is a
    deployment fact, not a bug, and says so.
    """

    category = "runtime_unavailable"
    status_code = 409


class RunJournalError(ServiceError):
    """The durable run journal cannot be read or written.

    A 500 rather than a 4xx: nothing the caller did caused it, and it is not something
    a caller can correct. It is deliberately **not** swallowed — a service that
    silently stops persisting run state answers 404 for real runs after the next
    restart, which is the failure this journal exists to remove.
    """

    category = "run_journal_unavailable"
    status_code = 500
