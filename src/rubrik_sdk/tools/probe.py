"""rubrik-probe: try each call blt makes, once, against a real RSC account,
and say what happened - including what RSC's own schema says about every
name the SDK had to guess.

    uv run rubrik-probe

The service account file and, if needed, a CA bundle come from .env
(RUBRIK_SERVICE_ACCOUNT, RUBRIK_CA_BUNDLE - see .env.example) or the
environment. RUBRIK_PROBE_SAVE=/some/folder also writes each raw answer
there. Reads only; stores nothing unless asked to - rubrik-sample is the
command for keeping answers.

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

from ..activity import (
    _ACTIVITY_SERIES_PAGE_DOCUMENT,
    FILTER_STARTED_AFTER,
    FILTER_UPDATED_AFTER,
    SORT_LAST_UPDATED,
    SORT_START_TIME,
)
from ..auth import ServiceAccount
from ..client import RubrikClient
from ..inventory import _OBJECT_FIELDS
from .config import load_config

Check = tuple[str, Callable[[], str]]

_TYPE_QUERY = """
query ProbeType($name: String!) {
  __type(name: $name) {
    name
    fields(includeDeprecated: true) { name isDeprecated }
    inputFields { name }
    enumValues(includeDeprecated: true) { name }
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

# Fields of Snappable the inventory query selects.
_OBJECT_SELECTED = [line.strip() for line in _OBJECT_FIELDS.split("slaDomain {", 1)[0].split()] + [
    "slaDomain",
    "cluster",
]
# How far the inventory check walks: enough for a picture, not the whole
# account.
_INVENTORY_PAGES = 25

# Fields blt would like next, if the schema has them.
_WANTED_FIELDS = [
    "endTime",
    "clusterUuid",
    "clusterName",
    "objectCdmId",
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

    def object_fields() -> str:
        fields = schema("Snappable")["fields"] or []
        have = names(fields)
        deprecated = {f["name"] for f in fields if f.get("isDeprecated")}
        missing = [f for f in _OBJECT_SELECTED if f not in have]
        old = [f for f in _OBJECT_SELECTED if f in deprecated]
        if missing:
            raise LookupError(f"MISSING: {', '.join(missing)}")
        note = f"; deprecated: {', '.join(old)}" if old else ""
        return f"all {len(_OBJECT_SELECTED)} selected fields exist{note}"

    def object_enums() -> str:
        found = []
        for name in ("ProtectionStatusEnum", "ComplianceStatusEnum", "ObjectState"):
            try:
                found.append(f"{name}: {', '.join(sorted(names(schema(name)['enumValues'])))}")
            except LookupError as exc:
                found.append(str(exc))
        return "; ".join(found)

    def inventory_sample() -> str:
        objects = rsc.inventory.sample(20)
        keep("inventory-sample", [o.model_dump(mode="json") for o in objects])
        if not objects:
            return "no objects at all"
        return (
            f"{len(objects)} read; with fid {sum(bool(o.fid) for o in objects)}, "
            f"with SLA domain {sum(bool(o.sla_domain) for o in objects)}, "
            f"with cluster {sum(bool(o.cluster) for o in objects)}, "
            f"with org {sum(bool(o.org_id) for o in objects)}"
        )

    def inventory() -> str:
        count = pages = 0
        types: Counter[str | None] = Counter()
        protection: Counter[str | None] = Counter()
        states: Counter[str | None] = Counter()
        for page in rsc.inventory.iter_pages():
            pages += 1
            count += len(page)
            types.update(o.object_type for o in page)
            protection.update(o.protection_status for o in page)
            states.update(o.object_state for o in page)
            if pages >= _INVENTORY_PAGES:
                break
        whole = "all of it" if pages < _INVENTORY_PAGES else f"stopped after {pages} pages"
        return (
            f"{count} objects ({whole}): types {dict(types.most_common())}; "
            f"protection {dict(protection)}; states {dict(states)}"
        )

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
        ("Snappable fields", object_fields),
        ("inventory enums", object_enums),
        ("inventory sample", inventory_sample),
        ("inventory", inventory),
    ]


def main() -> int:
    config = load_config()
    account = ServiceAccount.from_json_file(config.require_service_account())
    save_dir = os.environ.get("RUBRIK_PROBE_SAVE")
    save = Path(save_dir).expanduser() if save_dir else None

    print(f"RSC account: {account.base_url}  (service account {account.name or '?'})")
    failures = 0
    with RubrikClient(account, ca_bundle=config.ca_bundle) as rsc:
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
