"""Signing in to Rubrik Security Cloud (RSC) with a service account.

A service account is made in RSC's UI (Settings > Users > Service
Accounts) and downloaded once as a JSON file:

    {"client_id": "client|...", "client_secret": "...",
     "name": "blt-reader",
     "access_token_uri": "https://<account>.my.rubrik.com/api/client_token"}

POSTing client_id and client_secret to access_token_uri returns a bearer
token, which every GraphQL call carries. Unlike Commvault's token pair
there is nothing to renew or store: the id and secret stay valid until
someone rotates them in RSC, and a fresh token is fetched whenever the
old one is refused. sdk-primer's TokenExchangeAuth does exactly that.

RSC caps how many sessions one service account may have open, so a
client should end its session when done (RubrikClient.close does,
with DELETE /api/session).
"""

from __future__ import annotations

from pathlib import Path
from typing import Self

import httpx
from pydantic import BaseModel, SecretStr
from sdk_primer import TokenExchangeAuth

from .errors import RubrikError

TOKEN_PATH = "/api/client_token"


class ServiceAccount(BaseModel):
    """The JSON file RSC hands out for a service account. The secret is a
    SecretStr, so printing or logging the model does not show it."""

    client_id: str
    client_secret: SecretStr
    access_token_uri: str
    name: str | None = None

    @classmethod
    def from_json_file(cls, path: str | Path) -> Self:
        return cls.model_validate_json(Path(path).read_text())

    @property
    def base_url(self) -> str:
        """The account's address (https://<account>.my.rubrik.com), taken
        from access_token_uri so it is never given twice."""
        uri = self.access_token_uri.rstrip("/")
        if not uri.endswith(TOKEN_PATH):
            raise RubrikError(
                f"access_token_uri {self.access_token_uri!r} does not end with {TOKEN_PATH!r}; "
                "is this an RSC service account file?"
            )
        return uri.removesuffix(TOKEN_PATH)


def service_account_auth(account: ServiceAccount, client: httpx.Client) -> TokenExchangeAuth:
    """An httpx.Auth that fetches a token on first use and again on a 401.
    `client` makes the token request (it carries the TLS settings)."""
    return TokenExchangeAuth(
        token_url=account.access_token_uri,
        credentials={
            "client_id": account.client_id,
            "client_secret": account.client_secret.get_secret_value(),
        },
        client=client,
    )
