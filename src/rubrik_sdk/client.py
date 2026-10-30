"""The SDK's entry point: RubrikClient.

A facade: one object per Rubrik Security Cloud (RSC) account, with a
named group of calls for each kind of thing - `rsc.jobs`, `rsc.clusters`,
`rsc.sla_domains`, `rsc.mssql_databases`.

    account = ServiceAccount.from_json_file("blt-reader.json")
    with RubrikClient(account) as rsc:
        for page in rsc.jobs.iter_pages(updated_after=since):
            ...

RSC has one endpoint, POST /api/graphql, for everything. sdk-primer
supplies the transport underneath it (retry and backoff, typed
exceptions, per-request log correlation) and the service-account token
exchange. What this adds is GraphQL's own failure mode - 200 OK with an
`errors` array - and the rule about changes:

- `execute`  - queries. Retried on a timeout or a gateway error.
- `change`   - mutations (assigning an SLA, starting a backup, ...).
               Refused unless the client was built with
               allow_changes=True, and sent exactly once: a mutation that
               timed out may well have happened, and sending it again
               could do it twice.

Queries are taken from the operation files of Rubrik's own PowerShell
SDK (github.com/rubrikinc/rubrik-powershell-sdk). **None of it has been
run against a real RSC account yet**; `rubrik-probe` is there to check
it the first time.
"""

from __future__ import annotations

import ssl
from pathlib import Path
from typing import TYPE_CHECKING, Any

import httpx
from loguru import logger as _default_logger
from sdk_primer import APIClient, SDKError, ServerError

from .activity import ActivitySeriesManager
from .auth import ServiceAccount, service_account_auth
from .cluster import ClusterManager
from .errors import ChangesNotAllowed, GraphQLError
from .inventory import InventoryManager
from .mssql import MssqlDatabaseManager
from .sla_domain import SlaDomainManager

if TYPE_CHECKING:
    # loguru's Logger exists only in its type stub.
    from loguru import Logger

GRAPHQL_PATH = "/api/graphql"
SESSION_PATH = "/api/session"


class RubrikClient:
    """One connection to one RSC account.

    Built from a service account (the normal way), or from an address and
    a bearer token obtained elsewhere. Read-only unless built with
    allow_changes=True.
    """

    def __init__(
        self,
        service_account: ServiceAccount | None = None,
        *,
        base_url: str | None = None,
        token: str | None = None,
        verify_tls: bool = True,
        ca_bundle: Path | None = None,
        page_size: int = 200,
        timeout: float = 120.0,
        allow_changes: bool = False,
        transport: httpx.BaseTransport | None = None,
        logger: Logger = _default_logger,
    ) -> None:
        if (service_account is None) == (token is None):
            raise ValueError("Give either a service account, or base_url and token.")
        if service_account is not None:
            base_url = service_account.base_url
        if not base_url:
            raise ValueError("base_url is needed with a token.")
        self.base_url = base_url.rstrip("/")
        self.page_size = page_size
        # Off by default. A caller that only reads should leave it off.
        self.allow_changes = allow_changes
        self._logger = logger

        verify: bool | ssl.SSLContext = verify_tls
        if verify_tls and ca_bundle is not None:
            verify = ssl.create_default_context(cafile=str(ca_bundle))
        headers = {"Accept": "application/json"}

        # The token request goes through its own plain client: it cannot
        # use the one whose authentication it is supplying.
        self._login_client = httpx.Client(verify=verify, timeout=timeout, transport=transport)
        self._auth: httpx.Auth | None = None
        if service_account is not None:
            self._auth = service_account_auth(service_account, self._login_client)

        def api(max_attempts: int) -> APIClient:
            return APIClient(
                base_url=self.base_url,
                token=token,
                auth=self._auth,
                default_headers=headers,
                timeout=timeout,
                max_attempts=max_attempts,
                transport=transport or httpx.HTTPTransport(verify=verify),
            )

        self._api = api(3)
        # For mutations: one attempt, never a retry.
        self._api_once = api(1)

        self.jobs = ActivitySeriesManager(self)
        self.clusters = ClusterManager(self)
        self.inventory = InventoryManager(self)
        self.sla_domains = SlaDomainManager(self)
        self.mssql_databases = MssqlDatabaseManager(self)
        self._logger.debug("Initialized RubrikClient for {}", self.base_url)

    @property
    def logger(self) -> Logger:
        return self._logger

    @property
    def api(self) -> APIClient:
        """The authenticated transport, for a call the SDK does not wrap
        yet. Prefer adding it to the right group."""
        return self._api

    # -- GraphQL -----------------------------------------------------------

    def _send(
        self,
        transport: APIClient,
        document: str,
        variables: dict[str, Any] | None,
        operation_name: str | None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {"query": document, "variables": variables or {}}
        if operation_name is not None:
            payload["operationName"] = operation_name
        response = transport.post(GRAPHQL_PATH, json=payload)
        try:
            body = response.json()
        except ValueError:
            raise ServerError(
                f"POST {GRAPHQL_PATH} ({operation_name}) returned "
                f"{response.headers.get('content-type', 'no content type')} instead of JSON."
            ) from None
        if body.get("errors"):
            raise GraphQLError(body["errors"], operation_name)
        data: dict[str, Any] = body.get("data") or {}
        return data

    def execute(
        self,
        document: str,
        variables: dict[str, Any] | None = None,
        *,
        operation_name: str | None = None,
    ) -> dict[str, Any]:
        """Run a query and return its `data`. Raises GraphQLError if RSC
        refused it, an SDKError if it never got an answer."""
        return self._send(self._api, document, variables, operation_name)

    def change(
        self,
        document: str,
        variables: dict[str, Any] | None = None,
        *,
        operation_name: str | None = None,
    ) -> dict[str, Any]:
        """Run a mutation, once. Refused on a read-only client."""
        if not self.allow_changes:
            raise ChangesNotAllowed(
                f"{operation_name or 'This mutation'} would change Rubrik; this client is "
                "read-only. Build it with allow_changes=True if that is really intended."
            )
        return self._send(self._api_once, document, variables, operation_name)

    # -- lifetime ----------------------------------------------------------

    def close(self, *, logout: bool = True) -> None:
        """Close the connection, ending the session on RSC first so it
        does not count against the service account's session limit."""
        self._logger.debug("Closing RubrikClient for {}", self.base_url)
        # Only if a token was ever fetched: logging out must not log in.
        signed_in = getattr(self._auth, "_token", None) is not None
        if logout and signed_in:
            try:
                self._api_once.delete(SESSION_PATH)
            except SDKError:
                self._logger.info("Ending the RSC session failed; it will expire on its own")
        self._api.close()
        self._api_once.close()
        self._login_client.close()

    def __enter__(self) -> RubrikClient:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()
