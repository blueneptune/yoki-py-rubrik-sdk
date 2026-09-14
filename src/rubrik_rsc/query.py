"""Generic CRUD-analogue for GraphQL Relay connections.

This is the GraphQL equivalent of `BaseAPIModel` in a REST-flavoured SDK:
subclass `ConnectionQuery`, set `document` (the full GraphQL query text),
`operation_name`, `connection_path` (where in the response's `data` object
the connection lives), and `node_model` (the pydantic model each edge's
`node` parses into) - and the subclass gets single-page fetching *and*
transparent auto-pagination for free. None of that walking-`pageInfo` logic
needs to be rewritten per domain, which is the entire point of a *generic*
base class (see `cluster.py`/`sla_domain.py` for the concrete subclasses).

`ConnectionQuery` itself is never instantiated - every method is a
classmethod, so a subclass is just a named bundle of "this document, parsed
this way", handed an `RscClient` explicitly at call time rather than holding
one itself. That mirrors `BaseAPIModel.load()`/`.find()`: the caller is
always the one supplying the client (directly, or via a domain manager - see
`cluster.py`'s `ClusterManager` - that already has one).
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from pydantic import BaseModel

from .client import RscClient
from .pagination import Page, PageInfo


def _dig(data: dict[str, Any], path: tuple[str, ...]) -> dict[str, Any]:
    node = data
    for key in path:
        node = node[key]
    return node


class ConnectionQuery[M: BaseModel]:
    # Plain class attributes, not `ClassVar` - PEP 695 type parameters like
    # `M` above can't appear inside `ClassVar[...]`, and since this class is
    # never instantiated the ClassVar/instance-attribute distinction has no
    # runtime effect anyway. Each subclass sets these once, at class-body
    # level (see `cluster.py`'s `ClusterQuery`).
    document: str
    operation_name: str
    connection_path: tuple[str, ...]
    node_model: type[M]

    @classmethod
    def fetch_page(cls, client: RscClient, **variables: Any) -> Page[M]:
        """Fetch exactly one page. `variables` are the GraphQL document's
        variables verbatim (e.g. `first=`, `after=`, `filter=`, `sortBy=`) -
        any left as `None` are dropped rather than sent, since RSC's schema
        treats an omitted variable and an explicit `null` the same way for
        every variable used here, and dropping them keeps request bodies
        smaller.
        """
        clean_variables = {key: value for key, value in variables.items() if value is not None}
        data = client.execute(cls.document, clean_variables, operation_name=cls.operation_name)
        connection = _dig(data, cls.connection_path)
        items = [cls.node_model(**edge["node"]) for edge in connection["edges"]]
        page_info = PageInfo(**connection["pageInfo"])
        return Page(items=items, page_info=page_info)

    @classmethod
    def fetch_all(cls, client: RscClient, **variables: Any) -> Iterator[M]:
        """Walk every page via `pageInfo.hasNextPage`/`endCursor`, yielding
        items one at a time rather than building the full list in memory
        first - so callers can `break` out early (e.g. `find_by_name()` in
        `cluster.py`) without paying for pages they never needed.
        """
        after = variables.pop("after", None)
        while True:
            page = cls.fetch_page(client, after=after, **variables)
            yield from page.items
            if not page.page_info.has_next_page or not page.page_info.end_cursor:
                return
            after = page.page_info.end_cursor
