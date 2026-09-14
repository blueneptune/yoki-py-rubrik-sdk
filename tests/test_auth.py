import io
import json
from pathlib import Path

import httpx
import pytest
import respx
from loguru import logger

from rubrik_rsc import RscAuthError, ServiceAccount, fetch_access_token

TOKEN_URI = "https://test-instance.my.rubrik.com/api/client_token"


@pytest.fixture
def service_account() -> ServiceAccount:
    return ServiceAccount(
        client_id="client-123",
        client_secret="s3cr3t",
        access_token_uri=TOKEN_URI,
        name="test-service-account",
    )


def test_from_json_file_loads_fields(tmp_path: Path, service_account: ServiceAccount) -> None:
    path = tmp_path / "service-account.json"
    path.write_text(service_account.model_dump_json())

    loaded = ServiceAccount.from_json_file(path)

    assert loaded == service_account


def test_base_url_strips_token_endpoint_suffix(service_account: ServiceAccount) -> None:
    assert service_account.base_url == "https://test-instance.my.rubrik.com"


def test_base_url_raises_when_access_token_uri_has_unexpected_shape() -> None:
    service_account = ServiceAccount(
        client_id="c", client_secret="s", access_token_uri="https://example.com/weird"
    )

    with pytest.raises(RscAuthError, match="Cannot derive base_url"):
        _ = service_account.base_url


@respx.mock
def test_fetch_access_token_posts_credentials_and_returns_token(
    service_account: ServiceAccount,
) -> None:
    route = respx.post(TOKEN_URI).mock(
        return_value=httpx.Response(200, json={"access_token": "abc123", "token_type": "bearer"})
    )

    token = fetch_access_token(service_account)

    assert token == "abc123"
    sent_body = json.loads(route.calls.last.request.content)
    assert sent_body == {"client_id": "client-123", "client_secret": "s3cr3t"}


@respx.mock
def test_fetch_access_token_raises_on_http_error(service_account: ServiceAccount) -> None:
    respx.post(TOKEN_URI).mock(return_value=httpx.Response(403, json={"detail": "forbidden"}))

    with pytest.raises(httpx.HTTPStatusError):
        fetch_access_token(service_account)


@respx.mock
def test_fetch_access_token_raises_rsc_auth_error_when_token_missing(
    service_account: ServiceAccount,
) -> None:
    respx.post(TOKEN_URI).mock(return_value=httpx.Response(200, json={"token_type": "bearer"}))

    with pytest.raises(RscAuthError, match="did not include an 'access_token'"):
        fetch_access_token(service_account)


@respx.mock
def test_fetch_access_token_logs_through_the_passed_in_logger(
    service_account: ServiceAccount,
) -> None:
    """`logger` is dependency-injected the same way `RscClient`'s is (see
    test_client.py) - this exchange's log lines should show up wherever the
    caller's logger sends them, not only through loguru's global default."""
    respx.post(TOKEN_URI).mock(return_value=httpx.Response(200, json={"access_token": "abc123"}))
    stream = io.StringIO()
    sink_id = logger.add(stream, level="DEBUG")

    try:
        fetch_access_token(service_account, logger=logger)
    finally:
        logger.remove(sink_id)

    assert "Obtained a bearer token" in stream.getvalue()
