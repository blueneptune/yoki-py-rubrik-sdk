import json

import httpx
import pytest
import respx
from sdk_primer import SDKError

from rubrik_sdk import ChangesNotAllowed, GraphQLError, RubrikClient

from .conftest import BASE_URL, GRAPHQL_URL


@respx.mock
def test_execute_posts_query_variables_and_operation_name(client: RubrikClient) -> None:
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
    client: RubrikClient,
) -> None:
    route = respx.post(GRAPHQL_URL).mock(
        return_value=httpx.Response(200, json={"data": {"ok": True}})
    )

    client.execute("query Ping { ok }")

    sent_body = json.loads(route.calls.last.request.content)
    assert sent_body == {"query": "query Ping { ok }", "variables": {}}


@respx.mock
def test_execute_sends_bearer_token(client: RubrikClient) -> None:
    route = respx.post(GRAPHQL_URL).mock(
        return_value=httpx.Response(200, json={"data": {"ok": True}})
    )

    client.execute("query Ping { ok }")

    assert route.calls.last.request.headers["Authorization"] == "Bearer test-token"


@respx.mock
def test_execute_raises_graphql_error_on_errors_array(client: RubrikClient) -> None:
    respx.post(GRAPHQL_URL).mock(
        return_value=httpx.Response(
            200, json={"data": None, "errors": [{"message": "permission denied"}]}
        )
    )

    with pytest.raises(GraphQLError, match="permission denied"):
        client.execute("query Ping { ok }")


@respx.mock
def test_execute_raises_an_sdk_error_on_http_error_status(client: RubrikClient) -> None:
    respx.post(GRAPHQL_URL).mock(return_value=httpx.Response(403, json={"detail": "no"}))

    with pytest.raises(SDKError):
        client.execute("query Ping { ok }")


@respx.mock
def test_queries_are_retried_on_a_gateway_error(client: RubrikClient) -> None:
    route = respx.post(GRAPHQL_URL).mock(
        side_effect=[httpx.Response(503), httpx.Response(200, json={"data": {"ok": True}})]
    )
    client._api._sleep = lambda _: None

    assert client.execute("query Ping { ok }") == {"ok": True}
    assert route.call_count == 2


def test_mutations_are_refused_on_a_read_only_client(client: RubrikClient) -> None:
    with pytest.raises(ChangesNotAllowed):
        client.change("mutation Do { do }", operation_name="Do")


@respx.mock
def test_mutations_are_sent_once_even_on_a_gateway_error() -> None:
    rsc = RubrikClient(base_url=BASE_URL, token="t", allow_changes=True)
    route = respx.post(GRAPHQL_URL).mock(return_value=httpx.Response(503))

    with pytest.raises(SDKError):
        rsc.change("mutation Do { do }", operation_name="Do")
    assert route.call_count == 1


def test_context_manager_closes_on_exit() -> None:
    with RubrikClient(base_url=BASE_URL, token="test-token") as client:
        assert not client.api._http.is_closed
    assert client.api._http.is_closed
