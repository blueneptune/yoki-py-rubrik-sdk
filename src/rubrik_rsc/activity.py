"""The `jobs` domain: job history.

RSC calls this "activity series" internally rather than "jobs" - every
backup, replication, archival, etc. run shows up as one `ActivitySeries`
(a chain of individual activity events over time), queried via
`activitySeriesConnection`. This module wraps that under the more
task-oriented name a caller asking for "job history" would expect.

Sourced from `docs/graphql/operations/ActivitySeriesConnection.all.query.graphql`
and `TaskchainStatus.all.query.graphql` in
https://github.com/rubrikinc/rubrik-powershell-sdk, used close to verbatim -
this domain's field selection is already small enough that no trimming was
needed (contrast `cluster.py`/`sla_domain.py`, which do trim their much
larger real fragments).
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from pydantic import BaseModel

from .client import RscClient
from .common import CAMEL_CONFIG, ClusterReference
from .pagination import Page
from .query import ConnectionQuery


class ActivityEvent(BaseModel):
    model_config = CAMEL_CONFIG

    id: str
    message: str | None = None
    severity: str | None = None
    time: str | None = None


class ActivityConnection(BaseModel):
    model_config = CAMEL_CONFIG

    nodes: list[ActivityEvent] = []


class ActivitySeries(BaseModel):
    """One job's history: its current status/progress plus the individual
    activity events (`activity_connection`) that make up its timeline."""

    model_config = CAMEL_CONFIG

    id: str
    fid: str | None = None
    activity_series_id: str | None = None
    start_time: str | None = None
    last_updated: str | None = None
    last_activity_type: str | None = None
    last_activity_status: str | None = None
    location: str | None = None
    object_name: str | None = None
    object_id: str | None = None
    object_type: str | None = None
    severity: str | None = None
    progress: str | None = None
    sla_domain_name: str | None = None
    cluster: ClusterReference | None = None
    activity_connection: ActivityConnection | None = None


class Taskchain(BaseModel):
    """The live status of one currently (or recently) running job, queried
    by its taskchain id - distinct from `ActivitySeries`, which is history
    rather than a point-in-time status check."""

    model_config = CAMEL_CONFIG

    id: str
    state: str | None = None
    taskchain_uuid: str | None = None
    progressed_at: str | None = None


# Real query name/variables/field selection from the schema's
# `ActivitySeriesConnection.all.query.graphql`, used as-is.
_ACTIVITY_SERIES_DOCUMENT = """
query ActivitySeriesConnection(
  $after: String
  $filters: ActivitySeriesFilter
  $first: Int
  $sortBy: ActivitySeriesSortField
  $sortOrder: SortOrder
) {
  activitySeriesConnection(
    after: $after
    first: $first
    filters: $filters
    sortBy: $sortBy
    sortOrder: $sortOrder
  ) {
    edges {
      node {
        id
        fid
        activitySeriesId
        startTime
        lastUpdated
        lastActivityType
        lastActivityStatus
        location
        objectName
        objectId
        objectType
        severity
        progress
        slaDomainName
        cluster {
          id
          name
        }
        activityConnection {
          nodes {
            id
            message
            severity
            time
          }
        }
      }
    }
    pageInfo {
      endCursor
      hasNextPage
      hasPreviousPage
    }
  }
}
"""

# Real query name/variables/fragment from the schema's
# `TaskchainStatus.all.query.graphql`, used as-is - including its outer
# variable being named `$filter` even though it holds a taskchain id, not a
# filter object (the schema's own naming, not a mistake introduced here).
_TASKCHAIN_STATUS_DOCUMENT = """
query TaskchainStatus($filter: String!) {
  getKorgTaskchainStatus(taskchainId: $filter) {
    taskchain {
      id
      state
      taskchainUuid
      ... on Taskchain {
        progressedAt
      }
    }
  }
}
"""


class ActivitySeriesQuery(ConnectionQuery[ActivitySeries]):
    document = _ACTIVITY_SERIES_DOCUMENT
    operation_name = "ActivitySeriesConnection"
    connection_path = ("activitySeriesConnection",)
    node_model = ActivitySeries


class ActivitySeriesManager:
    """What you get back as `rsc.jobs` from the `RSC` facade (see
    `facade.py`)."""

    def __init__(self, client: RscClient) -> None:
        self._client = client

    def list(
        self,
        *,
        first: int | None = None,
        after: str | None = None,
        filter: dict[str, Any] | None = None,  # noqa: A002
        sort_by: str | None = None,
        sort_order: str | None = None,
    ) -> Page[ActivitySeries]:
        """Fetch a single page of job history.

        `filter` is passed straight through as the `ActivitySeriesFilter`
        GraphQL variable - two of its fields are confirmed real by the
        schema's own docs (`lastActivityType`, `startTimeGt`); consult the
        RSC schema for the rest.
        """
        return ActivitySeriesQuery.fetch_page(
            self._client,
            first=first,
            after=after,
            filters=filter,
            sortBy=sort_by,
            sortOrder=sort_order,
        )

    def all(
        self,
        *,
        filter: dict[str, Any] | None = None,  # noqa: A002
        sort_by: str | None = None,
        sort_order: str | None = None,
    ) -> Iterator[ActivitySeries]:
        """Auto-paginated: yields every matching job across every page."""
        yield from ActivitySeriesQuery.fetch_all(
            self._client, filters=filter, sortBy=sort_by, sortOrder=sort_order
        )

    def for_object(self, object_id: str, **kwargs: Any) -> Iterator[ActivitySeries]:
        """Job history for one object - a client machine/host, a database,
        a cluster, anything RSC assigns an id to.

        Built on `{"objectFid": [object_id]}`: this schema consistently
        calls object ids `fid` wherever an object reference shows up (see
        e.g. `physicalPath { fid name }` in `mssql.py`, or `id: fid` in
        `sla_domain.py`), so `objectFid` is `ActivitySeriesFilter`'s very
        likely equivalent field - but unlike `lastActivityType`/
        `startTimeGt` above, it isn't independently confirmed by the
        schema's own docs. If job history for an object comes back empty
        when you expect results, pass `filter={"...": ...}` to `.all()`
        directly with whatever field name the RSC schema actually specifies
        instead.
        """
        yield from self.all(filter={"objectFid": [object_id]}, **kwargs)

    def status(self, taskchain_id: str) -> Taskchain | None:
        """The live status of one job by its taskchain id (e.g. one
        returned by a mutation that kicks off a backup/restore), rather
        than historical job data."""
        data = self._client.execute(
            _TASKCHAIN_STATUS_DOCUMENT,
            {"filter": taskchain_id},
            operation_name="TaskchainStatus",
        )
        taskchain = data["getKorgTaskchainStatus"]["taskchain"]
        return Taskchain(**taskchain) if taskchain is not None else None
