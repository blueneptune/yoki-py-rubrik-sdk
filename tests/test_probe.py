import json
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx

from rubrik_sdk.tools import probe

from .conftest import BASE_URL, GRAPHQL_URL
from .test_activity import _activity_series_node
from .test_cluster import _cluster_node

TYPES: dict[str, dict[str, Any] | None] = {
    "ActivitySeries": {
        "fields": [{"name": n} for n in probe._SELECTED_FIELDS + ["endTime", "clusterUuid"]]
    },
    "ActivitySeriesFilter": {"inputFields": [{"name": "startTimeGt"}, {"name": "objectFid"}]},
    "ActivitySeriesSortField": {"enumValues": [{"name": "LAST_UPDATED"}, {"name": "START_TIME"}]},
    "ActivityStatusEnum": None,
}


def _answer(request: httpx.Request) -> httpx.Response:
    body = json.loads(request.content)
    name = body.get("operationName")
    if name == "ProbeSignIn":
        return httpx.Response(200, json={"data": {"__typename": "Query"}})
    if name == "ProbeType":
        found = TYPES[body["variables"]["name"]]
        return httpx.Response(200, json={"data": {"__type": found}})
    if name == "ActivitySeriesPage":
        node = _activity_series_node(id="a", object_name="secret-host")
        node.pop("activityConnection")
        connection = {"edges": [{"node": node}], "pageInfo": {"hasNextPage": False}}
        return httpx.Response(200, json={"data": {"activitySeriesConnection": connection}})
    if name == "Cluster":
        connection = {
            "edges": [{"node": _cluster_node(id="c", name="cl")}],
            "pageInfo": {"hasNextPage": False},
        }
        return httpx.Response(200, json={"data": {"clusterConnection": connection}})
    raise AssertionError(f"unexpected operation {name}")


@respx.mock
def test_the_probe_reports_each_check_and_keeps_names_out_of_its_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    account = tmp_path / "sa.json"
    account.write_text(
        json.dumps(
            {
                "client_id": "id",
                "client_secret": "s3cr3t",
                "access_token_uri": f"{BASE_URL}/api/client_token",
                "name": "blt-reader",
            }
        )
    )
    monkeypatch.setenv("RUBRIK_SERVICE_ACCOUNT", str(account))
    monkeypatch.setenv("RUBRIK_ENV_FILE", str(tmp_path / "no.env"))
    monkeypatch.setenv("RUBRIK_PROBE_SAVE", str(tmp_path / "saved"))
    respx.post(f"{BASE_URL}/api/client_token").mock(
        return_value=httpx.Response(200, json={"access_token": "tok"})
    )
    respx.post(GRAPHQL_URL).mock(side_effect=_answer)
    respx.delete(f"{BASE_URL}/api/session").mock(return_value=httpx.Response(204))

    code = probe.main()

    out = capsys.readouterr().out
    assert code == 1  # the missing filter is a failure
    assert "ok    sign in" in out
    assert "all selected fields exist; also available: endTime, clusterUuid" in out
    assert "FAIL  ActivitySeriesFilter: LookupError: {'lastUpdatedTimeGt': 'MISSING'" in out
    assert "ok    ActivitySeriesSortField" in out
    assert "FAIL  ActivityStatusEnum" not in out  # an absent type is reported, not a crash
    assert "ok    newest series: 1 newest" in out
    assert "ok    clusters: 1 cluster(s)" in out
    assert "secret-host" not in out and "s3cr3t" not in out
    assert (tmp_path / "saved" / "sample.json").exists()
