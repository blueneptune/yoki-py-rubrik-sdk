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
from datetime import datetime
from typing import TYPE_CHECKING, Any

from loguru import logger
from pydantic import BaseModel, ValidationError, field_validator

from .common import CAMEL_CONFIG, ClusterReference
from .pagination import Page
from .query import ConnectionQuery

if TYPE_CHECKING:
    from .client import RubrikClient


class ActivityEvent(BaseModel):
    model_config = CAMEL_CONFIG

    id: str
    message: str | None = None
    severity: str | None = None
    time: str | None = None


class ActivityConnection(BaseModel):
    model_config = CAMEL_CONFIG

    nodes: list[ActivityEvent] = []


# Statuses RSC gives a series that is still going. Compared without case
# or underscores: the schema's enum says RUNNING, the string field on a
# series has been seen as "Running".
ACTIVE_STATUSES = frozenset({"running", "queued", "canceling", "active", "inprogress"})


def _plain(value: str | None) -> str:
    return (value or "").replace("_", "").replace(" ", "").lower()


class ActivitySeries(BaseModel):
    """One job: what RSC calls an activity series - a backup, recovery,
    replication, archival or other run, with its latest status and the
    events (`activity_connection`) that make up its timeline."""

    model_config = CAMEL_CONFIG

    id: str
    fid: str | None = None
    activity_series_id: str | None = None
    start_time: datetime | None = None
    last_updated: datetime | None = None
    last_activity_type: str | None = None
    last_activity_status: str | None = None
    location: str | None = None
    object_name: str | None = None
    object_id: str | None = None
    object_type: str | None = None
    severity: str | None = None
    # The latest event's message, and why a failed series failed, as RSC
    # words them.
    last_activity_message: str | None = None
    failure_reason: str | None = None
    cause_error_code: str | None = None
    cause_error_message: str | None = None
    cause_error_reason: str | None = None
    cause_error_remedy: str | None = None
    progress: str | None = None
    sla_domain_name: str | None = None
    attempt_number: int | None = None
    is_on_demand: bool | None = None
    # Bytes, and bytes per second.
    data_transferred: int | None = None
    logical_size: int | None = None
    effective_throughput: int | None = None
    cluster: ClusterReference | None = None
    activity_connection: ActivityConnection | None = None

    @field_validator(
        "sla_domain_name",
        "last_activity_message",
        "failure_reason",
        "cause_error_code",
        "cause_error_message",
        "cause_error_reason",
        "cause_error_remedy",
        mode="after",
    )
    @classmethod
    def _blank_is_none(cls, value: str | None) -> str | None:
        # RSC sends "" for a series with no SLA domain, or no failure.
        return value or None

    @property
    def percent_complete(self) -> float | None:
        """`progress` ("14%") as a number, or None when RSC gives none."""
        try:
            return float((self.progress or "").rstrip("%"))
        except ValueError:
            return None

    @property
    def is_active(self) -> bool:
        """Still running or waiting to run."""
        return _plain(self.last_activity_status) in ACTIVE_STATUSES

    @property
    def key(self) -> str:
        """What identifies this series across collections. `fid` is RSC's
        global id; a series without one falls back to its cluster and its
        id on that cluster."""
        if self.fid:
            return self.fid
        cluster = self.cluster.id if self.cluster else ""
        return f"{cluster}:{self.activity_series_id or self.id}"


class Taskchain(BaseModel):
    """The live status of one currently (or recently) running job, queried
    by its taskchain id - distinct from `ActivitySeries`, which is history
    rather than a point-in-time status check."""

    model_config = CAMEL_CONFIG

    id: str
    state: str | None = None
    taskchain_uuid: str | None = None
    progressed_at: str | None = None


# What both activity series queries ask for about each series. The
# failure, size and attempt fields were confirmed in RSC's schema by
# rubrik-sample (2026-10-28). `cluster { ... }` stays last: rubrik-probe
# reads the field names before it to check them against the schema.
_SERIES_FIELDS = """\
        id
        fid
        activitySeriesId
        startTime
        lastUpdated
        lastActivityType
        lastActivityStatus
        lastActivityMessage
        failureReason
        causeErrorCode
        causeErrorMessage
        causeErrorReason
        causeErrorRemedy
        location
        objectName
        objectId
        objectType
        severity
        progress
        slaDomainName
        attemptNumber
        isOnDemand
        dataTransferred
        logicalSize
        effectiveThroughput
        cluster {
          id
          name
        }
"""

