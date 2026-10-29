"""Generic support for RSC's Relay-style connections, plus a matching
wrapper for the schema's occasional flat (unpaginated) list.

Every *paginated* list-returning query in the RSC schema follows the same
shape:

    someConnection(first: Int, after: String, ...) {
      edges { node { ...fields... } }
      pageInfo { startCursor endCursor hasNextPage hasPreviousPage }
    }

`PageInfo` models that `pageInfo` block once, and `Page` bundles one page's
worth of already-parsed model instances together with it. A handful of
queries (see `mssql.py`'s `mssqlDatabases`) instead return every result as a
flat `nodes` list with no pagination at all - `Collection` is `Page` without
the `page_info`, for that shape.

Every one of these - `PageInfo`, `Page`, `Collection`, and every domain
model they wrap - is a pydantic `BaseModel`, not a plain dataclass or bare
list: whatever a domain manager method hands back, you can call
`.model_dump()`/`.model_dump_json()` on it the same way, whether it's one
object, a page of them, or the whole flat list. Both `Page` and `Collection`
are generic over "whatever node type this particular query returns" so
they're reused as-is by every domain (see `query.py`, which is what
actually walks pages using these two types) instead of being redefined per
domain the way the GraphQL documents themselves are.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel


class PageInfo(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    start_cursor: str | None = None
    end_cursor: str | None = None
    has_next_page: bool = False
    has_previous_page: bool = False


class Page[M](BaseModel):
    items: list[M]
    page_info: PageInfo


class Collection[M](BaseModel):
    items: list[M]
