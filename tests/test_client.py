import json

import httpx
import pytest
import respx

from rubrik_rsc import GraphQLError, RscClient

from .conftest import GRAPHQL_URL


@respx.mock
def test_execute_posts_query_variables_and_operation_name(client: RscClient) -> None:
    route = respx.post(GRAPHQL_URL).mock(
        return_value=httpx.Response(200, json={"data": {"ok": True}})
    )

    data = client.execute("query Ping { ok }", {"a": 1}, operation_name="Ping")

    assert data == {"ok": True}
    sent_body = json.loads(route.calls.last.request.content)
    assert sent_body == {
        "query": "query Ping { ok }",
        "variables": {"a": 1},
        "operationName": "Ping",
    }


@respx.mock
def test_execute_defaults_variables_to_empty_dict_and_omits_operation_name(
    client: RscClient,
) -> None:
    route = respx.post(GRAPHQL_URL).mock(
        return_value=httpx.Response(200, json={"data": {"ok": True}})
    )

    client.execute("query Ping { ok }")

    sent_body = json.loads(route.calls.last.request.content)
    assert sent_body == {"query": "query Ping { ok }", "variables": {}}


@respx.mock
def test_execute_sends_bearer_token(client: RscClient) -> None:
    route = respx.post(GRAPHQL_URL).mock(
        return_value=httpx.Response(200, json={"data": {"ok": True}})
    )

    client.execute("query Ping { ok }")

    assert route.calls.last.request.headers["Authorization"] == "Bearer test-token"


@respx.mock
def test_execute_raises_graphql_error_on_errors_array(client: RscClient) -> None:
    respx.post(GRAPHQL_URL).mock(
        return_value=httpx.Response(
            200, json={"data": None, "errors": [{"message": "permission denied"}]}
        )
    )

    with pytest.raises(GraphQLError, match="permission denied"):
        client.execute("query Ping { ok }")


@respx.mock
def test_execute_raises_on_http_error_status(client: RscClient) -> None:
    respx.post(GRAPHQL_URL).mock(return_value=httpx.Response(401, json={"detail": "unauthorized"}))

    with pytest.raises(httpx.HTTPStatusError):
        client.execute("query Ping { ok }")


def test_close_closes_underlying_http_client() -> None:
    client = RscClient("https://test-instance.my.rubrik.com", token="test-token")
    client.close()
    assert client._http.is_closed


def test_context_manager_closes_on_exit() -> None:
    with RscClient("https://test-instance.my.rubrik.com", token="test-token") as client:
        assert not client._http.is_closed
    assert client._http.is_closed
