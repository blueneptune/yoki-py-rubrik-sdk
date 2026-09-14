# rubrik-rsc-sdk-for-python

A facade-of-facades Python SDK wrapping Rubrik Security Cloud's (RSC) GraphQL API, styled after
[sdk-primer](https://github.com/blueneptune/sdk-primer)'s REST-flavoured facade pattern.

## Quickstart

1. Install dependencies (including dev tools):

   ```
   uv sync
   ```

2. Connect using an RSC service account (downloaded as JSON from RSC's UI):

   ```python
   from rubrik_rsc import ServiceAccount, connect_with_service_account

   service_account = ServiceAccount.from_json_file("service-account.json")
   rsc = connect_with_service_account(service_account)

   for cluster in rsc.clusters.all():
       print(cluster.name, cluster.status)
   ```

   Already have a bearer token and don't want the SDK managing the exchange? Use `connect()`
   directly:

   ```python
   from rubrik_rsc import connect

   rsc = connect("https://my-instance.my.rubrik.com", token="...")
   ```

## Connecting, step by step

Everything above in one call, broken into what `connect_with_service_account()` actually does -
useful if you want to manage the token yourself (cache it, refresh it on a schedule, ...) instead
of exchanging it fresh on every run.

**1. Load the service account file** (downloaded from RSC's UI):

```python
from rubrik_rsc import ServiceAccount

service_account = ServiceAccount.from_json_file("service-account.json")
print(service_account.name)
print(service_account.base_url)  # derived from access_token_uri
```
```
my-terraform-service-account
https://my-instance.my.rubrik.com
```

**2. Exchange it for a bearer token:**

```python
from rubrik_rsc import fetch_access_token

token = fetch_access_token(service_account)
print(token)
```
```
eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJzdmMtYWNjdCJ9.dGhpc19pc19hbl9leGFtcGxl
```

**3. Build the facade from that token:**

```python
from rubrik_rsc import connect

rsc = connect(service_account.base_url, token)
```

Steps 2-3 together are exactly what `connect_with_service_account(service_account)` (Quickstart,
above) does in one call.

**4. Handle errors.** `RscClient.execute()` (which every domain method eventually calls) raises
two different exceptions depending on where things failed, plus `fetch_access_token()`/
`ServiceAccount.base_url` raise a third for the auth step - see `errors.py`:

```python
import httpx
from rubrik_rsc import GraphQLError, RscAuthError

try:
    rsc.clusters.list()
except GraphQLError as error:
    # The HTTP call succeeded, but RSC's response body carried a top-level
    # `errors` array - a bad variable, a permission problem, ...
    print("GraphQL error:", error.errors)
except httpx.HTTPStatusError as error:
    # The HTTP call itself failed - bad/expired token, RSC unreachable, ...
    print("HTTP error:", error.response.status_code)
```
```
GraphQL error: [{'message': "permission denied for field 'clusterConnection'"}]
```

```python
try:
    fetch_access_token(service_account)
except RscAuthError as error:
    print(error)
```
```
Token endpoint response did not include an 'access_token' field.
```

**5. Clean up the connection when you're done** (optional - `RscClient` holds an `httpx.Client`
with pooled connections):

```python
rsc.client.close()

# or, scoping it explicitly:
from rubrik_rsc import RscClient

with RscClient(service_account.base_url, token) as client:
    ...  # client.close() is called automatically on exit
```

## Logging

This SDK logs through [loguru](https://github.com/Delgan/loguru) - `RscClient.execute()`
(every domain call goes through it) and `fetch_access_token()` (the token exchange) both emit
debug/warning-level log lines - but nothing in this package ever calls `logger.add(...)` itself.
That's deliberate, not an oversight: loguru's `logger` is a process-wide singleton, so a library
adding a sink on its own would silently rewrite the *whole application's* logging setup, and would
add another duplicate sink every time you construct another `RscClient` - which this SDK
explicitly supports doing (see `test_two_rsc_instances_stay_isolated_to_their_own_client` in
`tests/test_facade.py`). **Deciding where log records end up - the sink - is always the calling
application's job, not this SDK's.** What this SDK owns is only the plumbing: emitting log
records through whatever logger you gave it.

That plumbing is dependency-injected end to end, not just at `RscClient`: `connect()`,
`connect_with_service_account()`, and `fetch_access_token()` all accept the same `logger`
parameter and thread it straight through, so you don't have to bypass the facade helpers and
hand-wire `RscClient`/`RSC()` yourself just to plug in a custom logger.

```python
from loguru import logger

my_logger = logger.bind(component="rubrik-backup-report")
rsc = connect_with_service_account(service_account, logger=my_logger)
# every log line this connection produces - the token exchange included - carries
# component="rubrik-backup-report", so your own sink's filter/format can pick it out
```

If you already configure loguru yourself (added your own sink(s) at application startup),
nothing extra is needed beyond that - by default every entry point above uses loguru's global
`logger`, so log calls already show up in whatever sinks you've configured, the same
dependency-injection pattern used for the `httpx.Client`/`transport` underneath `RscClient`.

If you don't have loguru set up yet and just want to see this SDK's log lines, `configure_logging()`
is a small, explicit, opt-in wrapper around one `logger.add()` call - it's not invoked by any other
code in this package:

```python
from rubrik_rsc import configure_logging

configure_logging()  # adds a stderr sink, level INFO, scoped to this package's own log lines

rsc = connect_with_service_account(service_account)
rsc.clusters.list()
```
```
2024-06-01 12:00:00.000 | DEBUG    | rubrik_rsc.client:__init__:70 - Initialized RscClient for https://my-instance.my.rubrik.com
2024-06-01 12:00:00.010 | DEBUG    | rubrik_rsc.client:execute:113 - POST https://my-instance.my.rubrik.com/api/graphql operationName=Cluster
```

(loguru's default format includes a timestamp/level/location prefix like the one shown - the
messages themselves are the plain text passed to `.debug()`/`.warning()` in `client.py`.)

Already use loguru elsewhere and want one sink to show everything, not just this SDK's lines? Pass
`only_this_package=False`, or skip `configure_logging()` and call `loguru.logger.add()` yourself -
either way, log calls made through `fetch_access_token()`/`RscClient`/domain managers show up in
it automatically, since they all go through the same global `logger` by default (pass `logger=`
to `connect()`/`connect_with_service_account()` if you want a particular connection to use a
different one instead).

## Usage

See `src/rubrik_rsc/facade.py` for how the pieces (`RscClient`, `ConnectionQuery`,
domain managers, `RSC`) fit together, and `src/rubrik_rsc/cluster.py` for the template to follow
when adding a new domain.

- **`RscClient`** (`client.py`) is the transport layer: one GraphQL endpoint, one bearer token,
  `execute(document, variables)` in, parsed `data` out. It knows nothing about clusters or SLA
  domains.
- **`ConnectionQuery`** (`query.py`) is the generic engine for RSC's Relay-style paginated
  queries (`edges { node { ... } } pageInfo { ... }`): give it a document, the response path to
  the connection, and a pydantic model for the node, and it gets single-page fetching and
  transparent multi-page auto-pagination (`fetch_all`) for free.
- **Domain modules** (`cluster.py`, `sla_domain.py`, `activity.py`, `mssql.py`) each pair a
  pydantic model with the real query/mutation text from RSC's schema (sourced from
  [rubrik-powershell-sdk's docs/graphql](https://github.com/rubrikinc/rubrik-powershell-sdk/tree/main/docs/graphql)),
  plus a manager class (`ClusterManager`, `SlaDomainManager`, `ActivitySeriesManager`,
  `MssqlDatabaseManager`) exposing whatever shape of methods that domain actually needs - GraphQL
  operations don't share one uniform CRUD shape the way REST resources do, so unlike a single
  generic `ResourceManager`, each domain gets its own manager.
- **`RSC`** (`facade.py`) is the facade of facades: one object, built from one `RscClient`, with
  every domain manager already wired up as an attribute (`.clusters`, `.sla_domains`, `.jobs`,
  `.mssql_databases`).

### Every result is a pydantic model

Whatever a domain manager method hands back - one object, a page of them, or a whole flat list -
it's a pydantic `BaseModel`, never a plain dict, dataclass, or bare list of dicts. That means
`.model_dump()`/`.model_dump_json()` work the same way everywhere, and every field is validated
and typed going in.

Three return shapes cover every method in the SDK (see `pagination.py`):

| Shape | Returned by | What it looks like |
| --- | --- | --- |
| A single model | `.find_by_name()`, `.get()`, `.assign_to_objects()`, `.status()` | `Cluster`, `SlaAssignResult`, `MssqlDatabaseDetails`, `Taskchain \| None`, ... |
| `Page[M]` | `.list()` on a paginated domain | `Page(items=[...], page_info=PageInfo(...))` - one page plus Relay pagination metadata |
| `Collection[M]` | `.list()`/`.for_host()`/`.unprotected()` on the one *unpaginated* domain (`mssql_databases`) | `Collection(items=[...])` - `Page` without `page_info`, since there's nothing to paginate |
| A generator of models | every `.all()`/`.all_snapshots()` | not itself a `BaseModel` (materializing a possibly-huge auto-paginated result into one object would defeat the point), but every item it yields is one |

```python
page = rsc.clusters.list(first=2)
page.model_dump_json(indent=2)  # -> the JSON shown in the Clusters example below
```

## Examples

Each section below shows the call, then the shape of what comes back - either printed field
access, or a `.model_dump_json(indent=2)` dump showing the full pydantic object. Field values are
illustrative (a real RSC instance's data, formatted the way this SDK's models parse it), not
output actually captured from a live cluster.

### Clusters

```python
page = rsc.clusters.list(first=1)
print(page.items[0].name, page.items[0].status, page.items[0].version)
```
```
cluster-one Connected 9.1.0
```

`page` itself is a pydantic `Page[Cluster]`:

```python
print(page.model_dump_json(indent=2))
```
```json
{
  "items": [
    {
      "id": "c1",
      "name": "cluster-one",
      "version": "9.1.0",
      "status": "Connected",
      "sub_status": null,
      "pause_status": null,
      "type": "CDM",
      "product_type": "CDM",
      "timezone": "UTC",
      "registration_time": "2024-01-01T00:00:00Z",
      "last_connection_time": "2024-06-01T00:00:00Z",
      "is_healthy": true,
      "snapshot_count": 1420,
      "encryption_enabled": true,
      "cloud_info": null,
      "cluster_node_connection": {
        "count": 4,
        "nodes": [
          {"id": "c1-node-1", "ip_address": "10.0.0.1", "status": "OK", "cpu_cores": 16, "ram": 137438953472}
        ]
      },
      "geo_location": {"address": "Palo Alto, CA", "latitude": 37.44, "longitude": -122.14},
      "metric": {
        "available_capacity": 5000.0,
        "used_capacity": 1200.0,
        "total_capacity": 6200.0,
        "snapshot_capacity": 900.0,
        "live_mount_capacity": 0.0,
        "miscellaneous_capacity": 300.0,
        "ingested_snapshot_storage": 800.0,
        "physical_snapshot_storage": 700.0,
        "ingested_archival_storage": 100.0,
        "physical_archival_storage": 90.0,
        "immutability_overhead": 10.0,
        "last_update_time": "2024-06-01T00:00:00Z"
      }
    }
  ],
  "page_info": {"start_cursor": null, "end_cursor": "c1", "has_next_page": true, "has_previous_page": false}
}
```

Auto-paginate across every cluster with `.all()` (a generator - each yielded item is still a
`Cluster`):

```python
for cluster in rsc.clusters.all():
    print(cluster.name, cluster.status)
```
```
cluster-one Connected
cluster-two Connected
cluster-three Degraded
```

Look up one cluster by name (returns `None` rather than raising if there's no match):

```python
cluster = rsc.clusters.find_by_name("cluster-one")
print(cluster.status if cluster is not None else "not found")
```
```
Connected
```

### SLA domains

A single page:

```python
page = rsc.sla_domains.list(first=2)
for sla in page.items:
    print(sla.name, sla.protected_object_count)
```
```
Bronze 120
Gold 812
```

Every SLA domain, auto-paginated:

```python
for sla in rsc.sla_domains.all():
    print(sla.name)
```
```
Bronze
Gold
Platinum
```

Look up one by name:

```python
gold = rsc.sla_domains.find_by_name("Gold")
print(gold.model_dump_json(indent=2))
```
```json
{
  "id": "s2",
  "name": "Gold",
  "description": "Global gold policy",
  "protected_object_count": 812,
  "base_frequency": {"duration": 1, "unit": "DAYS"},
  "local_retention_limit": {"duration": 90, "unit": "DAYS"},
  "object_types": ["VirtualMachine", "MssqlDatabase"]
}
```

Assigning it to a set of objects returns a `SlaAssignResult` (also pydantic):

```python
result = rsc.sla_domains.assign_to_objects(object_ids=["obj-1", "obj-2"], sla_id=gold.id)
print(result.model_dump_json())
```
```json
{"success": true}
```

### Jobs (`rsc.jobs`)

A single page of job history, across every object:

```python
page = rsc.jobs.list(first=2)
for job in page.items:
    print(job.object_name, job.last_activity_type, job.last_activity_status)
```
```
AdventureWorks Backup Success
cluster-one Replication Success
```

Every job, auto-paginated:

```python
for job in rsc.jobs.all():
    print(job.last_activity_type, job.last_activity_status)
```
```
Backup Success
Replication Success
Backup Failure
```

Job history for one object - a client machine, a database, a cluster:

```python
for job in rsc.jobs.for_object("db-1"):
    print(job.last_activity_type, job.last_activity_status, job.progress)
```
```
Backup Success 100
Backup Failure 45
```

```python
print(job.model_dump_json(indent=2))
```
```json
{
  "id": "job-2",
  "fid": "job-2",
  "activity_series_id": "job-2",
  "start_time": "2024-06-02T02:00:00Z",
  "last_updated": "2024-06-02T02:05:00Z",
  "last_activity_type": "Backup",
  "last_activity_status": "Failure",
  "location": "sql-prod-01",
  "object_name": "AdventureWorks",
  "object_id": "db-1",
  "object_type": "MssqlDatabase",
  "severity": "Critical",
  "progress": "45",
  "sla_domain_name": "Gold",
  "cluster": {"id": "c1", "name": "cluster-one"},
  "activity_connection": {
    "nodes": [
      {"id": "evt-1", "message": "Started", "severity": "Info", "time": "2024-06-02T02:00:00Z"},
      {"id": "evt-2", "message": "Database offline mid-backup", "severity": "Critical", "time": "2024-06-02T02:05:00Z"}
    ]
  }
}
```

Live status of a specific job by taskchain id, rather than history:

```python
taskchain = rsc.jobs.status("tc-1")
print(taskchain.state if taskchain else "not found")
```
```
RUNNING
```

### MSSQL databases (`rsc.mssql_databases`)

Every SQL Server database RSC has discovered, across every client machine (not paginated - see
[Every result is a pydantic model](#every-result-is-a-pydantic-model)):

```python
all_databases = rsc.mssql_databases.list()
for database in all_databases.items:
    print(database.host_name, database.name, database.is_protected)
```
```
sql-prod-01 AdventureWorks True
sql-prod-01 Scratch False
sql-prod-02 Northwind True
```

What does this client machine have, and is it backed up?

```python
databases = rsc.mssql_databases.for_host("sql-prod-01")
for database in databases.items:
    print(database.name, "protected" if database.is_protected else "NOT PROTECTED")
```
```
AdventureWorks protected
Scratch NOT PROTECTED
```

`for_host()` returns a `Collection[MssqlDatabase]` - `.list()` (every database, across every
client machine) and `.unprotected()` return the same shape:

```python
print(databases.model_dump_json(indent=2))
```
```json
{
  "items": [
    {
      "id": "db-1",
      "name": "AdventureWorks",
      "dag_id": null,
      "physical_path": [{"fid": "host-1", "name": "sql-prod-01", "object_type": null}],
      "logical_path": [{"fid": "inst-1", "name": "sql-prod-01\\MSSQLSERVER", "object_type": null}],
      "is_in_availability_group": false,
      "cdm_link": null,
      "cdm_id": "cdm-db-1",
      "cluster": {"id": "c1", "name": "cluster-one"},
      "effective_sla_domain": {"id": "sla-1", "name": "Gold"},
      "primary_cluster_location": {"name": "cluster-one"},
      "recovery_model": "FULL",
      "sla_assignment": "Direct",
      "configured_sla_domain": {"id": "sla-1", "name": "Gold"}
    },
    {
      "id": "db-2",
      "name": "Scratch",
      "dag_id": null,
      "physical_path": [{"fid": "host-1", "name": "sql-prod-01", "object_type": null}],
      "logical_path": [{"fid": "inst-1", "name": "sql-prod-01\\MSSQLSERVER", "object_type": null}],
      "is_in_availability_group": false,
      "cdm_link": null,
      "cdm_id": "cdm-db-2",
      "cluster": {"id": "c1", "name": "cluster-one"},
      "effective_sla_domain": null,
      "primary_cluster_location": {"name": "cluster-one"},
      "recovery_model": "SIMPLE",
      "sla_assignment": "Unassigned",
      "configured_sla_domain": null
    }
  ]
}
```

Every database RSC has ever discovered but that was never actually protected - across *all*
client machines:

```python
for database in rsc.mssql_databases.unprotected().items:
    print(database.host_name, database.name)
```
```
sql-prod-01 Scratch
sql-prod-02 TempReporting
```

Richer detail on one specific database:

```python
details = rsc.mssql_databases.get("db-1")
print(details.model_dump_json(indent=2))
```
```json
{
  "id": "db-1",
  "cdm_id": "cdm-db-1",
  "name": "AdventureWorks",
  "recovery_model": "FULL",
  "is_relic": false,
  "unprotectable_reasons": [],
  "is_log_shipping_secondary": false,
  "is_online": true,
  "copy_only": false,
  "is_in_availability_group": false,
  "effective_sla_domain": {"id": "sla-1", "name": "Gold"},
  "logical_path": [{"fid": null, "name": "sql-prod-01\\MSSQLSERVER", "object_type": "MssqlInstance"}],
  "physical_path": [{"fid": null, "name": "sql-prod-01", "object_type": "PhysicalHost"}],
  "cluster": {"id": "c1", "name": "cluster-one"},
  "cdm_snapshots": {"count": 42},
  "authorized_operations": ["Restore", "ExportSnapshot"],
  "log_backup_frequency_in_seconds": 900,
  "log_backup_retention_in_hours": 24,
  "has_log_config_from_sla": true
}
```

A single page of one database's backup history:

```python
page = rsc.mssql_databases.snapshots("db-1", first=2)
for snapshot in page.items:
    print(snapshot.date, "CORRUPTED" if snapshot.is_corrupted else "ok")
print("more pages?", page.page_info.has_next_page)
```
```
2024-06-01T00:00:00Z ok
2024-06-02T00:00:00Z ok
more pages? True
```

And that database's full backup history, auto-paginated - each snapshot is one entry:

```python
for snapshot in rsc.mssql_databases.all_snapshots("db-1"):
    print(
        snapshot.date,
        "on-demand" if snapshot.is_on_demand_snapshot else "scheduled",
        "CORRUPTED" if snapshot.is_corrupted else "ok",
    )
```
```
2024-06-01T00:00:00Z scheduled ok
2024-06-02T00:00:00Z scheduled ok
2024-06-02T14:00:00Z on-demand CORRUPTED
```

```python
print(snapshot.model_dump_json(indent=2))
```
```json
{
  "id": "snap-3",
  "date": "2024-06-02T14:00:00Z",
  "expiration_date": "2024-07-02T14:00:00Z",
  "expiry_hint": null,
  "workload_id": "db-1",
  "is_corrupted": true,
  "indexing_attempts": 3,
  "is_indexed": false,
  "is_unindexable": true,
  "is_on_demand_snapshot": true,
  "workload_type": "Mssql",
  "cluster_uuid": "c1",
  "cdm_id": "cdm-snap-3",
  "cdm_version": "9.1.0",
  "is_downloaded_snapshot": false,
  "is_expired": false,
  "sla_domain": {"id": "sla-1", "name": "Gold"}
}
```

### Adding a new domain

Four real domains (`clusters`, `sla_domains`, `jobs`, `mssql_databases`) are implemented as a
worked example - RSC's schema has ~100 curated operations across many more domains (AWS/Azure/GCP
native accounts, snapshots, Kubernetes, VMware, Sonar/malware scanning, ...). To add one:

1. Pull the real query/mutation text for that operation from
   [`docs/graphql/operations`](https://github.com/rubrikinc/rubrik-powershell-sdk/tree/main/docs/graphql/operations)
   in the rubrik-powershell-sdk repo (inline any fragments it references from sibling files so the
   document is self-contained).
2. Write a pydantic model matching the fields you selected (see `cluster.py`'s models for the
   camelCase-alias convention used throughout).
3. Subclass `ConnectionQuery` (for a paginated query) wiring the document/model together, or call
   `client.execute()` directly for a one-shot query/mutation or a flat/unpaginated list (wrapping a
   flat list in `Collection`, per `mssql.py`'s `MssqlDatabaseManager.list()`) - see
   `SlaDomainManager.assign_to_objects` for the one-shot-mutation case.
4. Write a manager class exposing whatever methods make sense, and register it on `RSC` in
   `facade.py`.

## Development

Install dependencies (including dev tools):

```
uv sync
```

Run tests with coverage:

```
uv run pytest
```

Lint and format:

```
uv run ruff check .
uv run ruff format .
```

Type check:

```
uv run mypy
```
