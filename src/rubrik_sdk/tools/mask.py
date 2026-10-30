"""rubrik-mask: turn raw samples (rubrik-sample) into ones that are safe
to share - commit to this repository, paste into a chat, attach to a
ticket.

    uv run rubrik-mask                     # the newest folder in samples/raw
    uv run rubrik-mask samples/raw/20261028T150000Z --out samples/masked/first

How it masks
------------
Every string is replaced, unless its field is on a short list of fields
that only ever hold Rubrik's own vocabulary (statuses, types, severities)
or it is a timestamp. Unknown fields are masked: a field nobody thought
about is the one that leaks.

The replacement is an HMAC of the value with your salt
(RUBRIK_MASK_SALT), so it is:

- consistent - the same host is `objectName-3f2a9c1b` in every file and
  every capture, so relationships survive (this job ran on that object,
  on that cluster);
- not reversible, and not guessable - without the salt, nobody can
  check whether `objectName-3f2a9c1b` is "sql01" by masking "sql01"
  themselves. That is what the salt is for; keep it secret and keep it
  the same, or the pseudonyms change.

Shapes are kept: UUIDs become other UUIDs, IPv4 addresses 10.x.x.x,
e-mail addresses user-...@example.invalid, so the samples still parse
as RSC answers and can serve as test fixtures.

Before anything is written, every string left unmasked is searched for
the values that were masked; if one turns up there (a status field
holding a hostname, say), nothing is written and the command fails,
naming the fields and files involved - not the value, so the message can
be pasted; `--show-leaks` adds the values, for your own terminal.
A map from pseudonym back to original is written beside the *raw*
samples (never beside the masked ones), for your own look-ups.

Nothing here knows about Rubrik except KEEP_FIELDS; the masker can move
to sdk-primer-core when another SDK needs one.
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import ipaddress
import json
import re
import sys
import uuid
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .config import load_config

# Fields whose string values are Rubrik's vocabulary, not the customer's.
KEEP_FIELDS = frozenset(
    {
        # activity series
        "lastActivityStatus",
        "lastActivityType",
        "objectType",
        "severity",
        "progress",
        # inventory objects
        "objectState",
        "protectionStatus",
        "complianceStatus",
        "archivalComplianceStatus",
        "replicationComplianceStatus",
        # clusters, SLA domains, snapshots
        "status",
        "subStatus",
        "pauseStatus",
        "type",
        "productType",
        "version",
        "timezone",
        "state",
        "vendor",
        "region",
        "unit",
        "retentionUnit",
        "frequency",
        # GraphQL plumbing and the capture's own envelope
        "__typename",
        "operation",
        "sortBy",
        "sortOrder",
        "captured_at",
        "endCursor",
        "startCursor",
    }
)
# Subtrees kept whole: RSC's schema description is not customer data.
KEEP_SUBTREES = frozenset({"__type", "schema"})
# Not worth masking, and masking them would hide nothing: too short to be
# a name.
MIN_MASK_LENGTH = 3

_TIMESTAMP = re.compile(
    r"^\d{4}-\d{2}-\d{2}([T ]\d{2}:\d{2}(:\d{2}(\.\d+)?)?(Z|[+-]\d{2}:?\d{2})?)?$"
)
_UUID = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


@dataclass
class Masker:
    salt: str
    keep_fields: frozenset[str] = KEEP_FIELDS
    keep_subtrees: frozenset[str] = KEEP_SUBTREES
    # pseudonym -> original, for the private map
    mapping: dict[str, str] = field(default_factory=dict)
    # original -> the fields it was masked in
    masked_in: dict[str, set[str]] = field(default_factory=dict)
    # (file, field, value) for each string left as it was - where a leak
    # would be
    kept: list[tuple[str, str, str]] = field(default_factory=list)
    # the file being masked, for the leak report
    source: str = ""

    def _digest(self, value: str) -> bytes:
        return hmac.new(self.salt.encode(), value.encode(), hashlib.sha256).digest()

    def pseudonym(self, value: str, label: str) -> str:
        """The masked form of one string, keeping its shape."""
        digest = self._digest(value)
        if _UUID.match(value):
            masked = str(uuid.UUID(bytes=digest[:16], version=4))
        elif _is_ipv4(value):
            masked = f"10.{digest[0]}.{digest[1]}.{digest[2]}"
        elif _EMAIL.match(value):
            masked = f"user-{digest.hex()[:8]}@example.invalid"
        else:
            masked = f"{label or 'value'}-{digest.hex()[:8]}"
        self.mapping[masked] = value
        self.masked_in.setdefault(value, set()).add(f"{label or 'value'} ({self.source})")
        return masked

    def mask(self, data: Any, key: str = "") -> Any:
        if isinstance(data, dict):
            return {k: (v if k in self.keep_subtrees else self.mask(v, k)) for k, v in data.items()}
        if isinstance(data, list):
            return [self.mask(item, key) for item in data]
        if isinstance(data, str):
            if key in self.keep_fields or _TIMESTAMP.match(data) or len(data) < MIN_MASK_LENGTH:
                self.kept.append((self.source, key, data))
                return data
            return self.pseudonym(data, key)
        return data  # numbers, booleans, null


def _is_ipv4(value: str) -> bool:
    try:
        return isinstance(ipaddress.ip_address(value), ipaddress.IPv4Address)
    except ValueError:
        return False


@dataclass(frozen=True)
class Leak:
    value: str
    masked_in: tuple[str, ...]  # "field (file)" where it was masked
    kept_field: str
    kept_file: str

    def describe(self, *, show_value: bool = False) -> str:
        where = ", ".join(self.masked_in)
        text = (
            f"a value masked in {where} also appears in kept field "
            f"`{self.kept_field}` ({self.kept_file})"
        )
        return f"{text}: {self.value!r}" if show_value else text


def leaks(kept: Iterable[tuple[str, str, str]], masked_in: dict[str, set[str]]) -> list[Leak]:
    """Masked originals that still appear inside a string left as it was
    - a vocabulary field holding a customer's name, say. Matched as a whole
    word, so `1028` is not found inside `2026-10-28`. (Pseudonyms are not
    searched: they are made from the field name and a hash.)"""
    candidates = [v for v in masked_in if len(v) > MIN_MASK_LENGTH]
    found: dict[tuple[str, str, str], Leak] = {}
    for source, key, text in set(kept):
        for value in candidates:
            if value in text and re.search(
                rf"(?<![A-Za-z0-9]){re.escape(value)}(?![A-Za-z0-9])", text
            ):
                found.setdefault(
                    (value, key, source),
                    Leak(value, tuple(sorted(masked_in[value])), key, source),
                )
    return sorted(found.values(), key=lambda leak: (leak.kept_file, leak.kept_field, leak.value))


def mask_folder(raw: Path, out: Path, salt: str, *, show_leaks: bool = False) -> dict[str, int]:
    """Mask every .json file in `raw` into `out`. Writes nothing if any
    original value would survive."""
    masker = Masker(salt)
    results: dict[Path, str] = {}
    for source in sorted(raw.glob("*.json")):
        if source.name == "mask-map.json":
            continue
        masker.source = source.name
        masked = masker.mask(json.loads(source.read_text()))
        results[out / source.name] = json.dumps(masked, indent=2, sort_keys=False)

    survived = leaks(masker.kept, masker.masked_in)
    if survived:
        lines = "\n".join(f"  {leak.describe(show_value=show_leaks)}" for leak in survived)
        raise SystemExit(
            f"Not written: {len(survived)} masked value(s) also appear in fields kept as "
            f"vocabulary (KEEP_FIELDS), so masking would not hide them. Nothing was written.\n"
            f"{lines}\n"
            "If the kept field can hold customer data, take it off KEEP_FIELDS; if the masked "
            "value is really Rubrik's vocabulary (a status, say), add its field to KEEP_FIELDS."
            + ("" if show_leaks else " --show-leaks prints the values (keep that output private).")
        )

    out.mkdir(parents=True, exist_ok=True)
    for target, text in results.items():
        target.write_text(text + "\n")
    # The way back, beside the raw samples only.
    (raw / "mask-map.json").write_text(json.dumps(masker.mapping, indent=2, sort_keys=True))
    return {"files": len(results), "values_masked": len(masker.mapping)}


def _newest(folder: Path) -> Path:
    captures = sorted(p for p in folder.iterdir() if p.is_dir()) if folder.is_dir() else []
    if not captures:
        raise SystemExit(f"No captures in {folder} - run rubrik-sample first.")
    return captures[-1]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="rubrik-mask", description=__doc__.split("\n")[0])
    parser.add_argument("raw", nargs="?", type=Path, help="a capture folder (default: the newest)")
    parser.add_argument("--out", type=Path, help="where to write (default: under the masked dir)")
    parser.add_argument(
        "--show-leaks", action="store_true", help="print leaked values (private: real names)"
    )
    args = parser.parse_args(argv)

    config = load_config()
    salt = config.require_salt()
    raw = args.raw or _newest(config.samples_dir)
    out = args.out or config.masked_dir / raw.name
    if out.resolve() == raw.resolve():
        raise SystemExit("--out must not be the raw folder.")

    counts = mask_folder(raw, out, salt, show_leaks=args.show_leaks)
    print(f"Masked {counts['files']} file(s), {counts['values_masked']} distinct value(s):")
    print(f"  {raw}  ->  {out}")
    print("  leak check: no original value appears in the masked files")
    print(f"  map back to the originals (private): {raw / 'mask-map.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
