import json
from datetime import UTC, datetime
from typing import Any

import respx

from rubrik_sdk import InventoryObject, RubrikClient

from .conftest import GRAPHQL_URL, graphql_responder


def _object_node(*, id: str, name: str, **extra: Any) -> dict[str, Any]:  # noqa: A002
    return {
        "id": id,
        "fid": id,
        "name": name,
        "objectType": "VmwareVirtualMachine",
        "location": "vcenter-01",
        "objectState": "ACTIVE",
        "protectionStatus": "PROTECTED",
        "complianceStatus": "IN_COMPLIANCE",
        "orgName": "",
        "lastSnapshot": "2024-06-01T01:00:00.000Z",
        "totalSnapshots": 42,
        "logicalBytes": 42949672960,
        "pullTime": "2024-06-01T02:00:00.000Z",
        "slaDomain": {"id": "sla-1", "name": "Gold"},
        "cluster": {"id": "c1", "name": "cluster-one"},
        **extra,
    }


def _page(nodes: list[dict[str, Any]], cursor: str | None) -> dict[str, Any]:
    return {
        "data": {
            "snappableConnection": {
                "edges": [{"node": node} for node in nodes],
                "pageInfo": {"endCursor": cursor, "hasNextPage": cursor is not None},
            }
        }
    }


@respx.mock
def test_iter_pages_walks_every_page() -> None:
    client = RubrikClient(base_url="https://test-instance.my.rubrik.com", token="test-token")
    route = respx.post(GRAPHQL_URL).mock(
        side_effect=graphql_responder(
            {
                "InventoryPage": [
                    _page([_object_node(id="a", name="vm-a")], "c1"),
                    _page([_object_node(id="b", name="vm-b")], None),
                ]
            }
        )
    )

    pages = list(client.inventory.iter_pages(page_size=1))

    assert [[o.id for o in page] for page in pages] == [["a"], ["b"]]
    first, second = (json.loads(call.request.content)["variables"] for call in route.calls)
    assert first == {"first": 1}
    assert second == {"first": 1, "after": "c1"}
    assert "snappableConnection" in json.loads(route.calls[0].request.content)["query"]


@respx.mock
def test_iter_pages_passes_the_filter_through() -> None:
    client = RubrikClient(base_url="https://test-instance.my.rubrik.com", token="test-token")
    route = respx.post(GRAPHQL_URL).mock(
        side_effect=graphql_responder({"InventoryPage": [_page([], None)]})
    )

    assert list(client.inventory.iter_pages(filter={"objectType": ["Mssql"]})) == []
    assert json.loads(route.calls[0].request.content)["variables"]["filter"] == {
        "objectType": ["Mssql"]
    }


@respx.mock
def test_iter_pages_skips_a_record_it_cannot_read() -> None:
    client = RubrikClient(base_url="https://test-instance.my.rubrik.com", token="test-token")
    bad = _object_node(id="bad", name="x", lastSnapshot="not a time")
    respx.post(GRAPHQL_URL).mock(
        side_effect=graphql_responder(
            {"InventoryPage": [_page([bad, _object_node(id="good", name="y")], None)]}
        )
    )

    assert [o.id for o in client.inventory.all()] == ["good"]


@respx.mock
def test_sample_asks_for_one_page_of_the_first_few() -> None:
    client = RubrikClient(base_url="https://test-instance.my.rubrik.com", token="test-token")
    route = respx.post(GRAPHQL_URL).mock(
        side_effect=graphql_responder(
            {"InventoryPage": [_page([_object_node(id="a", name="vm-a")], "more")]}
        )
    )

    assert [o.id for o in client.inventory.sample(3)] == ["a"]
    assert len(route.calls) == 1
    assert json.loads(route.calls[0].request.content)["variables"] == {"first": 3}


def test_an_object_as_rsc_sends_it() -> None:
    obj = InventoryObject.model_validate(_object_node(id="a", name="vm-a"))

    assert obj.object_type == "VmwareVirtualMachine"
    assert obj.protection_status == "PROTECTED"
    assert obj.sla_domain is not None and obj.sla_domain.name == "Gold"
    assert obj.cluster is not None and obj.cluster.name == "cluster-one"
    assert obj.last_snapshot == datetime(2024, 6, 1, 1, 0, tzinfo=UTC)
    assert obj.org_name is None  # RSC's "" for no organisation
    assert obj.total_snapshots == 42


def test_an_unprotected_object_has_no_sla_domain_or_snapshots() -> None:
    obj = InventoryObject.model_validate(
        _object_node(
            id="a",
            name="mailbox-a",
            objectType="O365Mailbox",
            protectionStatus="NO_SLA",
            complianceStatus="UNPROTECTED",
            slaDomain=None,
            cluster=None,
            lastSnapshot=None,
        )
    )

    assert obj.sla_domain is None and obj.cluster is None and obj.last_snapshot is None


def test_key_prefers_the_global_id() -> None:
    assert InventoryObject(id="local", fid="global", name="x").key == "global"
    assert InventoryObject(id="local", name="x").key == "local"
