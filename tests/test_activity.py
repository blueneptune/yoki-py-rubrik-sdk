import json
from datetime import UTC, datetime
from typing import Any

import respx

from rubrik_sdk import ActivitySeries, ActivitySeriesManager, RubrikClient

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
    client = RubrikClient(base_url="https://test-instance.my.rubrik.com", token="test-token")
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
    client = RubrikClient(base_url="https://test-instance.my.rubrik.com", token="test-token")
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
    client = RubrikClient(base_url="https://test-instance.my.rubrik.com", token="test-token")
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
    client = RubrikClient(base_url="https://test-instance.my.rubrik.com", token="test-token")
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
    client = RubrikClient(base_url="https://test-instance.my.rubrik.com", token="test-token")
    respx.post(GRAPHQL_URL).mock(
        side_effect=graphql_responder(
            {"TaskchainStatus": [{"data": {"getKorgTaskchainStatus": {"taskchain": None}}}]}
        )
    )
    manager = ActivitySeriesManager(client)

    taskchain = manager.status("does-not-exist")

    assert taskchain is None


def _light_page(nodes: list[dict[str, Any]], cursor: str | None) -> dict[str, Any]:
    for node in nodes:
        node.pop("activityConnection", None)
    return {
        "data": {
            "activitySeriesConnection": {
                "edges": [{"node": node} for node in nodes],
                "pageInfo": {"endCursor": cursor, "hasNextPage": cursor is not None},
            }
        }
    }


@respx.mock
def test_iter_pages_walks_every_page_oldest_change_first() -> None:
    client = RubrikClient(base_url="https://test-instance.my.rubrik.com", token="test-token")
    route = respx.post(GRAPHQL_URL).mock(
        side_effect=graphql_responder(
            {
                "ActivitySeriesPage": [
                    _light_page([_activity_series_node(id="a", object_name="x")], "c1"),
                    _light_page([_activity_series_node(id="b", object_name="y")], None),
                ]
            }
        )
    )
    since = datetime(2024, 6, 1, 12, 0, tzinfo=UTC)

    pages = list(client.jobs.iter_pages(updated_after=since, page_size=1))

    assert [[s.id for s in page] for page in pages] == [["a"], ["b"]]
    first, second = (json.loads(call.request.content)["variables"] for call in route.calls)
    assert first == {
        "first": 1,
        "sortBy": "LAST_UPDATED",
        "sortOrder": "ASC",
        "filters": {"lastUpdatedTimeGt": "2024-06-01T12:00:00Z"},
    }
    assert second["after"] == "c1"
    assert "activityConnection" not in json.loads(route.calls[0].request.content)["query"]


@respx.mock
def test_iter_pages_skips_a_record_it_cannot_read() -> None:
    client = RubrikClient(base_url="https://test-instance.my.rubrik.com", token="test-token")
    bad = _activity_series_node(id="bad", object_name="x")
    bad["startTime"] = "not a time"
    respx.post(GRAPHQL_URL).mock(
        side_effect=graphql_responder(
            {
                "ActivitySeriesPage": [
                    _light_page([bad, _activity_series_node(id="good", object_name="y")], None)
                ]
            }
        )
    )

    pages = list(client.jobs.iter_pages())

    assert [s.id for s in pages[0]] == ["good"]


@respx.mock
def test_sample_asks_for_the_newest_few() -> None:
    client = RubrikClient(base_url="https://test-instance.my.rubrik.com", token="test-token")
    route = respx.post(GRAPHQL_URL).mock(
        side_effect=graphql_responder(
            {
                "ActivitySeriesPage": [
                    _light_page([_activity_series_node(id="a", object_name="x")], None)
                ]
            }
        )
    )

    series = client.jobs.sample(3)

    assert [s.id for s in series] == ["a"]
    variables = json.loads(route.calls.last.request.content)["variables"]
    assert variables == {"first": 3, "sortBy": "LAST_UPDATED", "sortOrder": "DESC"}


def test_series_times_are_read_as_timezone_aware_datetimes() -> None:
    series = ActivitySeries.model_validate(_activity_series_node(id="a", object_name="x"))

    assert series.start_time == datetime(2024, 6, 1, 0, 0, tzinfo=UTC)


def test_is_active_reads_the_status_loosely() -> None:
    def status(value: str) -> bool:
        return ActivitySeries.model_validate(
            _activity_series_node(id="a", object_name="x", status=value)
        ).is_active

    assert status("Running") and status("RUNNING") and status("Queued")
    assert not status("Success") and not status("Failure") and not status("Canceled")


def test_key_prefers_the_global_id_and_falls_back_to_cluster_and_series() -> None:
    node = _activity_series_node(id="7", object_name="x")
    assert ActivitySeries.model_validate(node).key == "7"
    node["fid"] = None
    node["activitySeriesId"] = "series-9"
    assert ActivitySeries.model_validate(node).key == "c1:series-9"


def test_a_numeric_series_id_is_read_as_a_string() -> None:
    # RSC sends an activity series' id as a number.
    series = ActivitySeries.model_validate(
        {"id": 11352988, "activitySeriesId": "a1", "cluster": {"id": "c1", "name": "x"}}
    )

    assert series.id == "11352988"
    assert series.key == "c1:a1"
