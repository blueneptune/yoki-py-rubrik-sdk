"""The `mssql_databases` domain: which client machines have SQL Server
databases, whether each database is actually being backed up, and each
database's snapshot (backup) history.

Sourced from `docs/graphql/operations/MssqlDatabases.all.query.graphql`,
`MssqlDatabaseDetails.all.query.graphql`, and
`MssqlDatabaseSnapshots.all.query.graphql` in
https://github.com/rubrikinc/rubrik-powershell-sdk.

A third connection shape, alongside `cluster.py`'s Relay `edges`/`pageInfo`
connections and `activity.py`'s identical shape: RSC's `mssqlDatabases`
field returns a *flat* `nodes` list with no pagination arguments at all (two
independent curated queries in the schema's own docs both call it with zero
arguments) - so `MssqlDatabaseManager.list()` calls `client.execute()`
directly instead of going through `ConnectionQuery`, which assumes a paged
connection, and wraps the result in `Collection` (a pydantic `Page` without
`page_info`) rather than `Page` itself. `cdmSnapshots` (this module's
snapshot/backup history), by contrast, *is* a paged connection and does use
`ConnectionQuery` - nested one level inside `mssqlDatabase(fid: ...)` rather
than at the top level of `data`, which `connection_path`'s multi-segment
lookup handles unchanged.
"""

from __future__ import annotations

from collections.abc import Iterator

from pydantic import BaseModel

from .client import RscClient
from .common import CAMEL_CONFIG, ClusterReference, SlaDomainReference
from .pagination import Collection, Page
from .query import ConnectionQuery


class PathNode(BaseModel):
    """One segment of a database's `physical_path`/`logical_path` - the
    chain of ancestors (host, instance, availability group, ...) leading to
    it. The last entry is generally the client machine or instance the
    database actually lives on - see `MssqlDatabase.host_name`."""

    model_config = CAMEL_CONFIG

    fid: str | None = None
    name: str
    object_type: str | None = None


class PrimaryClusterLocation(BaseModel):
    model_config = CAMEL_CONFIG

    name: str | None = None


class SnapshotCount(BaseModel):
    model_config = CAMEL_CONFIG

    count: int


class MssqlDatabase(BaseModel):
    """One discovered SQL Server database, as returned by listing every
    database in the environment (`MssqlDatabaseManager.list()`)."""

    model_config = CAMEL_CONFIG

    id: str
    name: str
    dag_id: str | None = None
    physical_path: list[PathNode] = []
    logical_path: list[PathNode] = []
    is_in_availability_group: bool | None = None
    cdm_link: str | None = None
    cdm_id: str | None = None
    cluster: ClusterReference | None = None
    effective_sla_domain: SlaDomainReference | None = None
    primary_cluster_location: PrimaryClusterLocation | None = None
    recovery_model: str | None = None
    sla_assignment: str | None = None
    configured_sla_domain: SlaDomainReference | None = None

    @property
    def is_protected(self) -> bool:
        """Whether RSC is actually backing this database up. A database
        RSC has discovered but never had an SLA domain assigned to has no
        `effective_sla_domain` - this is the "discovered but not backed up"
        case."""
        return self.effective_sla_domain is not None

    @property
    def host_name(self) -> str | None:
        """The client machine/instance this database lives on: the
        deepest (last) segment of `physical_path`."""
        return self.physical_path[-1].name if self.physical_path else None


