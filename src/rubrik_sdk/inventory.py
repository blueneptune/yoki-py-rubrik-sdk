"""The `inventory` domain: every object RSC knows about - VMs, hosts,
databases, file sets, mailboxes, OneDrives, SharePoint sites, Teams... -
whether it is protected, by which SLA domain, and how its backups stand.

RSC calls these "snappables" (anything it can take a snapshot of) and
lists them with `snappableConnection`: the data behind RSC's Object
Compliance report. One row per object, every workload type in one
connection, Microsoft 365 included. RSC refreshes it on its own
schedule; `pull_time` on each object says when that row was computed.

Sourced from `New-RscQuerySnappable.cs` (`snappableConnection`) and
`Schema/Elements/type/Snappable.cs` in
https://github.com/rubrikinc/rubrik-powershell-sdk - field names from
the schema, the selection trimmed to what an inventory wants. Not yet run
against RSC: `rubrik-probe` checks every selected field.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime
from typing import TYPE_CHECKING, Any

from loguru import logger
from pydantic import BaseModel, ValidationError, field_validator

from .common import CAMEL_CONFIG, ClusterReference, SlaDomainReference

if TYPE_CHECKING:
    from .client import RubrikClient


class InventoryObject(BaseModel):
    """One object RSC protects, or could: a VM, host, database, mailbox,
    site, ... with its protection and compliance as RSC last computed
    them."""

    model_config = CAMEL_CONFIG

    id: str
    fid: str | None = None
    name: str
    # RSC's vocabulary: VmwareVirtualMachine, Mssql, O365Mailbox, ...
    object_type: str | None = None
    # Where it is: its host, vCenter, tenant, ... as RSC words it.
    location: str | None = None
    # ACTIVE; RELIC once gone from its source but still holding snapshots.
    object_state: str | None = None
    # PROTECTED, NO_SLA, DO_NOT_PROTECT, ...
    protection_status: str | None = None
    # IN_COMPLIANCE, OUT_OF_COMPLIANCE, UNPROTECTED, ...
    compliance_status: str | None = None
    archival_compliance_status: str | None = None
    replication_compliance_status: str | None = None
    sla_domain: SlaDomainReference | None = None
    cluster: ClusterReference | None = None
    org_id: str | None = None
    org_name: str | None = None
    protected_on: datetime | None = None
    last_snapshot: datetime | None = None
    latest_archival_snapshot: datetime | None = None
    latest_replication_snapshot: datetime | None = None
    awaiting_first_full: bool | None = None
    total_snapshots: int | None = None
    missed_snapshots: int | None = None
    local_snapshots: int | None = None
    archive_snapshots: int | None = None
    replica_snapshots: int | None = None
    # Bytes.
    logical_bytes: int | None = None
    physical_bytes: int | None = None
    local_storage: int | None = None
    archive_storage: int | None = None
    replica_storage: int | None = None
    transferred_bytes: int | None = None
    # When RSC computed this row.
    pull_time: datetime | None = None

    @field_validator("location", "org_name", mode="after")
    @classmethod
    def _blank_is_none(cls, value: str | None) -> str | None:
        return value or None

    @property
    def key(self) -> str:
        """What identifies this object across collections: RSC's global
        id where it gives one, else its `id`."""
        return self.fid or self.id


def parse_object(raw: dict[str, Any]) -> InventoryObject | None:
    """An InventoryObject, or None if this record cannot be read - one odd
    record costs that record, loudly, not the run."""
    try:
        return InventoryObject.model_validate(raw)
    except ValidationError as exc:
        problems = "; ".join(
            f"{'.'.join(str(part) for part in error['loc'])}: {error['msg']}"
            for error in exc.errors()
        )
        logger.error("Skipping object {}: could not read it - {}", raw.get("id"), problems)
        return None


# Every field of Snappable the inventory selects; rubrik-probe checks them.
_OBJECT_FIELDS = """\
        id
        fid
        name
        objectType
        location
        objectState
        protectionStatus
        complianceStatus
        archivalComplianceStatus
        replicationComplianceStatus
        orgId
        orgName
        protectedOn
        lastSnapshot
        latestArchivalSnapshot
        latestReplicationSnapshot
        awaitingFirstFull
        totalSnapshots
        missedSnapshots
        localSnapshots
        archiveSnapshots
        replicaSnapshots
        logicalBytes
        physicalBytes
        localStorage
        archiveStorage
        replicaStorage
        transferredBytes
        pullTime
        slaDomain {
          id
          name
        }
        cluster {
          id
          name
        }
"""

# Sorted by RSC's default (name), so no sort enum value has to be guessed.
_INVENTORY_PAGE_DOCUMENT = (
    """
query InventoryPage($after: String, $first: Int, $filter: SnappableFilterInput) {
  snappableConnection(after: $after, first: $first, filter: $filter) {
    edges {
      node {
"""
    + _OBJECT_FIELDS
    + """      }
    }
    pageInfo {
      endCursor
      hasNextPage
    }
  }
}
"""
)


class InventoryManager:
    """Every object RSC knows about: `rsc.inventory` on a RubrikClient."""

    def __init__(self, client: RubrikClient) -> None:
        self._client = client

    def _page(
        self,
        filter: dict[str, Any] | None,
        first: int,
        after: str | None,  # noqa: A002
    ) -> tuple[list[InventoryObject], str | None]:
        """One page: (the objects that could be read, the cursor for the
        next page or None if this was the last)."""
        variables: dict[str, Any] = {"first": first}
        if filter:
            variables["filter"] = filter
        if after:
            variables["after"] = after
        data = self._client.execute(
            _INVENTORY_PAGE_DOCUMENT, variables, operation_name="InventoryPage"
        )
        connection = data["snappableConnection"]
        objects = [o for edge in connection["edges"] if (o := parse_object(edge["node"]))]
        info = connection.get("pageInfo") or {}
        cursor = info.get("endCursor") if info.get("hasNextPage") else None
        return objects, cursor

    def iter_pages(
        self,
        *,
        filter: dict[str, Any] | None = None,  # noqa: A002 - the GraphQL argument's name
        page_size: int | None = None,
    ) -> Iterator[list[InventoryObject]]:
        """Every object, a page at a time. `filter` is RSC's
        SnappableFilterInput as-is: objectType, protectionStatus,
        objectState, cluster, ... - none means everything."""
        size = page_size or self._client.page_size
        after: str | None = None
        while True:
            objects, after = self._page(filter, size, after)
            if objects:
                yield objects
            if after is None:
                return

    def all(self, *, filter: dict[str, Any] | None = None) -> Iterator[InventoryObject]:  # noqa: A002
        """Every object, one at a time."""
        for page in self.iter_pages(filter=filter):
            yield from page

    def sample(self, limit: int = 5) -> list[InventoryObject]:
        """The first few - one request, for checking the listing works."""
        objects, _ = self._page(None, limit, None)
        return objects
