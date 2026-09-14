from typing import Any

import respx

from rubrik_rsc import MssqlDatabaseManager, RscClient

from .conftest import GRAPHQL_URL, graphql_responder, make_page_info


def _database_node(
    *,
    id: str,  # noqa: A002
    name: str,
    host: str,
    protected: bool = True,
) -> dict[str, Any]:
    return {
        "id": id,
        "name": name,
        "dagId": None,
        "physicalPath": [{"fid": "host-fid", "name": host}],
        "logicalPath": [{"fid": "instance-fid", "name": f"{host}\\MSSQLSERVER"}],
        "isInAvailabilityGroup": False,
        "cdmLink": None,
        "cdmId": f"cdm-{id}",
        "cluster": {"id": "c1", "name": "cluster-one"},
        "effectiveSlaDomain": {"id": "sla-1", "name": "Gold"} if protected else None,
        "primaryClusterLocation": {"name": "cluster-one"},
        "recoveryModel": "FULL",
        "slaAssignment": "Direct" if protected else "Unassigned",
        "configuredSlaDomain": {"id": "sla-1", "name": "Gold"} if protected else None,
    }


@respx.mock
def test_list_returns_every_database_from_the_flat_nodes_list() -> None:
    client = RscClient("https://test-instance.my.rubrik.com", token="test-token")
    respx.post(GRAPHQL_URL).mock(
        side_effect=graphql_responder(
            {
                "MssqlDatabases": [
                    {
                        "data": {
                            "mssqlDatabases": {
                                "nodes": [
                                    _database_node(
                                        id="db-1", name="AdventureWorks", host="sql-prod-01"
                                    ),
                                    _database_node(
                                        id="db-2",
                                        name="Scratch",
                                        host="sql-prod-02",
                                        protected=False,
                                    ),
                                ]
                            }
                        }
                    }
                ]
            }
        )
    )
    manager = MssqlDatabaseManager(client)

    databases = manager.list()

    assert [d.name for d in databases.items] == ["AdventureWorks", "Scratch"]
    assert databases.items[0].host_name == "sql-prod-01"
    assert databases.items[0].is_protected is True
    assert databases.items[1].is_protected is False


@respx.mock
def test_for_host_filters_databases_by_deepest_physical_path_segment() -> None:
    client = RscClient("https://test-instance.my.rubrik.com", token="test-token")
    respx.post(GRAPHQL_URL).mock(
        side_effect=graphql_responder(
            {
                "MssqlDatabases": [
                    {
                        "data": {
                            "mssqlDatabases": {
                                "nodes": [
                                    _database_node(
                                        id="db-1", name="AdventureWorks", host="sql-prod-01"
                                    ),
                                    _database_node(id="db-2", name="Northwind", host="sql-prod-01"),
                                    _database_node(id="db-3", name="Other", host="sql-prod-02"),
                                ]
                            }
                        }
                    }
                ]
            }
        )
    )
    manager = MssqlDatabaseManager(client)

    databases = manager.for_host("sql-prod-01")

    assert {d.name for d in databases.items} == {"AdventureWorks", "Northwind"}


@respx.mock
def test_unprotected_returns_only_databases_without_an_effective_sla_domain() -> None:
    client = RscClient("https://test-instance.my.rubrik.com", token="test-token")
    respx.post(GRAPHQL_URL).mock(
        side_effect=graphql_responder(
            {
                "MssqlDatabases": [
                    {
                        "data": {
                            "mssqlDatabases": {
                                "nodes": [
                                    _database_node(
                                        id="db-1", name="AdventureWorks", host="sql-prod-01"
                                    ),
                                    _database_node(
                                        id="db-2",
                                        name="DiscoveredNotBackedUp",
                                        host="sql-prod-01",
                                        protected=False,
                                    ),
                                ]
                            }
                        }
                    }
                ]
            }
        )
    )
    manager = MssqlDatabaseManager(client)

    unprotected = manager.unprotected()

    assert [d.name for d in unprotected.items] == ["DiscoveredNotBackedUp"]


