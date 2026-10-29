# yoki-py-rubrik-sdk

Your Org's Keepsake Integrations - python - rubrik - SDK

A small SDK for **Rubrik Security Cloud** (RSC) - Rubrik's control
plane, which every Rubrik cluster reports to - built on
[sdk-primer-core](https://github.com/blueneptune/sdk-primer-core). It
is the Rubrik counterpart of `yoki-py-commvault-sdk`,
`yoki-py-veeam-sdk` and `yoki-py-netbackup-sdk`, laid out the same way:
one client object per account, a named group of calls for each kind of
thing, read-only unless told otherwise.

The repository is `yoki-py-rubrik-sdk`; the package it provides is
`rubrik-sdk`, imported as `rubrik_sdk`. It grew out of
`rubrik-rsc-sdk-for-python` (September 2026), whose queries and tests it
keeps.

> **Status: written from Rubrik's PowerShell SDK operation files and
> RSC's documentation. No part of it has been run against a real RSC
> account.** Every call is covered by a test that fakes RSC's answers,
> which proves the SDK does what those sources describe - not that RSC
> agrees. `rubrik-probe` (below) checks it the first time, and asks RSC's
> own schema about every name the SDK had to guess; `rubrik-sample` and
> `rubrik-mask` bring real answers back, safely, to fix it from.

```python
from datetime import UTC, datetime, timedelta
from rubrik_sdk import RubrikClient, ServiceAccount

account = ServiceAccount.from_json_file("blt-reader.json")
with RubrikClient(account) as rsc:
    since = datetime.now(UTC) - timedelta(hours=24)
    for page in rsc.jobs.iter_pages(updated_after=since):
        for job in page:
            print(job.object_name, job.last_activity_type, job.last_activity_status)
```

## Rubrik's words, next to Commvault's

| Rubrik (RSC) | What it is | Nearest Commvault idea |
|---|---|---|
| RSC account | `https://<account>.my.rubrik.com` - what this connects to | CommServe (or Commvault Cloud) |
| Cluster (CDM) | A Rubrik appliance cluster that does the backups | MediaAgents + the CommServe's view of them |
| Activity series | One run - a backup, recovery, replication, archival... - with its event timeline | Job |
| Activity event | One line of that timeline | Job event |
| Object (workload) | A VM, database, host, share... | Client / subclient / instance |
| SLA domain | What protects an object, how often, for how long | Plan / storage policy + schedule |
| Service account | An API login: client id + secret | API user with an access token |

blt calls an activity series a **job**, so this SDK does too: `rsc.jobs`.

## The calls

| Group | Call | GraphQL | Run against RSC? |
|---|---|---|---|
| `rsc.jobs` | `iter_pages(updated_after=, started_after=, filters=)` | `activitySeriesConnection`, no events | written, not run |
| | `sample(limit)` | same, newest first | written, not run |
| | `list` / `all` / `for_object(fid)` | `activitySeriesConnection`, with events | written, not run |
| | `status(taskchain_id)` | `getKorgTaskchainStatus` | written, not run |
| `rsc.clusters` | `list` / `all` / `find_by_name` | `clusterConnection` | written, not run |
| `rsc.sla_domains` | `list` / `all` / `find_by_name` | `slaDomains` | written, not run |
| | `assign_to_objects` - **a change** | `assignSlasForSnappableHierarchies` | written, not run |
| `rsc.mssql_databases` | `list` / `for_host` / `unprotected` / `get` / `snapshots` | `mssqlDatabases`, `mssqlDatabase`, `snapshotOfASnappableConnection` | written, not run |

Anything else: `rsc.execute(document, variables, operation_name=...)`
runs any query; `rsc.change(...)` any mutation, on a client built with
`allow_changes=True`.

## Signing in

In RSC: **Settings > Users > Service Accounts > Create**. Give it a
read-only role (blt only reads), then download the JSON file it offers
- once; RSC does not show the secret again. That file is all the SDK
needs:

```python
account = ServiceAccount.from_json_file("blt-reader.json")
rsc = RubrikClient(account)
```

The SDK exchanges the id and secret for a bearer token on the first
call, fetches a new one if RSC refuses the old one, and ends the session
on `close()` (RSC limits how many sessions one service account can
have). The secret is a `SecretStr`: printing or logging the account
does not show it. There is no refresh token to store or renew.

`RubrikClient(base_url=..., token=...)` takes a token obtained some
other way instead.

## Options

| Argument | Default | |
|---|---|---|
| `page_size` | 200 | series per GraphQL page |
| `timeout` | 120 s | per request |
| `verify_tls` / `ca_bundle` | on / the system's | for a proxy that re-signs TLS |
| `allow_changes` | `False` | mutations refused unless `True` |
| `logger` | loguru's | pass `logger.bind(...)` to tag this client's lines |

Queries are retried on a timeout or a 429/502/503/504; mutations are
sent once.

## Running it on its own

Three commands work against a real RSC account without blt, from a
checkout of this repository:

| Command | What it does | Writes |
|---|---|---|
| `uv run rubrik-probe` | checks every name the SDK relies on against RSC's own schema, reads a sample, walks the last 24 hours | nothing |
| `uv run rubrik-sample` | saves RSC's raw answers to the queries blt uses (and the schema types behind them) | `samples/raw/<time>/` - real names, git-ignored |
| `uv run rubrik-mask` | masks the newest raw capture with your salt; refuses if anything would leak | `samples/masked/<time>/` - safe to commit or share |

Set-up, once:

```
uv sync
cp .env.example .env
python -c "import secrets; print(secrets.token_urlsafe(32))"   # your salt
# in .env: RUBRIK_SERVICE_ACCOUNT=<path to the JSON file>, RUBRIK_MASK_SALT=<that salt>
```

Then:

```
uv run rubrik-probe          # every line "ok"? its output is safe to paste as it is
uv run rubrik-sample         # --limit 100 --hours 48 for more
uv run rubrik-mask           # or: rubrik-mask samples/raw/<time> --out samples/masked/<name>
```

**The salt.** Masking replaces each name with an HMAC of it under your
salt: `sql-prod-01` becomes `objectName-8c6e592c` in every file and
every capture, so which job ran on which object on which cluster still
shows - but without the salt nobody can check a guess ("is it
sql-prod-01?") by masking it themselves. Keep it secret, and keep it the
same between captures. It lives only in `.env`.

**What is kept.** Statuses, types, severities and other Rubrik
vocabulary (`KEEP_FIELDS` in `tools/mask.py`), timestamps, numbers,
booleans, and RSC's schema descriptions. Every other string is masked,
including fields nobody listed. UUIDs, IPv4 and e-mail addresses keep
their shape. Before writing, the masker checks that no masked value also
appears in a kept field; if one does, it writes nothing. A map back to
the real names is written beside the raw capture, never the masked one.

Read one masked file before committing it - see `samples/README.md`.

## What is not known

Until `rubrik-probe` has run against a real account:

- The filter `lastUpdatedTimeGt` and the sort `LAST_UPDATED` -
  collection depends on both; the PowerShell SDK's examples show
  `startTimeGt` only. They are constants in `activity.py`, so a
  correction is one line.
- What `lastActivityStatus` actually says - `Running` or `RUNNING`, and
  which values mean "still going". `is_active` compares loosely for that
  reason.
- Whether `fid` is always set; `key` falls back to cluster + series id.
- Page size limits and rate limits on `activitySeriesConnection`.

## Using it from another project

```toml
[project]
dependencies = ["rubrik-sdk"]

[tool.uv.sources]
rubrik-sdk = { git = "https://github.com/blueneptune/yoki-py-rubrik-sdk.git", tag = "v0.2.0" }
```

## Development and releases

See [docs/development.md](docs/development.md): how it is built, adding
a query, the checks, and how changes are merged and released, as for blt
and the other yoki SDKs.

```
uv sync
uv run pytest
uv run ruff check . && uv run ruff format --check . && uv run mypy src
```

## Sources

- Rubrik's PowerShell SDK, whose `docs/graphql/operations/*.graphql`
  are real queries RSC accepts:
  https://github.com/rubrikinc/rubrik-powershell-sdk
- RSC's GraphQL reference, in the RSC UI under the API playground.
