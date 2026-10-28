"""rubrik-probe: try each call blt makes, once, against a real RSC account,
and say what happened - including what RSC's own schema says about every
name the SDK had to guess.

    RUBRIK_SERVICE_ACCOUNT=~/blt-reader.json rubrik-probe

Optional: RUBRIK_CA_BUNDLE=/path/to/ca.pem (a proxy that re-signs TLS),
RUBRIK_PROBE_SAVE=/some/folder to also write each raw answer there as
JSON for a closer look. Reads only; stores nothing unless asked to.

What it prints is meant to be safe to paste into a chat or a ticket:
counts, field names, status and type values - never object names,
locations, ids or the secret. The saved files (if asked for) are the
raw answers and do contain names: look before sharing them.
"""

from __future__ import annotations

import json
import os
import sys
from collections import Counter
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from .activity import (
    _ACTIVITY_SERIES_PAGE_DOCUMENT,
    FILTER_STARTED_AFTER,
    FILTER_UPDATED_AFTER,
    SORT_LAST_UPDATED,
    SORT_START_TIME,
)
from .auth import ServiceAccount
from .client import RubrikClient

Check = tuple[str, Callable[[], str]]

_TYPE_QUERY = """
query ProbeType($name: String!) {
  __type(name: $name) {
    name
    fields { name }
    inputFields { name }
    enumValues { name }
  }
}
"""

# Fields of ActivitySeries the collection query selects.
_SELECTED_FIELDS = [
    line.strip()
    for line in _ACTIVITY_SERIES_PAGE_DOCUMENT.split("node {", 1)[1]
    .split("cluster {", 1)[0]
    .split()
] + ["cluster"]

# Fields blt would like next, if the schema has them.
_WANTED_FIELDS = [
    "endTime",
    "clusterUuid",
    "clusterName",
    "objectCdmId",
    "causeErrorMessage",
    "causeErrorCode",
    "dataTransferred",
    "logicalSize",
    "effectiveThroughput",
    "isCancelable",
    "username",
    "orgName",
]


def checks(rsc: RubrikClient, save: Path | None) -> list[Check]:
    day_ago = datetime.now(UTC) - timedelta(hours=24)

    def keep(name: str, data: Any) -> None:
        if save is not None:
            save.mkdir(parents=True, exist_ok=True)
            (save / f"{name}.json").write_text(json.dumps(data, indent=2, default=str))

    def schema(name: str) -> dict[str, Any]:
        data = rsc.execute(_TYPE_QUERY, {"name": name}, operation_name="ProbeType")
        keep(f"schema-{name}", data)
        found: dict[str, Any] | None = data.get("__type")
        if found is None:
            raise LookupError(f"the schema has no type {name}")
        return found

    def names(entries: list[dict[str, Any]] | None) -> set[str]:
        return {entry["name"] for entry in entries or []}

    def sign_in() -> str:
        # The first call fetches the token; any answer at all means it worked.
        rsc.execute("query ProbeSignIn { __typename }", operation_name="ProbeSignIn")
        return "token fetched, GraphQL answering"

    def series_fields() -> str:
        have = names(schema("ActivitySeries")["fields"])
        missing = [f for f in _SELECTED_FIELDS if f not in have]
        wanted = [f for f in _WANTED_FIELDS if f in have]
        extra = f"also available: {', '.join(wanted) or 'none of the wanted ones'}"
        if missing:
            raise LookupError(f"MISSING: {', '.join(missing)}; {extra}")
        return f"all selected fields exist; {extra}"

    def filter_fields() -> str:
        have = names(schema("ActivitySeriesFilter")["inputFields"])
        verdict = {
            name: ("ok" if name in have else "MISSING")
            for name in (FILTER_UPDATED_AFTER, FILTER_STARTED_AFTER)
        }
        times = sorted(n for n in have if "time" in n.lower() or "updated" in n.lower())
        report = f"{verdict}; time filters the schema has: {', '.join(times)}"
        if "MISSING" in verdict.values():
            raise LookupError(report)
        return report

    def sort_fields() -> str:
        have = names(schema("ActivitySeriesSortField")["enumValues"])
        verdict = {
            name: ("ok" if name in have else "MISSING")
            for name in (SORT_LAST_UPDATED, SORT_START_TIME)
        }
        report = f"{verdict}; all: {', '.join(sorted(have))}"
        if "MISSING" in verdict.values():
            raise LookupError(report)
        return report

    def status_values() -> str:
        try:
            have = names(schema("ActivityStatusEnum")["enumValues"])
        except LookupError as exc:
            return str(exc)
        return ", ".join(sorted(have))

    def sample() -> str:
        series = rsc.jobs.sample(20)
        keep("sample", [s.model_dump(mode="json") for s in series])
        if not series:
            return "no activity series at all"
        statuses = Counter(s.last_activity_status for s in series)
        kinds = Counter(s.last_activity_type for s in series)
        objects = Counter(s.object_type for s in series)
        newest = max((s.last_updated for s in series if s.last_updated), default=None)
        return (
            f"{len(series)} newest: statuses {dict(statuses)}; types {dict(kinds)}; "
            f"object types {dict(objects)}; newest update {newest}; "
            f"active {sum(s.is_active for s in series)}; "
            f"with fid {sum(bool(s.fid) for s in series)}"
        )

    def delta() -> str:
        count = pages = 0
        for page in rsc.jobs.iter_pages(updated_after=day_ago):
            pages += 1
            count += len(page)
            if pages >= 10:
                return f"{count} series changed in the last 24 h (stopped after {pages} pages)"
        return f"{count} series changed in the last 24 h, {pages} page(s)"

    def clusters() -> str:
        found = list(rsc.clusters.all())
        return f"{len(found)} cluster(s): statuses {dict(Counter(c.status for c in found))}"

    return [
        ("sign in", sign_in),
        ("ActivitySeries fields", series_fields),
        ("ActivitySeriesFilter", filter_fields),
        ("ActivitySeriesSortField", sort_fields),
        ("ActivityStatusEnum", status_values),
        ("newest series", sample),
        ("delta, last 24 h", delta),
        ("clusters", clusters),
    ]


def main() -> int:
    path = os.environ.get("RUBRIK_SERVICE_ACCOUNT")
    if not path:
        print("Set RUBRIK_SERVICE_ACCOUNT to the service account's JSON file.", file=sys.stderr)
        return 2
    account = ServiceAccount.from_json_file(Path(path).expanduser())
    ca = os.environ.get("RUBRIK_CA_BUNDLE")
    save_dir = os.environ.get("RUBRIK_PROBE_SAVE")
    save = Path(save_dir).expanduser() if save_dir else None

    print(f"RSC account: {account.base_url}  (service account {account.name or '?'})")
    failures = 0
    with RubrikClient(account, ca_bundle=Path(ca) if ca else None) as rsc:
        for name, check in checks(rsc, save):
            try:
                print(f"  ok    {name}: {check()}")
            except Exception as exc:  # noqa: BLE001 - the point is to report every failure
                failures += 1
                print(f"  FAIL  {name}: {type(exc).__name__}: {str(exc)[:300]}")
    if save is not None:
        print(f"Raw answers saved in {save} - they contain names; look before sharing.")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
