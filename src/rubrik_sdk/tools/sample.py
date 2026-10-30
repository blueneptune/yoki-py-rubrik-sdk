"""rubrik-sample: save RSC's raw answers to the queries blt relies on, so
they can be masked (rubrik-mask) and looked at away from the account.

    uv run rubrik-sample                    # into samples/raw/<UTC time>/
    uv run rubrik-sample --limit 100 --hours 48

Reads only. Each query is one file - the operation, its variables, when
it was asked and RSC's `data` - so a masked copy can stand in for RSC in
a test. A query RSC refuses is recorded in errors.json and the rest
still run.

The raw files hold the account's real names. They go under samples/raw,
which git ignores; mask them before they go anywhere else.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sdk_primer import SDKError

from ..activity import (
    _ACTIVITY_SERIES_DOCUMENT,
    _ACTIVITY_SERIES_PAGE_DOCUMENT,
    FILTER_UPDATED_AFTER,
    SORT_LAST_UPDATED,
    as_graphql_time,
)
from ..auth import ServiceAccount
from ..client import RubrikClient
from ..cluster import ClusterQuery
from ..inventory import _INVENTORY_PAGE_DOCUMENT
from ..sla_domain import SlaDomainQuery
from .config import load_config

_TYPE_QUERY = """
query SampleType($name: String!) {
  __type(name: $name) {
    name
    kind
    fields { name type { name kind ofType { name kind } } }
    inputFields { name type { name kind ofType { name kind } } }
    enumValues { name }
  }
}
"""
SCHEMA_TYPES = (
    "ActivitySeries",
    "ActivitySeriesFilter",
    "ActivitySeriesSortField",
    "ActivityStatusEnum",
    "ActivityTypeEnum",
    "ActivityObjectTypeEnum",
    "Snappable",
    "SnappableFilterInput",
    "ProtectionStatusEnum",
    "ComplianceStatusEnum",
    "ObjectState",
)

Capture = tuple[str, str, str, dict[str, Any]]  # file name, operation, document, variables


def captures(limit: int, hours: float, now: datetime) -> list[Capture]:
    since = as_graphql_time(now - timedelta(hours=hours))
    newest = {"first": limit, "sortBy": SORT_LAST_UPDATED, "sortOrder": "DESC"}
    return [
        *((f"schema-{name}", "SampleType", _TYPE_QUERY, {"name": name}) for name in SCHEMA_TYPES),
        ("jobs-newest", "ActivitySeriesPage", _ACTIVITY_SERIES_PAGE_DOCUMENT, newest),
        (
            "jobs-changed",
            "ActivitySeriesPage",
            _ACTIVITY_SERIES_PAGE_DOCUMENT,
            {
                "first": limit,
                "sortBy": SORT_LAST_UPDATED,
                "sortOrder": "ASC",
                "filters": {FILTER_UPDATED_AFTER: since},
            },
        ),
        # With each job's event timeline: where failure reasons will come from.
        (
            "jobs-with-events",
            "ActivitySeriesConnection",
            _ACTIVITY_SERIES_DOCUMENT,
            {"first": min(limit, 10), "sortBy": SORT_LAST_UPDATED, "sortOrder": "DESC"},
        ),
        ("inventory", "InventoryPage", _INVENTORY_PAGE_DOCUMENT, {"first": limit}),
        ("clusters", ClusterQuery.operation_name, ClusterQuery.document, {"first": limit}),
        ("sla-domains", SlaDomainQuery.operation_name, SlaDomainQuery.document, {"first": limit}),
    ]


def run_captures(
    execute: Callable[..., dict[str, Any]],
    out: Path,
    *,
    limit: int,
    hours: float,
    now: datetime,
) -> tuple[list[str], dict[str, str]]:
    out.mkdir(parents=True, exist_ok=True)
    saved: list[str] = []
    errors: dict[str, str] = {}
    for name, operation, document, variables in captures(limit, hours, now):
        try:
            data = execute(document, variables, operation_name=operation)
        except SDKError as exc:
            errors[name] = f"{type(exc).__name__}: {exc}"
            continue
        record = {
            "operation": operation,
            "variables": variables,
            "captured_at": now.isoformat(),
            "data": data,
        }
        (out / f"{name}.json").write_text(json.dumps(record, indent=2, default=str) + "\n")
        saved.append(name)
    if errors:
        (out / "errors.json").write_text(json.dumps(errors, indent=2) + "\n")
    return saved, errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="rubrik-sample", description=__doc__.split("\n")[0])
    parser.add_argument("--limit", type=int, default=50, help="items per query (default 50)")
    parser.add_argument(
        "--hours", type=float, default=24, help="window for jobs-changed (default 24)"
    )
    parser.add_argument("--out", type=Path, help="folder to write (default samples/raw/<time>)")
    args = parser.parse_args(argv)

    config = load_config()
    account = ServiceAccount.from_json_file(config.require_service_account())
    now = datetime.now(UTC).replace(microsecond=0)
    out = args.out or config.samples_dir / now.strftime("%Y%m%dT%H%M%SZ")

    print(f"RSC account: {account.base_url}  (service account {account.name or '?'})")
    with RubrikClient(account, ca_bundle=config.ca_bundle) as rsc:
        saved, errors = run_captures(rsc.execute, out, limit=args.limit, hours=args.hours, now=now)
    print(f"Saved {len(saved)} answer(s) to {out}")
    for name, error in errors.items():
        print(f"  refused  {name}: {error[:200]}")
    print("These hold real names: run rubrik-mask before sharing them.")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
