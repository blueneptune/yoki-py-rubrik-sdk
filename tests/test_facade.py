import io

import httpx
import respx
from loguru import logger

from rubrik_rsc import (
    RSC,
    ActivitySeriesManager,
    ClusterManager,
    MssqlDatabaseManager,
    RscClient,
    ServiceAccount,
    SlaDomainManager,
    connect,
    connect_with_service_account,
)

from .conftest import GRAPHQL_URL, graphql_responder, make_page_info


def test_rsc_wires_up_client_and_every_domain_manager() -> None:
    client = RscClient("https://test-instance.my.rubrik.com", token="test-token")

    rsc = RSC(client)

    assert rsc.client is client
    assert isinstance(rsc.clusters, ClusterManager)
    assert isinstance(rsc.sla_domains, SlaDomainManager)
    assert isinstance(rsc.jobs, ActivitySeriesManager)
    assert isinstance(rsc.mssql_databases, MssqlDatabaseManager)


def test_connect_builds_rsc_from_base_url_and_token() -> None:
    rsc = connect("https://test-instance.my.rubrik.com", "a-token")

    assert isinstance(rsc, RSC)
    assert rsc.client.base_url == "https://test-instance.my.rubrik.com"
    assert rsc.client.token == "a-token"


def test_connect_threads_a_custom_logger_through_to_the_client() -> None:
    """The DI pattern documented for `RscClient` (client.py) needs to reach
    all the way up through `connect()` - the entry point callers actually
    use - or it isn't real plumbing, just an internal implementation
    detail."""
    stream = io.StringIO()
    sink_id = logger.add(stream, level="DEBUG")

    try:
        rsc = connect("https://test-instance.my.rubrik.com", "a-token", logger=logger)
    finally:
        logger.remove(sink_id)

    assert rsc.client.logger is logger
    assert "Initialized RscClient" in stream.getvalue()


@respx.mock
def test_connect_with_service_account_threads_a_custom_logger_through() -> None:
    respx.post("https://test-instance.my.rubrik.com/api/client_token").mock(
        return_value=httpx.Response(200, json={"access_token": "exchanged-token"})
    )
    service_account = ServiceAccount(
        client_id="client-123",
        client_secret="s3cr3t",
        access_token_uri="https://test-instance.my.rubrik.com/api/client_token",
    )
    stream = io.StringIO()
    sink_id = logger.add(stream, level="DEBUG")

    try:
        rsc = connect_with_service_account(service_account, logger=logger)
    finally:
        logger.remove(sink_id)

    assert rsc.client.logger is logger
    output = stream.getvalue()
    assert "Obtained a bearer token" in output
    assert "Initialized RscClient" in output


@respx.mock
def test_connect_with_service_account_exchanges_token_then_queries() -> None:
    """End-to-end happy path: token exchange, then a real domain call
    through the resulting facade - proves the two pieces (auth.py,
    facade.py) are actually wired together, not just independently
    correct."""
    respx.post("https://test-instance.my.rubrik.com/api/client_token").mock(
        return_value=httpx.Response(200, json={"access_token": "exchanged-token"})
    )
    graphql_route = respx.post(GRAPHQL_URL).mock(
        side_effect=graphql_responder(
            {
                "Cluster": [
                    {
                        "data": {
                            "clusterConnection": {
                                "edges": [],
                                "pageInfo": make_page_info(has_next_page=False, end_cursor=None),
                            }
                        }
                    }
                ]
            }
        )
    )
    service_account = ServiceAccount(
        client_id="client-123",
        client_secret="s3cr3t",
        access_token_uri="https://test-instance.my.rubrik.com/api/client_token",
    )

    rsc = connect_with_service_account(service_account)
    page = rsc.clusters.list()

    assert page.items == []
    assert graphql_route.calls.last.request.headers["Authorization"] == "Bearer exchanged-token"


@respx.mock
def test_two_rsc_instances_stay_isolated_to_their_own_client() -> None:
    """No shared/global state: two RSC instances built on two different
    clients must never cross-talk."""
    route_a = respx.post("https://a.my.rubrik.com/api/graphql").mock(
        side_effect=graphql_responder(
            {
                "Cluster": [
                    {
                        "data": {
                            "clusterConnection": {
                                "edges": [],
                                "pageInfo": make_page_info(has_next_page=False, end_cursor=None),
                            }
                        }
                    }
                ]
            }
        )
    )
    route_b = respx.post("https://b.my.rubrik.com/api/graphql").mock(
        side_effect=graphql_responder(
            {
                "Cluster": [
                    {
                        "data": {
                            "clusterConnection": {
                                "edges": [],
                                "pageInfo": make_page_info(has_next_page=False, end_cursor=None),
                            }
                        }
                    }
                ]
            }
        )
    )

    rsc_a = connect("https://a.my.rubrik.com", "token-a")
    rsc_b = connect("https://b.my.rubrik.com", "token-b")
    rsc_a.clusters.list()
    rsc_b.clusters.list()

    assert route_a.called
    assert route_b.called