class MssqlDatabaseDetails(BaseModel):
    """Richer detail for one specific database (`MssqlDatabaseManager.get()`)
    than the `MssqlDatabase` summary `list()` returns - protection-relevant
    fields like `is_relic`/`unprotectable_reasons`/`is_online`, log-backup
    settings, and a snapshot count without paging through the snapshots
    themselves (see `snapshots()` for that)."""

    model_config = CAMEL_CONFIG

    id: str
    cdm_id: str | None = None
    name: str
    recovery_model: str | None = None
    is_relic: bool | None = None
    unprotectable_reasons: list[str] | None = None
    is_log_shipping_secondary: bool | None = None
    is_online: bool | None = None
    copy_only: bool | None = None
    is_in_availability_group: bool | None = None
    effective_sla_domain: SlaDomainReference | None = None
    logical_path: list[PathNode] = []
    physical_path: list[PathNode] = []
    cluster: ClusterReference | None = None
    cdm_snapshots: SnapshotCount | None = None
    authorized_operations: list[str] | None = None
    log_backup_frequency_in_seconds: int | None = None
    log_backup_retention_in_hours: int | None = None
    has_log_config_from_sla: bool | None = None

    @property
    def is_protected(self) -> bool:
        return self.effective_sla_domain is not None

    @property
    def host_name(self) -> str | None:
        return self.physical_path[-1].name if self.physical_path else None


class MssqlSnapshot(BaseModel):
    """One backup (snapshot) of a database - an entry in its backup
    history, as returned by `MssqlDatabaseManager.snapshots()`/
    `.all_snapshots()`."""

    model_config = CAMEL_CONFIG

    id: str
    date: str | None = None
    expiration_date: str | None = None
    expiry_hint: str | None = None
    workload_id: str | None = None
    is_corrupted: bool | None = None
    indexing_attempts: int | None = None
    is_indexed: bool | None = None
    is_unindexable: bool | None = None
    is_on_demand_snapshot: bool | None = None
    workload_type: str | None = None
    cluster_uuid: str | None = None
    cdm_id: str | None = None
    cdm_version: str | None = None
    is_downloaded_snapshot: bool | None = None
    is_expired: bool | None = None
    sla_domain: SlaDomainReference | None = None


# Real query name/field selection from the schema's
# `MssqlDatabases.all.query.graphql`, used as-is. Not a Relay connection -
# `mssqlDatabases` returns a flat `nodes` list (see module docstring), so
# there's no `first`/`after`/`pageInfo` here at all.
_LIST_DOCUMENT = """
query MssqlDatabases {
  mssqlDatabases {
    nodes {
      id
      name
      dagId
      physicalPath {
        fid
        name
      }
      logicalPath {
        fid
        name
      }
      isInAvailabilityGroup
      cdmLink
      cdmId
      cluster {
        id
        name
      }
      effectiveSlaDomain {
        id
        name
      }
      primaryClusterLocation {
        name
      }
      recoveryModel
      slaAssignment
      configuredSlaDomain {
        id
        name
      }
    }
  }
}
"""

# Trimmed-but-real subset of `MssqlDatabaseDetails.all.query.graphql`'s
# fragment (dropping its replicas/pendingSla/replicatedObjects/cluster
# connectivity detail - add them back here and to `MssqlDatabaseDetails`
# above if your use case needs them).
_GET_DOCUMENT = """
query MssqlDatabaseDetails($fid: UUID!) {
  mssqlDatabase(fid: $fid) {
    id
    cdmId
    name
    recoveryModel
    isRelic
    unprotectableReasons
    isLogShippingSecondary
    isOnline
    copyOnly
    isInAvailabilityGroup
    effectiveSlaDomain {
      id
      name
    }
    logicalPath {
      name
      objectType
    }
    physicalPath {
      name
      objectType
    }
    cluster {
      id
      name
      status
      version
    }
    cdmSnapshots {
      count
    }
    authorizedOperations
    logBackupFrequencyInSeconds
    logBackupRetentionInHours
    hasLogConfigFromSla
  }
}
"""

