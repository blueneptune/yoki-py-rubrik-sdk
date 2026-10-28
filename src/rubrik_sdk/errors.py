"""Exceptions this SDK raises on top of sdk-primer's.

Transport failures - a refused login, a 404, a timeout, a 503 after the
retries - arrive as sdk_primer's own types (AuthenticationError,
NotFoundError, NetworkError, ServerError, ...), all SDKError. These are
the Rubrik-specific ones; they are SDKError too, so one `except SDKError`
catches everything a call can fail with.
"""

from __future__ import annotations

from typing import Any

from sdk_primer import SDKError


class RubrikError(SDKError):
    """Rubrik answered, and the answer was not usable."""


class GraphQLError(RubrikError):
    """RSC answered 200 OK with a top-level `errors` array: the request
    reached GraphQL and was refused there - a field the schema does not
    have, a bad variable, no permission for the object - rather than
    failing on the way."""

    def __init__(self, errors: list[dict[str, Any]], operation_name: str | None = None) -> None:
        self.errors = errors
        self.operation_name = operation_name
        messages = "; ".join(str(error.get("message", error)) for error in errors)
        where = f" in {operation_name}" if operation_name else ""
        super().__init__(f"RSC returned {len(errors)} GraphQL error(s){where}: {messages}")


class ChangesNotAllowed(RubrikError):
    """A call that would alter Rubrik (a mutation) was made on a client
    that was not built with allow_changes=True."""
