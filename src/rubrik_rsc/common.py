"""Tiny reference models reused across domain modules.

Several different queries across RSC's schema embed the *same* small
summary of a cluster or SLA domain (just `{ id name }`) as a sub-selection,
rather than the full object a dedicated query would return. Sharing one
model for that shape here means `activity.py`/`mssql.py` don't each redefine
an identical two-field class under a slightly different name.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel

CAMEL_CONFIG = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class ClusterReference(BaseModel):
    model_config = CAMEL_CONFIG

    id: str
    name: str


class SlaDomainReference(BaseModel):
    model_config = CAMEL_CONFIG

    id: str
    name: str
