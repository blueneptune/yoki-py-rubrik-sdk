import json
from typing import Any

import respx

from rubrik_rsc import ClusterManager, RscClient

from .conftest import GRAPHQL_URL, graphql_responder, make_page_info


def _cluster_node(*, id: str, name: str, status: str = "Connected") -> dict[str, Any]:  # noqa: A002
    return {
        "id": id,
        "name": name,
        "version": "9.1.0",
        "status": status,
        "subStatus": None,
        "pauseStatus": None,
        "type": "CDM",
        "productType": "CDM",
        "timezone": "UTC",
        "registrationTime": "2024-01-01T00:00:00Z",
        "lastConnectionTime": "2024-06-01T00:00:00Z",
        "isHealthy": True,
        "snapshotCount": 42,
        "encryptionEnabled": True,
        "cloudInfo": {"region": "us-east-1", "vendor": "AWS"},
        "clusterNodeConnection": {
            "count": 1,
            "nodes": [
                {
                    "id": f"{id}-node-1",
                    "ipAddress": "10.0.0.1",
                    "status": "OK",
                    "cpuCores": 16,
                    "ram": 137438953472,
                }
            ],
        },
        "geoLocation": {"address": "Palo Alto, CA", "latitude": 37.44, "longitude": -122.14},
        "metric": {
            "availableCapacity": 100.0,
            "usedCapacity": 50.0,
            "totalCapacity": 150.0,
            "snapshotCapacity": 40.0,
            "liveMountCapacity": 0.0,
            "miscellaneousCapacity": 10.0,
            "ingestedSnapshotStorage": 30.0,
            "physicalSnapshotStorage": 25.0,
            "ingestedArchivalStorage": 5.0,
            "physicalArchivalStorage": 4.0,
            "immutabilityOverhead": 1.0,
            "lastUpdateTime": "2024-06-01T00:00:00Z",
        },
    }


def _cluster_page(
    *, nodes: list[dict[str, Any]], has_next_page: bool, end_cursor: str | None
) -> dict[str, Any]:
    return {
        "data": {
            "clusterConnection": {
                "edges": [{"node": node} for node in nodes],
                "pageInfo": make_page_info(has_next_page=has_next_page, end_cursor=end_cursor),
            }
        }
    }


@respx.mock
def test_list_returns_a_single_page_of_clusters() -> None:
    client = RscClient("https://test-instance.my.rubrik.com", token="test-token")
    respx.post(GRAPHQL_URL).mock(
        side_effect=graphql_responder(
            {
                "Cluster": [
                    _cluster_page(
                        nodes=[_cluster_node(id="c1", name="cluster-one")],
                        has_next_page=False,
                        end_cursor=None,
                    )
                ]
            }
        )
    )
    manager = ClusterManager(client)

    page = manager.list()

    assert len(page.items) == 1
    cluster = page.items[0]
    assert cluster.id == "c1"
    assert cluster.name == "cluster-one"
    assert cluster.cloud_info is not None
    assert cluster.cloud_info.region == "us-east-1"
    assert cluster.cluster_node_connection is not None
    assert cluster.cluster_node_connection.count == 1
    assert cluster.metric is not None
    assert cluster.metric.total_capacity == 150.0
    assert page.page_info.has_next_page is False


@respx.mock
def test_list_forwards_filter_and_sort_arguments_as_graphql_variables() -> None:
    client = RscClient("https://test-instance.my.rubrik.com", token="test-token")
    route = respx.post(GRAPHQL_URL).mock(
        side_effect=graphql_responder(
            {"Cluster": [_cluster_page(nodes=[], has_next_page=False, end_cursor=None)]}
        )
    )
    manager = ClusterManager(client)

    manager.list(filter={"connectedOnly": True}, sort_by="ClusterName", sort_order="ASC")

    sent_variables = json.loads(route.calls.last.request.content)["variables"]
    assert sent_variables == {
        "filter": {"connectedOnly": True},
        "sortBy": "ClusterName",
        "sortOrder": "ASC",
    }


@respx.mock
def test_all_auto_paginates_across_multiple_pages() -> None:
    client = RscClient("https://test-instance.my.rubrik.com", token="test-token")
    respx.post(GRAPHQL_URL).mock(
        side_effect=graphql_responder(
            {
                "Cluster": [
                    _cluster_page(
                        nodes=[_cluster_node(id="c1", name="cluster-one")],
                        has_next_page=True,
                        end_cursor="cursor-1",
                    ),
                    _cluster_page(
                        nodes=[_cluster_node(id="c2", name="cluster-two")],
                        has_next_page=False,
                        end_cursor=None,
                    ),
                ]
            }
        )
    )
    manager = ClusterManager(client)

    clusters = list(manager.all())

    assert [c.name for c in clusters] == ["cluster-one", "cluster-two"]


@respx.mock
def test_find_by_name_returns_matching_cluster_without_exhausting_pages() -> None:
    client = RscClient("https://test-instance.my.rubrik.com", token="test-token")
    respx.post(GRAPHQL_URL).mock(
        side_effect=graphql_responder(
            {
                "Cluster": [
                    _cluster_page(
                        nodes=[_cluster_node(id="c1", name="cluster-one")],
                        has_next_page=True,
                        end_cursor="cursor-1",
                    )
                    # A second page is deliberately not queued: if
                    # find_by_name() didn't stop early, the mock would raise
                    # IndexError from an empty queue, failing the test.
                ]
            }
        )
    )
    manager = ClusterManager(client)

    found = manager.find_by_name("cluster-one")

    assert found is not None
    assert found.id == "c1"


@respx.mock
def test_find_by_name_returns_none_when_no_cluster_matches() -> None:
    client = RscClient("https://test-instance.my.rubrik.com", token="test-token")
    respx.post(GRAPHQL_URL).mock(
        side_effect=graphql_responder(
            {
                "Cluster": [
                    _cluster_page(
                        nodes=[_cluster_node(id="c1", name="cluster-one")],
                        has_next_page=False,
                        end_cursor=None,
                    )
                ]
            }
        )
    )
    manager = ClusterManager(client)

    found = manager.find_by_name("does-not-exist")

    assert found is None
