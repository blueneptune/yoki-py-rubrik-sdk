"""The `sla_domains` domain: the `SlaDomains` query and
`AssignSlasForSnappableHierarchies` mutation from RSC's schema (see
`docs/graphql/operations/SlaDomains.all.query.graphql` and
`AssignSlasForSnappableHierarchies.all.mutation.graphql` in
https://github.com/rubrikinc/rubrik-powershell-sdk).

Deliberately a second, differently-shaped domain from `cluster.py`: RSC's
`slaDomains` field returns a union of two concrete types (`ClusterSlaDomain`
and `GlobalSlaReply`, selected here via inline `... on` fragments) rather
than one plain object type, and this domain also has a mutation
(`assign_to_objects`) alongside its query - showing that a domain manager's
shape follows whatever operations the domain actually needs, not a fixed
CRUD template.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel

from .pagination import Page
from .query import ConnectionQuery

if TYPE_CHECKING:
    from .client import RubrikClient

_CAMEL_CONFIG = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class Duration(BaseModel):
    model_config = _CAMEL_CONFIG

    duration: int
    unit: str


class SlaDomain(BaseModel):
    """One SLA domain. `ClusterSlaDomain` and `GlobalSlaReply` nodes both
    parse into this same model: whichever inline fragment matched supplies
    its fields, the other's are simply absent (left at their defaults)."""

    model_config = _CAMEL_CONFIG

    id: str
    name: str
    description: str | None = None
    protected_object_count: int | None = None
    base_frequency: Duration | None = None
    local_retention_limit: Duration | None = None
    object_types: list[str] | None = None


class SlaAssignResult(BaseModel):
    model_config = _CAMEL_CONFIG

    success: bool


# Real query name/variables/top-level field (`slaDomains`) from the schema's
# `SlaDomains.all.query.graphql`, trimmed to a smaller-but-real field
# selection on each branch of the union (dropping the archival/replication/
# snapshot-schedule detail the full fragment also selects - add it back here
# and to `SlaDomain` above if your use case needs it).
_QUERY_DOCUMENT = """
query SlaDomains(
  $after: String
  $first: Int
  $filter: [GlobalSlaFilterInput!]
  $sortBy: SlaQuerySortByField
  $sortOrder: SortOrder
  $shouldShowProtectedObjectCount: Boolean
) {
  slaDomains(
    after: $after
    first: $first
    filter: $filter
    sortBy: $sortBy
    sortOrder: $sortOrder
    shouldShowProtectedObjectCount: $shouldShowProtectedObjectCount
  ) {
    edges {
      node {
        name
        ... on ClusterSlaDomain {
          id: fid
          protectedObjectCount
          baseFrequency {
            duration
            unit
          }
          localRetentionLimit {
            duration
            unit
          }
        }
        ... on GlobalSlaReply {
          id
          description
          protectedObjectCount
          baseFrequency {
            duration
            unit
          }
          localRetentionLimit {
            duration
            unit
          }
          objectTypes
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
"""

# Real mutation name/variables/fragment from the schema's
# `AssignSlasForSnappableHierarchies.all.mutation.graphql`, used verbatim -
# note `$existing_snapshot_retention`'s snake_case name is the schema's own
# spelling, not a typo introduced here.
_ASSIGN_MUTATION_DOCUMENT = """
mutation AssignSlasForSnappableHierarchies(
  $slaId: UUID
  $globalSlaAssignType: SlaAssignTypeEnum = protectWithSlaId
  $objectIds: [UUID!]!
  $existing_snapshot_retention: GlobalExistingSnapshotRetention
  $shouldApplyToExistingSnapshots: Boolean = false
) {
  assignSlasForSnappableHierarchies(
    globalSlaOptionalFid: $slaId
    globalSlaAssignType: $globalSlaAssignType
    objectIds: $objectIds
    shouldApplyToExistingSnapshots: $shouldApplyToExistingSnapshots
    globalExistingSnapshotRetention: $existing_snapshot_retention
  ) {
    success
  }
}
"""


class SlaDomainQuery(ConnectionQuery[SlaDomain]):
    document = _QUERY_DOCUMENT
    operation_name = "SlaDomains"
    connection_path = ("slaDomains",)
    node_model = SlaDomain


class SlaDomainManager:
    """What you get back as `rsc.sla_domains` from the `RSC` facade (see
    `facade.py`)."""

    def __init__(self, client: RubrikClient) -> None:
        self._client = client

    # `list()` (below) is defined last in this class body, not first: once a
    # method named `list` exists as a class attribute, mypy resolves any
    # later `list[...]` annotation in this same class against *that* method
    # instead of the builtin generic type. Defining it last means every
    # other method's own `list[...]` annotations are still resolved before
    # that name is shadowed.

    def all(
        self,
        *,
        filter: list[dict[str, object]] | None = None,  # noqa: A002
        sort_by: str | None = None,
        sort_order: str | None = None,
    ) -> Iterator[SlaDomain]:
        yield from SlaDomainQuery.fetch_all(
            self._client, filter=filter, sortBy=sort_by, sortOrder=sort_order
        )

    def find_by_name(self, name: str) -> SlaDomain | None:
        for sla_domain in self.all():
            if sla_domain.name == name:
                return sla_domain
        return None

    def assign_to_objects(
        self,
        *,
        object_ids: list[str],
        sla_id: str | None = None,
        assign_type: str = "protectWithSlaId",
        apply_to_existing_snapshots: bool = False,
        existing_snapshot_retention: dict[str, Any] | None = None,
    ) -> SlaAssignResult:
        """Assign (or, with `assign_type="noAssignment"`/`"doNotProtect"` -
        see `SlaAssignTypeEnum` in the schema - unassign) an SLA domain to
        one or more objects."""
        data = self._client.change(
            _ASSIGN_MUTATION_DOCUMENT,
            {
                "slaId": sla_id,
                "globalSlaAssignType": assign_type,
                "objectIds": object_ids,
                "shouldApplyToExistingSnapshots": apply_to_existing_snapshots,
                "existing_snapshot_retention": existing_snapshot_retention,
            },
            operation_name="AssignSlasForSnappableHierarchies",
        )
        return SlaAssignResult(**data["assignSlasForSnappableHierarchies"])

    def list(
        self,
        *,
        first: int | None = None,
        after: str | None = None,
        filter: list[dict[str, object]] | None = None,  # noqa: A002
        sort_by: str | None = None,
        sort_order: str | None = None,
        should_show_protected_object_count: bool | None = None,
    ) -> Page[SlaDomain]:
        return SlaDomainQuery.fetch_page(
            self._client,
            first=first,
            after=after,
            filter=filter,
            sortBy=sort_by,
            sortOrder=sort_order,
            shouldShowProtectedObjectCount=should_show_protected_object_count,
        )
