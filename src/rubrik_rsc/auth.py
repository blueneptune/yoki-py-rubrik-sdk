"""Service-account authentication: exchanging long-lived credentials for the
short-lived bearer token `RscClient` actually sends on every request.

RSC issues API access through "service accounts". Downloading one from RSC's
UI gives you a JSON file shaped like `ServiceAccount` below - a `client_id`
and `client_secret`, plus the exact token endpoint URL to exchange them at
(`access_token_uri`, e.g. `https://<instance>.my.rubrik.com/api/client_token`).
`fetch_access_token()` does that exchange; `connect_with_service_account()`
in `facade.py` is the convenience wrapper that does the exchange *and* builds
a ready-to-use facade from the result, the way `load_client()` does once
you already have a token.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Self

import httpx
from loguru import logger as _default_logger
from pydantic import BaseModel

from .errors import RscAuthError

if TYPE_CHECKING:
    from loguru import Logger

_TOKEN_ENDPOINT_SUFFIX = "/api/client_token"


class ServiceAccount(BaseModel):
    """The shape of the JSON file RSC's UI hands you when you create a
    service account. Load it with `from_json_file()` rather than
    constructing one field-by-field, unless you're wiring credentials up
    from your own secret store."""

    client_id: str
    client_secret: str
    access_token_uri: str
    name: str | None = None

    @classmethod
    def from_json_file(cls, path: str | Path) -> Self:
        return cls.model_validate_json(Path(path).read_text())

    @property
    def base_url(self) -> str:
        """The GraphQL/API base URL for this instance, derived from
        `access_token_uri` by dropping its known `/api/client_token` suffix
        - so callers don't have to supply the same instance URL twice."""
        if not self.access_token_uri.endswith(_TOKEN_ENDPOINT_SUFFIX):
            raise RscAuthError(
                f"Cannot derive base_url: access_token_uri {self.access_token_uri!r} "
                f"does not end with {_TOKEN_ENDPOINT_SUFFIX!r}."
            )
        return self.access_token_uri.removesuffix(_TOKEN_ENDPOINT_SUFFIX)


def fetch_access_token(
    service_account: ServiceAccount,
    *,
    timeout: float = 30.0,
    logger: Logger = _default_logger,
) -> str:
    """Exchange a service account's client_id/client_secret for a bearer
    token by POSTing to its `access_token_uri`.

    Uses a throwaway `httpx` call rather than an `RscClient` - there's no
    bearer token to attach yet, since obtaining one is the entire point of
    this call. `logger` follows the same dependency-injection pattern as
    `RscClient`'s (see `client.py`): defaults to loguru's global `logger`,
    but accepts whatever logger the caller is already using so this
    function's log lines land wherever the rest of theirs do.
    """
    logger.debug(
        "Exchanging service account credentials for a bearer token at {}",
        service_account.access_token_uri,
    )
    response = httpx.post(
        service_account.access_token_uri,
        json={
            "client_id": service_account.client_id,
            "client_secret": service_account.client_secret,
        },
        timeout=timeout,
    )
    response.raise_for_status()
    body = response.json()
    token = body.get("access_token")
    if not token:
        logger.warning("Token endpoint response did not include an 'access_token' field.")
        raise RscAuthError("Token endpoint response did not include an 'access_token' field.")
    logger.debug("Obtained a bearer token for {}", service_account.base_url)
    return str(token)
