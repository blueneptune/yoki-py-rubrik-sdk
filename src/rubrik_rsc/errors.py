"""Exceptions raised by this SDK.

Kept in their own module (rather than on `client.py`/`auth.py`) so any part
of the SDK can raise/catch them without risking an import cycle back to the
module that happens to define the transport or auth logic.
"""

from __future__ import annotations

from typing import Any


class GraphQLError(Exception):
    """Raised when the RSC GraphQL API responds 200 OK but includes a
    top-level `errors` array in the response body - GraphQL's way of
    reporting application-level failures (bad variables, permission denied,
    a field that doesn't resolve, ...) separately from HTTP transport
    failures, which raise via `response.raise_for_status()` instead.
    """

    def __init__(self, errors: list[dict[str, Any]]) -> None:
        self.errors = errors
        messages = "; ".join(str(error.get("message", error)) for error in errors)
        super().__init__(f"GraphQL API returned {len(errors)} error(s): {messages}")


class RscAuthError(Exception):
    """Raised when exchanging a service account's credentials for a bearer
    token fails or the token endpoint responds in an unexpected shape."""
