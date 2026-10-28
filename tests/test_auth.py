import json
from pathlib import Path

import httpx
import pytest
import respx

from rubrik_sdk import RubrikClient, RubrikError, ServiceAccount

from .conftest import BASE_URL, GRAPHQL_URL

TOKEN_URI = f"{BASE_URL}/api/client_token"
SESSION_URL = f"{BASE_URL}/api/session"


@pytest.fixture
def service_account() -> ServiceAccount:
    return ServiceAccount(
        client_id="client-123",
        client_secret="s3cr3t",
        access_token_uri=TOKEN_URI,
        name="test-service-account",
    )


def test_from_json_file_loads_fields(tmp_path: Path) -> None:
    path = tmp_path / "service-account.json"
    path.write_text(
        json.dumps(
            {
                "client_id": "client-123",
                "client_secret": "s3cr3t",
                "access_token_uri": TOKEN_URI,
                "name": "blt-reader",
            }
        )
    )

    loaded = ServiceAccount.from_json_file(path)

    assert loaded.client_id == "client-123"
    assert loaded.client_secret.get_secret_value() == "s3cr3t"
    assert loaded.name == "blt-reader"


def test_the_secret_does_not_show_when_printed(service_account: ServiceAccount) -> None:
    assert "s3cr3t" not in repr(service_account)
    assert "s3cr3t" not in str(service_account)


def test_base_url_strips_token_endpoint_suffix(service_account: ServiceAccount) -> None:
    assert service_account.base_url == BASE_URL


def test_base_url_refuses_an_unexpected_token_address() -> None:
    account = ServiceAccount(
        client_id="c", client_secret="s", access_token_uri="https://example.com/weird"
    )

    with pytest.raises(RubrikError, match="does not end with"):
        _ = account.base_url


@respx.mock
def test_the_first_call_fetches_a_token_and_uses_it(service_account: ServiceAccount) -> None:
    token_route = respx.post(TOKEN_URI).mock(
        return_value=httpx.Response(200, json={"access_token": "tok-1"})
    )
    graphql = respx.post(GRAPHQL_URL).mock(
        return_value=httpx.Response(200, json={"data": {"ok": True}})
    )
    respx.delete(SESSION_URL).mock(return_value=httpx.Response(204))

    with RubrikClient(service_account) as rsc:
        rsc.execute("query Ping { ok }")
        rsc.execute("query Ping { ok }")

    assert token_route.call_count == 1
    assert json.loads(token_route.calls.last.request.content) == {
        "client_id": "client-123",
        "client_secret": "s3cr3t",
    }
    assert graphql.calls.last.request.headers["Authorization"] == "Bearer tok-1"


@respx.mock
def test_a_refused_token_is_replaced_once(service_account: ServiceAccount) -> None:
    respx.post(TOKEN_URI).mock(
        side_effect=[
            httpx.Response(200, json={"access_token": "old"}),
            httpx.Response(200, json={"access_token": "new"}),
        ]
    )
    graphql = respx.post(GRAPHQL_URL).mock(
        side_effect=[
            httpx.Response(401),
            httpx.Response(200, json={"data": {"ok": True}}),
        ]
    )
    rsc = RubrikClient(service_account)

    assert rsc.execute("query Ping { ok }") == {"ok": True}
    assert graphql.calls.last.request.headers["Authorization"] == "Bearer new"
    rsc.close(logout=False)


@respx.mock
def test_close_ends_the_session(service_account: ServiceAccount) -> None:
    respx.post(TOKEN_URI).mock(return_value=httpx.Response(200, json={"access_token": "tok"}))
    respx.post(GRAPHQL_URL).mock(return_value=httpx.Response(200, json={"data": {}}))
    logout = respx.delete(SESSION_URL).mock(return_value=httpx.Response(204))

    with RubrikClient(service_account) as rsc:
        rsc.execute("query Ping { ok }")

    assert logout.call_count == 1
    assert logout.calls.last.request.headers["Authorization"] == "Bearer tok"


@respx.mock
def test_close_without_a_session_does_not_sign_in(service_account: ServiceAccount) -> None:
    token_route = respx.post(TOKEN_URI).mock(return_value=httpx.Response(200, json={}))

    RubrikClient(service_account).close()

    assert token_route.call_count == 0


def test_a_client_needs_exactly_one_way_to_sign_in(service_account: ServiceAccount) -> None:
    with pytest.raises(ValueError):
        RubrikClient()
    with pytest.raises(ValueError):
        RubrikClient(service_account, token="t")
    with pytest.raises(ValueError):
        RubrikClient(token="t")