@respx.mock
def test_get_returns_database_details() -> None:
    client = RscClient("https://test-instance.my.rubrik.com", token="test-token")
    respx.post(GRAPHQL_URL).mock(
        side_effect=graphql_responder(
            {
                "MssqlDatabaseDetails": [
                    {
                        "data": {
                            "mssqlDatabase": {
                                "id": "db-1",
                                "cdmId": "cdm-db-1",
                                "name": "AdventureWorks",
                                "recoveryModel": "FULL",
                                "isRelic": False,
                                "unprotectableReasons": [],
                                "isLogShippingSecondary": False,
                                "isOnline": True,
                                "copyOnly": False,
                                "isInAvailabilityGroup": False,
                                "effectiveSlaDomain": {"id": "sla-1", "name": "Gold"},
                                "logicalPath": [
                                    {
                                        "name": "sql-prod-01\\MSSQLSERVER",
                                        "objectType": "MssqlInstance",
                                    }
                                ],
                                "physicalPath": [
                                    {"name": "sql-prod-01", "objectType": "PhysicalHost"}
                                ],
                                "cluster": {"id": "c1", "name": "cluster-one"},
                                "cdmSnapshots": {"count": 42},
                                "authorizedOperations": ["Restore"],
                                "logBackupFrequencyInSeconds": 900,
                                "logBackupRetentionInHours": 24,
                                "hasLogConfigFromSla": True,
                            }
                        }
                    }
                ]
            }
        )
    )
    manager = MssqlDatabaseManager(client)

    details = manager.get("db-1")

    assert details.is_online is True
    assert details.is_relic is False
    assert details.is_protected is True
    assert details.host_name == "sql-prod-01"
    assert details.cdm_snapshots is not None
    assert details.cdm_snapshots.count == 42


def _snapshot_node(*, id: str, corrupted: bool = False) -> dict[str, Any]:  # noqa: A002
    return {
        "id": id,
        "date": "2024-06-01T00:00:00Z",
        "expirationDate": "2024-07-01T00:00:00Z",
        "expiryHint": None,
        "workloadId": "db-1",
        "isCorrupted": corrupted,
        "indexingAttempts": 1,
        "isIndexed": True,
        "isUnindexable": False,
        "isOnDemandSnapshot": False,
        "workloadType": "Mssql",
        "clusterUuid": "c1",
        "cdmId": f"cdm-{id}",
        "cdmVersion": "9.1.0",
        "isDownloadedSnapshot": False,
        "isExpired": False,
        "slaDomain": {"id": "sla-1", "name": "Gold"},
    }


@respx.mock
def test_snapshots_returns_a_single_page_of_backup_history() -> None:
    client = RscClient("https://test-instance.my.rubrik.com", token="test-token")
    respx.post(GRAPHQL_URL).mock(
        side_effect=graphql_responder(
            {
                "MssqlDatabaseSnapshots": [
                    {
                        "data": {
                            "mssqlDatabase": {
                                "cdmSnapshots": {
                                    "edges": [{"node": _snapshot_node(id="snap-1")}],
                                    "pageInfo": make_page_info(
                                        has_next_page=False, end_cursor=None
                                    ),
                                }
                            }
                        }
                    }
                ]
            }
        )
    )
    manager = MssqlDatabaseManager(client)

    page = manager.snapshots("db-1")

    assert len(page.items) == 1
    assert page.items[0].id == "snap-1"
    assert page.items[0].is_corrupted is False


@respx.mock
def test_all_snapshots_auto_paginates_a_databases_full_backup_history() -> None:
    client = RscClient("https://test-instance.my.rubrik.com", token="test-token")
    respx.post(GRAPHQL_URL).mock(
        side_effect=graphql_responder(
            {
                "MssqlDatabaseSnapshots": [
                    {
                        "data": {
                            "mssqlDatabase": {
                                "cdmSnapshots": {
                                    "edges": [{"node": _snapshot_node(id="snap-1")}],
                                    "pageInfo": make_page_info(
                                        has_next_page=True, end_cursor="cursor-1"
                                    ),
                                }
                            }
                        }
                    },
                    {
                        "data": {
                            "mssqlDatabase": {
                                "cdmSnapshots": {
                                    "edges": [
                                        {"node": _snapshot_node(id="snap-2", corrupted=True)}
                                    ],
                                    "pageInfo": make_page_info(
                                        has_next_page=False, end_cursor=None
                                    ),
                                }
                            }
                        }
                    },
                ]
            }
        )
    )
    manager = MssqlDatabaseManager(client)

    snapshots = list(manager.all_snapshots("db-1"))

    assert [s.id for s in snapshots] == ["snap-1", "snap-2"]
    assert snapshots[1].is_corrupted is True
