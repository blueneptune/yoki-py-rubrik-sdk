"""The `clusters` domain: the `Cluster` query from RSC's schema (see
`docs/graphql/operations/Cluster.all.query.graphql` and its
`GeoLocation.graphql`/`ClusterMetric.graphql`/`PageInfo.all.query.graphql`
fragments in https://github.com/rubrikinc/rubrik-powershell-sdk), wrapped as
a `ConnectionQuery` plus a small ergonomic `ClusterManager` on top.

This is the template to copy (see `facade.py`'s docstring) when adding the
next domain: a pydantic model matching the fields you select, a
`_DOCUMENT` constant with the real query/mutation text, a `ConnectionQuery`
subclass wiring the two together, and a manager class exposing whatever
shape of methods makes sense for that domain - `list`/`all`/`find_by_name`
here, but a domain built around a single object (rather than a collection)
or a mutation-heavy one (like `sla_domain.py`'s `assign_to_objects`) will
look different, because GraphQL operations - unlike REST's uniform
save/delete/load/find - don't share one generic shape across domains.

The field selection below is a real, executable subset of the schema's
actual `ClusterFragment1` (trimmed to the fields most SDK users care about -
add more by editing `_DOCUMENT` and `Cluster` together) rather than a
same-shaped invention, so responses from a real RSC instance parse directly
into these models.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import TYPE_CHECKING

from pydantic import BaseModel

from .common import CAMEL_CONFIG
from .pagination import Page
from .query import ConnectionQuery

if TYPE_CHECKING:
    from .client import RubrikClient


class CloudInfo(BaseModel):
    model_config = CAMEL_CONFIG

    region: str | None = None
    vendor: str | None = None


class ClusterNode(BaseModel):
    model_config = CAMEL_CONFIG

    id: str
    ip_address: str | None = None
    status: str | None = None
    cpu_cores: int | None = None
    ram: int | None = None


class ClusterNodeConnection(BaseModel):
    model_config = CAMEL_CONFIG

    count: int
    nodes: list[ClusterNode] = []


class GeoLocation(BaseModel):
    model_config = CAMEL_CONFIG

    address: str | None = None
    latitude: float | None = None
    longitude: float | None = None


class ClusterMetric(BaseModel):
    model_config = CAMEL_CONFIG

    available_capacity: float | None = None
    used_capacity: float | None = None
    total_capacity: float | None = None
    snapshot_capacity: float | None = None
    live_mount_capacity: float | None = None
    miscellaneous_capacity: float | None = None
    ingested_snapshot_storage: float | None = None
    physical_snapshot_storage: float | None = None
    ingested_archival_storage: float | None = None
    physical_archival_storage: float | None = None
    immutability_overhead: float | None = None
    last_update_time: str | None = None


class Cluster(BaseModel):
    model_config = CAMEL_CONFIG

    id: str
    name: str
    version: str | None = None
    status: str | None = None
    sub_status: str | None = None
    pause_status: str | None = None
    type: str | None = None
    product_type: str | None = None
    timezone: str | None = None
    registration_time: str | None = None
    last_connection_time: str | None = None
    is_healthy: bool | None = None
    snapshot_count: int | None = None
    encryption_enabled: bool | None = None
    cloud_info: CloudInfo | None = None
    cluster_node_connection: ClusterNodeConnection | None = None
    geo_location: GeoLocation | None = None
    metric: ClusterMetric | None = None


# Real query name, variables, and top-level field (`clusterConnection`) from
# the schema's `Cluster.all.query.graphql`; the field selection inside
# `ClusterFragment` is the trimmed subset described in the module docstring,
# inlining the real `GeoLocationFragment_All`/`ClusterMetricFragment_All`
# fragments so this document is self-contained (no external fragment
# references RSC would reject as unresolved).
_DOCUMENT = """
query Cluster(
  $first: Int
  $after: String
  $filter: ClusterFilterInput
  $sortBy: ClusterSortByEnum
  $sortOrder: SortOrder
) {
  clusterConnection(
    filter: $filter
    sortBy: $sortBy
    sortOrder: $sortOrder
    first: $first
    after: $after
  ) {
    edges {
      node {
        ...ClusterFragment
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

fragment ClusterFragment on Cluster {
  id
  name
  version
  status
  subStatus
  pauseStatus
  type
  productType
  timezone
  registrationTime
  lastConnectionTime
  isHealthy
  snapshotCount
  encryptionEnabled
  cloudInfo {
    region
    vendor
  }
  clusterNodeConnection {
    count
    nodes {
      id
      ipAddress
      status
      cpuCores
      ram
    }
  }
  geoLocation {
    address
    latitude
    longitude
  }
  metric {
    availableCapacity
    usedCapacity
    totalCapacity
    snapshotCapacity
    liveMountCapacity
    miscellaneousCapacity
    ingestedSnapshotStorage
    physicalSnapshotStorage
    ingestedArchivalStorage
    physicalArchivalStorage
    immutabilityOverhead
    lastUpdateTime
  }
}
"""


class ClusterQuery(ConnectionQuery[Cluster]):
    document = _DOCUMENT
    operation_name = "Cluster"
    connection_path = ("clusterConnection",)
    node_model = Cluster


class ClusterManager:
    """What you get back as `rsc.clusters` from the `RSC` facade (see
    `facade.py`). Deliberately thin - it just calls `ClusterQuery` with the
    client it was given at construction time, so `rsc.clusters.all()` reads
    like a plain method call with no client-wiring visible at the call
    site.
    """

    def __init__(self, client: RubrikClient) -> None:
        self._client = client

    def list(
        self,
        *,
        first: int | None = None,
        after: str | None = None,
        filter: dict[str, object] | None = None,  # noqa: A002 - mirrors the GraphQL arg name
        sort_by: str | None = None,
        sort_order: str | None = None,
    ) -> Page[Cluster]:
        """Fetch a single page of clusters.

        `filter`/`sort_by`/`sort_order` are passed straight through as the
        `ClusterFilterInput`/`ClusterSortByEnum`/`SortOrder` GraphQL
        variables - see the RSC schema for the exact shapes/values those
        accept, since this SDK doesn't (yet) model every input type as its
        own pydantic class.
        """
        return ClusterQuery.fetch_page(
            self._client,
            first=first,
            after=after,
            filter=filter,
            sortBy=sort_by,
            sortOrder=sort_order,
        )

    def all(
        self,
        *,
        filter: dict[str, object] | None = None,  # noqa: A002
        sort_by: str | None = None,
        sort_order: str | None = None,
    ) -> Iterator[Cluster]:
        """Auto-paginated: yields every cluster across every page."""
        yield from ClusterQuery.fetch_all(
            self._client, filter=filter, sortBy=sort_by, sortOrder=sort_order
        )

    def find_by_name(self, name: str) -> Cluster | None:
        for cluster in self.all():
            if cluster.name == name:
                return cluster
        return None
