"""The tools' settings: a .env file in the current folder (or the one
RUBRIK_ENV_FILE names), with the process environment winning over it.

    cp .env.example .env      # then fill it in; .env is never committed

Read by hand rather than with python-dotenv so the SDK gains no
dependency for its tools: KEY=value lines, # comments, optional quotes.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

ENV_FILE = ".env"
# A salt shorter than this is refused: it is what stops someone who
# guesses a hostname from checking the guess against a masked sample.
MIN_SALT_LENGTH = 16


def read_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip().removeprefix("export ").strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        values[key] = value
    return values


@dataclass(frozen=True)
class ToolConfig:
    service_account: Path | None
    ca_bundle: Path | None
    samples_dir: Path
    masked_dir: Path
    salt: str | None

    def require_service_account(self) -> Path:
        if self.service_account is None:
            raise SystemExit(
                "Set RUBRIK_SERVICE_ACCOUNT in .env (or the environment) to the service "
                "account's JSON file."
            )
        if not self.service_account.is_file():
            raise SystemExit(f"Service account file not found: {self.service_account}")
        return self.service_account

    def require_salt(self) -> str:
        if not self.salt:
            raise SystemExit(
                "Set RUBRIK_MASK_SALT in .env - a long random secret of your own, e.g.\n"
                '  python -c "import secrets; print(secrets.token_urlsafe(32))"'
            )
        if len(self.salt) < MIN_SALT_LENGTH:
            raise SystemExit(f"RUBRIK_MASK_SALT must be at least {MIN_SALT_LENGTH} characters.")
        return self.salt


def _path(value: str | None) -> Path | None:
    return Path(value).expanduser() if value else None


def load_config(environ: Mapping[str, str] | None = None) -> ToolConfig:
    env = dict(os.environ if environ is None else environ)
    file_values = read_env_file(Path(env.get("RUBRIK_ENV_FILE", ENV_FILE)).expanduser())
    merged = {**file_values, **{k: v for k, v in env.items() if v != ""}}
    return ToolConfig(
        service_account=_path(merged.get("RUBRIK_SERVICE_ACCOUNT")),
        ca_bundle=_path(merged.get("RUBRIK_CA_BUNDLE")),
        samples_dir=_path(merged.get("RUBRIK_SAMPLES_DIR")) or Path("samples/raw"),
        masked_dir=_path(merged.get("RUBRIK_MASKED_DIR")) or Path("samples/masked"),
        salt=merged.get("RUBRIK_MASK_SALT") or None,
    )
