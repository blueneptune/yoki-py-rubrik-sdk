"""rubrik-sdk: a small, read-only-by-default SDK for Rubrik Security
Cloud's GraphQL API, built on sdk-primer-core. See client.py."""

from __future__ import annotations

from .activity import ActivitySeries, ActivitySeriesManager, ActivitySeriesQuery, Taskchain
from .auth import ServiceAccount
from .client import RubrikClient
from .cluster import Cluster, ClusterManager, ClusterQuery
from .errors import ChangesNotAllowed, GraphQLError, RubrikError
from .logging import configure_logging
from .mssql import (
    MssqlDatabase,
    MssqlDatabaseDetails,
    MssqlDatabaseManager,
    MssqlSnapshot,
    MssqlSnapshotQuery,
)
from .pagination import Collection, Page, PageInfo
from .query import ConnectionQuery
from .sla_domain import SlaAssignResult, SlaDomain, SlaDomainManager, SlaDomainQuery

__all__ = [
    "ActivitySeries",
    "ActivitySeriesManager",
    "ActivitySeriesQuery",
    "ChangesNotAllowed",
    "Cluster",
    "ClusterManager",
    "ClusterQuery",
    "Collection",
    "ConnectionQuery",
    "GraphQLError",
    "MssqlDatabase",
    "MssqlDatabaseDetails",
    "MssqlDatabaseManager",
    "MssqlSnapshot",
    "MssqlSnapshotQuery",
    "Page",
    "PageInfo",
    "RubrikClient",
    "RubrikError",
    "ServiceAccount",
    "SlaAssignResult",
    "SlaDomain",
    "SlaDomainManager",
    "SlaDomainQuery",
    "Taskchain",
    "configure_logging",
]
