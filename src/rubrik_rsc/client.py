"""The transport layer: a single class, `RscClient`, that knows how to POST
GraphQL documents to one RSC instance (its base URL, bearer token, timeout,
and where its logs go).

Nothing here knows about clusters, SLA domains, or any other domain - that's
the whole point, same as `APIClient` in a REST-flavoured SDK. `RscClient`
only understands "send this GraphQL document and these variables, hand back
the `data` object, raise if the response carries GraphQL errors". Domain
facades (`cluster.py`, `sla_domain.py`) are handed an `RscClient` to use
rather than reaching for one on their own - dependency injection, so two
`RscClient`s pointed at two different RSC instances never interfere with
each other, and tests just build a throwaway client instead of mutating
shared state.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import httpx
from loguru import logger as _default_logger

from .errors import GraphQLError

if TYPE_CHECKING:
    # loguru's `Logger` class only exists in its type stub, not at runtime -
    # importing it for real would raise ImportError. Guarding the import
    # behind `TYPE_CHECKING` means it exists purely for mypy to check
    # against.
    from loguru import Logger

_GRAPHQL_ENDPOINT = "/api/graphql"


class RscClient:
    """Everything needed to reach one RSC instance's GraphQL API, bundled
    into one object.

    Construct one of these per RSC instance you talk to (typically via
    `connect()`/`connect_with_service_account()` in `facade.py`), then hand
    it to `RSC()` to get a facade you can actually use.
    """

    def __init__(
        self,
        base_url: str,
        token: str,
        *,
        timeout: float = 30.0,
        logger: Logger = _default_logger,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token
        # Stored per-instance (not imported at module level) so a caller can
        # pass in a differently-configured logger - e.g.
        # `logger.bind(instance="prod")` - to tag every log line this
        # particular client produces, without affecting any other
        # RscClient.
        self._logger = logger
        headers = {"Authorization": f"Bearer {token}"}
        # `transport` normally stays None, and httpx opens real TCP sockets.
        # Passing one in is for testing against a fake ASGI app or a respx
        # mock transport without needing a real server listening on a real
        # port. Dependency injection again, one layer down: the thing that
        # actually moves bytes is swappable too.
        self._http = httpx.Client(
            base_url=self.base_url, headers=headers, timeout=timeout, transport=transport
        )
        self._logger.debug("Initialized RscClient for {}", self.base_url)

    @property
    def logger(self) -> Logger:
        """The logger this client was configured with.

        Exposed so other collaborators (domain managers, which are handed an
        `RscClient` rather than importing a global logger themselves) log
        through the same, possibly-customized, logger as this client.
        """
        return self._logger

    def close(self) -> None:
        self._logger.debug("Closing RscClient for {}", self.base_url)
        self._http.close()

    def __enter__(self) -> RscClient:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def execute(
        self,
        document: str,
        variables: dict[str, Any] | None = None,
        *,
        operation_name: str | None = None,
    ) -> dict[str, Any]:
        """Send one GraphQL document and return its `data` object.

        Raises `httpx.HTTPStatusError` on a non-2xx HTTP response (a
        transport-level failure - bad auth, the endpoint is down, ...) and
        `GraphQLError` when the HTTP call succeeds but the response body
        carries a top-level `errors` array (a GraphQL application-level
        failure - bad variables, a field that doesn't resolve, ...). Those
        are different failure modes, so they're surfaced as different
        exception types rather than one or the other being silently folded
        away.
        """
        payload: dict[str, Any] = {"query": document, "variables": variables or {}}
        if operation_name is not None:
            payload["operationName"] = operation_name
        self._logger.debug(
            "POST {}{} operationName={}", self.base_url, _GRAPHQL_ENDPOINT, operation_name
        )
        response = self._http.post(_GRAPHQL_ENDPOINT, json=payload)
        response.raise_for_status()
        body: dict[str, Any] = response.json()
        errors = body.get("errors")
        if errors:
            self._logger.warning("GraphQL {} returned {} error(s)", operation_name, len(errors))
            raise GraphQLError(errors)
        data: dict[str, Any] = body["data"]
        return data
