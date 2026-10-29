import json
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from sdk_primer import ServerError

from rubrik_sdk.tools.config import load_config, read_env_file
from rubrik_sdk.tools.mask import Masker, leaks, mask_folder
from rubrik_sdk.tools.sample import SCHEMA_TYPES, run_captures

SALT = "a-test-salt-that-is-long-enough"


# -- config ------------------------------------------------------------------


def test_the_env_file_is_read_and_the_environment_wins(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "# comment\n"
        "RUBRIK_SERVICE_ACCOUNT=~/sa.json\n"
        'RUBRIK_MASK_SALT="from-the-file-0123456789"\n'
        "export RUBRIK_SAMPLES_DIR='captures'\n"
        "RUBRIK_CA_BUNDLE=\n"
    )

    config = load_config(
        {"RUBRIK_ENV_FILE": str(env_file), "RUBRIK_MASK_SALT": "from-the-environment-0123"}
    )

    assert config.service_account == Path("~/sa.json").expanduser()
    assert config.salt == "from-the-environment-0123"
    assert config.samples_dir == Path("captures")
    assert config.masked_dir == Path("samples/masked")
    assert config.ca_bundle is None


def test_a_missing_env_file_is_no_settings(tmp_path: Path) -> None:
    assert read_env_file(tmp_path / "absent") == {}


@pytest.mark.parametrize("salt", [None, "short"])
def test_masking_refuses_without_a_proper_salt(tmp_path: Path, salt: str | None) -> None:
    env = {"RUBRIK_ENV_FILE": str(tmp_path / "none")}
    if salt:
        env["RUBRIK_MASK_SALT"] = salt
    with pytest.raises(SystemExit):
        load_config(env).require_salt()


# -- masking -----------------------------------------------------------------


def series(name: str, host_uuid: str, status: str = "Success") -> dict[str, Any]:
    return {
        "id": "12345",
        "fid": host_uuid,
        "objectName": name,
        "location": f"{name}.corp.example.com",
        "objectType": "Mssql",
        "lastActivityStatus": status,
        "lastActivityType": "Backup",
        "startTime": "2026-10-28T10:00:00Z",
        "progress": "100",
        "cluster": {"id": "c-7", "name": "rubrik-east-01"},
        "owner": "dba@corp.example.com",
        "address": "192.168.10.44",
        "count": 3,
        "ok": True,
    }


def test_names_are_masked_and_vocabulary_kept() -> None:
    host = "7b0e3c8e-4a5f-4c1e-9d2a-0f1e2d3c4b5a"
    masked = Masker(SALT).mask(series("sql01", host))

    assert masked["objectName"].startswith("objectName-") and "sql01" not in json.dumps(masked)
    assert masked["cluster"]["name"].startswith("name-")
    assert masked["lastActivityStatus"] == "Success"
    assert masked["objectType"] == "Mssql" and masked["lastActivityType"] == "Backup"
    assert masked["startTime"] == "2026-10-28T10:00:00Z"
    assert masked["count"] == 3 and masked["ok"] is True


def test_shapes_survive_masking() -> None:
    host = "7b0e3c8e-4a5f-4c1e-9d2a-0f1e2d3c4b5a"
    masked = Masker(SALT).mask(series("sql01", host))

    assert uuid.UUID(masked["fid"]) and masked["fid"] != host
    assert masked["address"].startswith("10.") and masked["address"].count(".") == 3
    assert masked["owner"].endswith("@example.invalid")


def test_the_same_value_masks_the_same_way_and_another_salt_differently() -> None:
    first = Masker(SALT).mask([series("sql01", "x" * 8), series("sql01", "y" * 8)])
    again = Masker(SALT).mask(series("sql01", "z" * 8))
    other = Masker(SALT + "-other").mask(series("sql01", "z" * 8))

    assert first[0]["objectName"] == first[1]["objectName"] == again["objectName"]
    assert other["objectName"] != again["objectName"]


def test_the_schema_is_kept_whole() -> None:
    data = {"data": {"__type": {"name": "ActivitySeries", "fields": [{"name": "objectName"}]}}}

    assert Masker(SALT).mask(data) == data


def capture_folder(tmp_path: Path, *records: dict[str, Any]) -> Path:
    raw = tmp_path / "raw" / "20261028T150000Z"
    raw.mkdir(parents=True)
    for number, record in enumerate(records):
        (raw / f"answer-{number}.json").write_text(json.dumps(record))
    return raw


def test_a_folder_is_masked_with_the_map_kept_beside_the_raw_files(tmp_path: Path) -> None:
    raw = capture_folder(tmp_path, {"data": [series("sql01", "a" * 8)]})
    out = tmp_path / "masked" / raw.name

    counts = mask_folder(raw, out, SALT)

    text = (out / "answer-0.json").read_text()
    assert "sql01" not in text and "corp.example.com" not in text
    assert counts["files"] == 1
    mapping = json.loads((raw / "mask-map.json").read_text())
    assert "sql01" in mapping.values()
    assert not (out / "mask-map.json").exists()


def test_nothing_is_written_if_a_masked_value_sits_in_a_kept_field(tmp_path: Path) -> None:
    # A status field that, here, holds a host's name.
    raw = capture_folder(
        tmp_path, {"data": [series("sql01", "a" * 8), series("vm-two", "b" * 8, status="sql01")]}
    )
    out = tmp_path / "masked" / raw.name

    with pytest.raises(SystemExit, match="Nothing was written") as failure:
        mask_folder(raw, out, SALT)
    assert not out.exists()
    message = str(failure.value)
    assert "objectName (answer-0.json)" in message and "`lastActivityStatus`" in message
    assert "sql01" not in message

    with pytest.raises(SystemExit, match="'sql01'"):
        mask_folder(raw, out, SALT, show_leaks=True)


def test_a_value_inside_a_longer_word_is_not_a_leak() -> None:
    masker = Masker(SALT)
    masker.source = "a.json"
    masker.mask({"objectName": "1028", "startTime": "2026-10-28T10:28:00Z", "x": "1028"})
    masker.mask({"status": "Backup of 10280 done"})

    assert leaks(masker.kept, masker.masked_in) == []


# -- sampling ----------------------------------------------------------------


def test_captures_are_saved_one_file_each_and_refusals_recorded(tmp_path: Path) -> None:
    asked: list[str] = []

    def execute(document: str, variables: dict[str, Any], *, operation_name: str) -> dict[str, Any]:
        asked.append(operation_name)
        if operation_name == "SlaDomains":
            raise ServerError("no permission")
        return {"answer": operation_name}

    now = datetime(2026, 10, 28, 15, 0, tzinfo=UTC)
    saved, errors = run_captures(execute, tmp_path, limit=5, hours=24, now=now)

    assert "jobs-changed" in saved and "clusters" in saved
    assert errors == {"sla-domains": "ServerError: no permission"}
    changed = json.loads((tmp_path / "jobs-changed.json").read_text())
    assert changed["variables"]["filters"] == {"lastUpdatedTimeGt": "2026-10-27T15:00:00Z"}
    assert changed["data"] == {"answer": "ActivitySeriesPage"}
    assert len([n for n in saved if n.startswith("schema-")]) == len(SCHEMA_TYPES)
    assert json.loads((tmp_path / "errors.json").read_text()) == errors
