"""The facade of facades: `RSC` is a single entry point that hides the
wiring behind it, and each attribute hanging off it (`.clusters`,
`.sla_domains`, `.jobs`, `.mssql_databases`) is itself a small facade over
one domain's GraphQL operations.

Construct `RSC` once with an `RscClient` and everything you need is already
wired up - `rsc.clusters.all()`, `rsc.sla_domains.assign_to_objects(...)`,
and so on. Adding the next domain (see `cluster.py`'s docstring for the
template) means adding one manager class and one line here, the same way
`sdk-primer`'s `SDK` grows by adding another `ResourceManager`.

Usage:

    from rubrik_rsc import ServiceAccount, connect_with_service_account

    service_account = ServiceAccount.from_json_file("service-account.json")
    rsc = connect_with_service_account(service_account)

    for cluster in rsc.clusters.all():
        print(cluster.name, cluster.status)

    production_sla = rsc.sla_domains.find_by_name("Gold")
    if production_sla is not None:
        rsc.sla_domains.assign_to_objects(
            object_ids=[cluster.id for cluster in rsc.clusters.all()],
            sla_id=production_sla.id,
        )

    # Which databases does this client machine have, and are they backed up?
    # (.for_host() returns a `Collection` - a pydantic model wrapping
    # `.items`, not a plain list - see pagination.py.)
    for database in rsc.mssql_databases.for_host("sql-prod-01").items:
        print(database.name, "protected" if database.is_protected else "NOT PROTECTED")
        for snapshot in rsc.mssql_databases.all_snapshots(database.id):
            print("  backup", snapshot.date, "corrupted" if snapshot.is_corrupted else "ok")

    # Job history for one object (a host, a database, a cluster, ...):
    for job in rsc.jobs.for_object(database.id):
        print(job.last_activity_type, job.last_activity_status, job.progress)
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from loguru import logger as _default_logger

from .activity import ActivitySeriesManager
from .auth import ServiceAccount, fetch_access_token
from .client import RscClient
from .cluster import ClusterManager
from .mssql import MssqlDatabaseManager
from .sla_domain import SlaDomainManager

if TYPE_CHECKING:
    from loguru import Logger


class RSC:
    """The facade itself. One `RscClient` in, one object with every domain
    already wired up out."""

    def __init__(self, client: RscClient) -> None:
        self.client = client
        self.clusters = ClusterManager(client)
        self.sla_domains = SlaDomainManager(client)
        self.jobs = ActivitySeriesManager(client)
        self.mssql_databases = MssqlDatabaseManager(client)


def connect(
    base_url: str,
    token: str,
    *,
    timeout: float = 30.0,
    logger: Logger = _default_logger,
) -> RSC:
    """Build the facade from a base URL and an already-obtained bearer
    token. Use this when you're managing token acquisition/refresh yourself;
    use `connect_with_service_account()` to have the SDK do the exchange
    for you.

    `logger` is threaded straight through to `RscClient` - pass your own
    (e.g. one already wired to your application's sinks, or
    `logger.bind(instance=...)` to tag every line this connection produces)
    the same way you would construct `RscClient` directly. Defaults to
    loguru's global `logger`, which emits nowhere until something (your
    application, or this SDK's own `configure_logging()`) adds a sink - see
    the README's "Logging" section.
    """
    return RSC(RscClient(base_url, token, timeout=timeout, logger=logger))


def connect_with_service_account(
    service_account: ServiceAccount,
    *,
    timeout: float = 30.0,
    logger: Logger = _default_logger,
) -> RSC:
    """Exchange a service account's credentials for a bearer token, then
    build the facade - the one-call convenience path for the common case.
    `logger` is used for both the token exchange (`fetch_access_token()`)
    and the resulting facade's `RscClient` - see `connect()`."""
    token = fetch_access_token(service_account, timeout=timeout, logger=logger)
    return connect(service_account.base_url, token, timeout=timeout, logger=logger)
