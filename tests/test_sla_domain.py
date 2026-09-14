import json
from typing import Any

import respx

from rubrik_rsc import RscClient, SlaDomainManager

from .conftest import GRAPHQL_URL, graphql_responder, make_page_info


def _cluster_sla_domain_node(*, id: str, name: str) -> dict[str, Any]:  # noqa: A002
    """Shaped like a `ClusterSlaDomain` match: `id` (aliased from `fid` in
    the real query) and no `description`/`objectTypes`, since those only
    exist on the `GlobalSlaReply` branch."""
    return {
        "name": name,
        "id": id,
        "protectedObjectCount": 12,
        "baseFrequency": {"duration": 1, "unit": "DAYS"},
        "localRetentionLimit": {"duration": 30, "unit": "DAYS"},
    }


def _global_sla_reply_node(*, id: str, name: str) -> dict[str, Any]:  # noqa: A002
    return {
        "name": name,
        "id": id,
        "description": "Global gold policy",
        "protectedObjectCount": 100,
        "baseFrequency": {"duration": 1, "unit": "DAYS"},
        "localRetentionLimit": {"duration": 90, "unit": "DAYS"},
        "objectTypes": ["VirtualMachine", "MssqlDatabase"],
    }


def _sla_domain_page(
    *, nodes: list[dict[str, Any]], has_next_page: bool, end_cursor: str | None
) -> dict[str, Any]:
    return {
        "data": {
            "slaDomains": {
                "edges": [{"node": node} for node in nodes],
                "pageInfo": make_page_info(has_next_page=has_next_page, end_cursor=end_cursor),
            }
        }
    }


@respx.mock
def test_list_parses_both_cluster_and_global_sla_domain_variants() -> None:
    client = RscClient("https://test-instance.my.rubrik.com", token="test-token")
    respx.post(GRAPHQL_URL).mock(
        side_effect=graphql_responder(
            {
                "SlaDomains": [
                    _sla_domain_page(
                        nodes=[
                            _cluster_sla_domain_node(id="s1", name="Bronze"),
                            _global_sla_reply_node(id="s2", name="Gold"),
                        ],
                        has_next_page=False,
                        end_cursor=None,
                    )
                ]
            }
        )
    )
    manager = SlaDomainManager(client)

    page = manager.list()

    bronze, gold = page.items
    assert bronze.id == "s1"
    assert bronze.name == "Bronze"
    assert bronze.description is None
    assert bronze.local_retention_limit is not None
    assert bronze.local_retention_limit.duration == 30

    assert gold.id == "s2"
    assert gold.description == "Global gold policy"
    assert gold.object_types == ["VirtualMachine", "MssqlDatabase"]


@respx.mock
def test_all_auto_paginates_across_multiple_pages() -> None:
    client = RscClient("https://test-instance.my.rubrik.com", token="test-token")
    respx.post(GRAPHQL_URL).mock(
        side_effect=graphql_responder(
            {
                "SlaDomains": [
                    _sla_domain_page(
                        nodes=[_cluster_sla_domain_node(id="s1", name="Bronze")],
                        has_next_page=True,
                        end_cursor="cursor-1",
                    ),
                    _sla_domain_page(
                        nodes=[_global_sla_reply_node(id="s2", name="Gold")],
                        has_next_page=False,
                        end_cursor=None,
                    ),
                ]
            }
        )
    )
    manager = SlaDomainManager(client)

    sla_domains = list(manager.all())

    assert [s.name for s in sla_domains] == ["Bronze", "Gold"]


@respx.mock
def test_find_by_name_returns_matching_sla_domain() -> None:
    client = RscClient("https://test-instance.my.rubrik.com", token="test-token")
    respx.post(GRAPHQL_URL).mock(
        side_effect=graphql_responder(
            {
                "SlaDomains": [
                    _sla_domain_page(
                        nodes=[_global_sla_reply_node(id="s2", name="Gold")],
                        has_next_page=False,
                        end_cursor=None,
                    )
                ]
            }
        )
    )
    manager = SlaDomainManager(client)

    found = manager.find_by_name("Gold")

    assert found is not None
    assert found.id == "s2"


@respx.mock
def test_assign_to_objects_sends_expected_mutation_variables() -> None:
    client = RscClient("https://test-instance.my.rubrik.com", token="test-token")
    route = respx.post(GRAPHQL_URL).mock(
        side_effect=graphql_responder(
            {
                "AssignSlasForSnappableHierarchies": [
                    {"data": {"assignSlasForSnappableHierarchies": {"success": True}}}
                ]
            }
        )
    )
    manager = SlaDomainManager(client)

    result = manager.assign_to_objects(object_ids=["obj-1", "obj-2"], sla_id="sla-1")

    assert result.success is True
    sent_body = json.loads(route.calls.last.request.content)
    assert sent_body["operationName"] == "AssignSlasForSnappableHierarchies"
    assert sent_body["variables"] == {
        "slaId": "sla-1",
        "globalSlaAssignType": "protectWithSlaId",
        "objectIds": ["obj-1", "obj-2"],
        "shouldApplyToExistingSnapshots": False,
        "existing_snapshot_retention": None,
    }
