import json
from typing import Any

import respx

from rubrik_rsc import ActivitySeriesManager, RscClient

from .conftest import GRAPHQL_URL, graphql_responder, make_page_info


def _activity_series_node(*, id: str, object_name: str, status: str = "Success") -> dict[str, Any]:  # noqa: A002
    return {
        "id": id,
        "fid": id,
        "activitySeriesId": id,
        "startTime": "2024-06-01T00:00:00Z",
        "lastUpdated": "2024-06-01T01:00:00Z",
        "lastActivityType": "Backup",
        "lastActivityStatus": status,
        "location": "sql-prod-01",
        "objectName": object_name,
        "objectId": "obj-1",
        "objectType": "MssqlDatabase",
        "severity": "Info",
        "progress": "100",
        "slaDomainName": "Gold",
        "cluster": {"id": "c1", "name": "cluster-one"},
        "activityConnection": {
            "nodes": [
                {
                    "id": "evt-1",
                    "message": "Started",
                    "severity": "Info",
                    "time": "2024-06-01T00:00:00Z",
                },
                {
                    "id": "evt-2",
                    "message": "Finished",
                    "severity": "Info",
                    "time": "2024-06-01T01:00:00Z",
                },
            ]
        },
    }


def _activity_series_page(
    *, nodes: list[dict[str, Any]], has_next_page: bool, end_cursor: str | None
) -> dict[str, Any]:
    return {
        "data": {
            "activitySeriesConnection": {
                "edges": [{"node": node} for node in nodes],
                "pageInfo": make_page_info(has_next_page=has_next_page, end_cursor=end_cursor),
            }
        }
    }


@respx.mock
def test_list_returns_a_single_page_of_jobs() -> None:
    client = RscClient("https://test-instance.my.rubrik.com", token="test-token")
    respx.post(GRAPHQL_URL).mock(
        side_effect=graphql_responder(
            {
                "ActivitySeriesConnection": [
                    _activity_series_page(
                        nodes=[_activity_series_node(id="job-1", object_name="AdventureWorks")],
                        has_next_page=False,
                        end_cursor=None,
                    )
                ]
            }
        )
    )
    manager = ActivitySeriesManager(client)

    page = manager.list()

    assert len(page.items) == 1
    job = page.items[0]
    assert job.id == "job-1"
    assert job.last_activity_status == "Success"
    assert job.cluster is not None
    assert job.cluster.name == "cluster-one"
    assert job.activity_connection is not None
    assert [e.message for e in job.activity_connection.nodes] == ["Started", "Finished"]


@respx.mock
def test_all_auto_paginates_across_multiple_pages() -> None:
    client = RscClient("https://test-instance.my.rubrik.com", token="test-token")
    respx.post(GRAPHQL_URL).mock(
        side_effect=graphql_responder(
            {
                "ActivitySeriesConnection": [
                    _activity_series_page(
                        nodes=[_activity_series_node(id="job-1", object_name="AdventureWorks")],
                        has_next_page=True,
                        end_cursor="cursor-1",
                    ),
                    _activity_series_page(
                        nodes=[_activity_series_node(id="job-2", object_name="Northwind")],
                        has_next_page=False,
                        end_cursor=None,
                    ),
                ]
            }
        )
    )
    manager = ActivitySeriesManager(client)

    jobs = list(manager.all())

    assert [j.id for j in jobs] == ["job-1", "job-2"]


@respx.mock
def test_for_object_filters_by_object_fid() -> None:
    client = RscClient("https://test-instance.my.rubrik.com", token="test-token")
    route = respx.post(GRAPHQL_URL).mock(
        side_effect=graphql_responder(
            {
                "ActivitySeriesConnection": [
                    _activity_series_page(
                        nodes=[_activity_series_node(id="job-1", object_name="AdventureWorks")],
                        has_next_page=False,
                        end_cursor=None,
                    )
                ]
            }
        )
    )
    manager = ActivitySeriesManager(client)

    jobs = list(manager.for_object("db-123"))

    assert [j.id for j in jobs] == ["job-1"]
    sent_variables = json.loads(route.calls.last.request.content)["variables"]
    assert sent_variables["filters"] == {"objectFid": ["db-123"]}


@respx.mock
def test_status_returns_taskchain_when_present() -> None:
    client = RscClient("https://test-instance.my.rubrik.com", token="test-token")
    respx.post(GRAPHQL_URL).mock(
        side_effect=graphql_responder(
            {
                "TaskchainStatus": [
                    {
                        "data": {
                            "getKorgTaskchainStatus": {
                                "taskchain": {
                                    "id": "tc-1",
                                    "state": "RUNNING",
                                    "taskchainUuid": "uuid-1",
                                    "progressedAt": "2024-06-01T00:30:00Z",
                                }
                            }
                        }
                    }
                ]
            }
        )
    )
    manager = ActivitySeriesManager(client)

    taskchain = manager.status("tc-1")

    assert taskchain is not None
    assert taskchain.state == "RUNNING"
    assert taskchain.progressed_at == "2024-06-01T00:30:00Z"


@respx.mock
def test_status_returns_none_when_taskchain_is_null() -> None:
    client = RscClient("https://test-instance.my.rubrik.com", token="test-token")
    respx.post(GRAPHQL_URL).mock(
        side_effect=graphql_responder(
            {"TaskchainStatus": [{"data": {"getKorgTaskchainStatus": {"taskchain": None}}}]}
        )
    )
    manager = ActivitySeriesManager(client)

    taskchain = manager.status("does-not-exist")

    assert taskchain is None