# Real query name/variables/field selection from the schema's
# `ActivitySeriesConnection.all.query.graphql`, used as-is.
_ACTIVITY_SERIES_DOCUMENT = (
    """
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
"""
    + _SERIES_FIELDS
    + """        activityConnection {
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
)

# The same query without the event timeline - what collection uses. Each
# series can carry many events; a page of 200 with all of them would be
# far heavier than the 200 rows a collector wants.
_ACTIVITY_SERIES_PAGE_DOCUMENT = (
    """
query ActivitySeriesPage(
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
"""
    + _SERIES_FIELDS
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

# Names in RSC's schema that collection depends on and the PowerShell
# SDK's examples do not confirm. Kept here, together, so a correction
# from rubrik-probe is a one-line change.
FILTER_UPDATED_AFTER = "lastUpdatedTimeGt"
FILTER_STARTED_AFTER = "startTimeGt"
SORT_LAST_UPDATED = "LAST_UPDATED"
SORT_START_TIME = "START_TIME"


def as_graphql_time(value: datetime) -> str:
    """A time the way RSC's DateTime scalar takes it: ISO 8601 in UTC."""
    if value.tzinfo is None:
        raise ValueError("Filter times must be timezone-aware.")
    return value.isoformat().replace("+00:00", "Z")


def parse_series(raw: dict[str, Any]) -> ActivitySeries | None:
    """An ActivitySeries, or None if this record cannot be read. One odd
    record among thousands should cost that record, loudly, not the run."""
    try:
        return ActivitySeries.model_validate(raw)
    except ValidationError as exc:
        problems = "; ".join(
            f"{'.'.join(str(part) for part in error['loc'])}: {error['msg']}"
            for error in exc.errors()
        )
        logger.error("Skipping activity series {}: could not read it - {}", raw.get("id"), problems)
        return None


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
    """Job history: `rsc.jobs` on a RubrikClient.

    `iter_pages` and `sample` are what a collector uses; `list`, `all`
    and `for_object` take RSC's filter as-is and include each series'
    events."""

    def __init__(self, client: RubrikClient) -> None:
        self._client = client

    def _page(
        self,
        filters: dict[str, Any] | None,
        sort_by: str,
        ascending: bool,
        first: int,
        after: str | None,
    ) -> tuple[list[ActivitySeries], str | None]:
        """One page: (the series that could be read, the cursor for the
        next page or None if this was the last)."""
        variables: dict[str, Any] = {
            "first": first,
            "sortBy": sort_by,
            "sortOrder": "ASC" if ascending else "DESC",
        }
        if filters:
            variables["filters"] = filters
        if after:
            variables["after"] = after
        data = self._client.execute(
            _ACTIVITY_SERIES_PAGE_DOCUMENT, variables, operation_name="ActivitySeriesPage"
        )
        connection = data["activitySeriesConnection"]
        series = [s for edge in connection["edges"] if (s := parse_series(edge["node"]))]
        info = connection.get("pageInfo") or {}
        cursor = info.get("endCursor") if info.get("hasNextPage") else None
        return series, cursor

    def iter_pages(
        self,
        *,
        updated_after: datetime | None = None,
        started_after: datetime | None = None,
        filters: dict[str, Any] | None = None,
        page_size: int | None = None,
    ) -> Iterator[list[ActivitySeries]]:
        """Every series matching, a page at a time, oldest change first.

        `updated_after` is what a delta collection wants: everything that
        changed since the last one, finished or not. `started_after` is a
        first collection's look-back. `filters` adds any other
        ActivitySeriesFilter fields (lastActivityType, clusterId, ...).

        Ordered by last update, ascending, so a series that changes while
        this runs moves to the end instead of being skipped.
        """
        merged = dict(filters or {})
        if updated_after is not None:
            merged[FILTER_UPDATED_AFTER] = as_graphql_time(updated_after)
        if started_after is not None:
            merged[FILTER_STARTED_AFTER] = as_graphql_time(started_after)
        size = page_size or self._client.page_size
        after: str | None = None
        while True:
            series, after = self._page(merged, SORT_LAST_UPDATED, True, size, after)
            if series:
                yield series
            if after is None:
                return

    def sample(
        self, limit: int = 5, *, updated_after: datetime | None = None
    ) -> list[ActivitySeries]:
        """The most recently changed few - one request, for checking the
        listing works."""
        filters = {FILTER_UPDATED_AFTER: as_graphql_time(updated_after)} if updated_after else None
        series, _ = self._page(filters, SORT_LAST_UPDATED, False, limit, None)
        return series

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
