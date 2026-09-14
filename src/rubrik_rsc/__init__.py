"""A facade-of-facades Python SDK for Rubrik Security Cloud's (RSC) GraphQL
API, styled after https://github.com/blueneptune/sdk-primer.

See `facade.py` for how the pieces (`RscClient`, `ConnectionQuery`,
`ClusterManager`/`SlaDomainManager`, `RSC`) fit together, and `cluster.py`
for the template to follow when adding a new domain.
"""

from __future__ import annotations

from .activity import ActivitySeries, ActivitySeriesManager, ActivitySeriesQuery, Taskchain
from .auth import ServiceAccount, fetch_access_token
from .client import RscClient
from .cluster import Cluster, ClusterManager, ClusterQuery
from .errors import GraphQLError, RscAuthError
from .facade import RSC, connect, connect_with_service_account
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
    "RSC",
    "ActivitySeries",
    "ActivitySeriesManager",
    "ActivitySeriesQuery",
    "Collection",
    "ClusterManager",
    "ClusterQuery",
    "Cluster",
    "ConnectionQuery",
    "GraphQLError",
    "MssqlDatabase",
    "MssqlDatabaseDetails",
    "MssqlDatabaseManager",
    "MssqlSnapshot",
    "MssqlSnapshotQuery",
    "Page",
    "PageInfo",
    "RscAuthError",
    "RscClient",
    "ServiceAccount",
    "SlaAssignResult",
    "SlaDomain",
    "SlaDomainManager",
    "SlaDomainQuery",
    "Taskchain",
    "configure_logging",
    "connect",
    "connect_with_service_account",
    "fetch_access_token",
]