# Trimmed-but-real subset of `MssqlDatabaseSnapshots.all.query.graphql`'s
# fragment (dropping `subObjs`/`latestUserNote`/`retentionInfo` detail).
# `cdmSnapshots(first:, after:)` and its `pageInfo` block are this module's
# own addition, not present in the source file (which calls `cdmSnapshots`
# with no arguments and doesn't select `pageInfo` at all) - added on the
# well-grounded but unverified assumption that it follows the same
# first/after/pageInfo convention every other paginated connection in this
# schema uses (`clusterConnection`, `slaDomains`, `activitySeriesConnection`
# all do). If a real RSC instance rejects these arguments, drop them and
# `MssqlSnapshotQuery.fetch_all()` will just return everything in one page.
_SNAPSHOTS_DOCUMENT = """
query MssqlDatabaseSnapshots($fid: UUID!, $first: Int, $after: String) {
  mssqlDatabase(fid: $fid) {
    cdmSnapshots(first: $first, after: $after) {
      edges {
        node {
          id
          date
          expirationDate
          expiryHint
          workloadId
          isCorrupted
          indexingAttempts
          isIndexed
          isUnindexable
          isOnDemandSnapshot
          workloadType
          clusterUuid
          cdmId
          cdmVersion
          isDownloadedSnapshot
          isExpired
          slaDomain {
            id
            name
          }
        }
      }
      pageInfo {
        startCursor
        endCursor
        hasNextPage
        hasPreviousPage
      }
    }
  }
}
"""


class MssqlSnapshotQuery(ConnectionQuery[MssqlSnapshot]):
    document = _SNAPSHOTS_DOCUMENT
    operation_name = "MssqlDatabaseSnapshots"
    connection_path = ("mssqlDatabase", "cdmSnapshots")
    node_model = MssqlSnapshot


class MssqlDatabaseManager:
    """What you get back as `rsc.mssql_databases` from the `RSC` facade
    (see `facade.py`)."""

    def __init__(self, client: RscClient) -> None:
        self._client = client

    # `list()` (below) is defined last in this class body, not first: once a
    # method named `list` exists as a class attribute, mypy resolves any
    # later `list[...]` annotation in this same class against *that* method
    # instead of the builtin generic type (see the identical note in
    # `sla_domain.py`'s `SlaDomainManager`).

    def for_host(self, host_name: str) -> Collection[MssqlDatabase]:
        """Every database discovered on one client machine, matched by
        `MssqlDatabase.host_name` (the deepest segment of its
        `physical_path`)."""
        matches = [database for database in self.list().items if database.host_name == host_name]
        return Collection(items=matches)

    def unprotected(self) -> Collection[MssqlDatabase]:
        """Databases RSC has discovered but that aren't actually being
        backed up - no effective SLA domain assigned. Combine with
        `for_host()` to answer "what did we find on this machine that isn't
        protected?"."""
        unprotected = [database for database in self.list().items if not database.is_protected]
        return Collection(items=unprotected)

    def get(self, database_id: str) -> MssqlDatabaseDetails:
        """Protection/backup-relevant detail for one database - use this
        after `list()`/`for_host()` to drill into a specific database's
        `id`."""
        data = self._client.execute(
            _GET_DOCUMENT, {"fid": database_id}, operation_name="MssqlDatabaseDetails"
        )
        return MssqlDatabaseDetails(**data["mssqlDatabase"])

    def snapshots(self, database_id: str, *, first: int | None = None) -> Page[MssqlSnapshot]:
        """A single page of one database's backup history."""
        return MssqlSnapshotQuery.fetch_page(self._client, fid=database_id, first=first)

    def all_snapshots(self, database_id: str) -> Iterator[MssqlSnapshot]:
        """Auto-paginated: yields a database's entire backup history."""
        yield from MssqlSnapshotQuery.fetch_all(self._client, fid=database_id)

    def list(self) -> Collection[MssqlDatabase]:
        """Every SQL Server database RSC has discovered, across every
        client machine. Not paginated - see the module docstring."""
        data = self._client.execute(_LIST_DOCUMENT, operation_name="MssqlDatabases")
        databases = [MssqlDatabase(**node) for node in data["mssqlDatabases"]["nodes"]]
        return Collection(items=databases)
