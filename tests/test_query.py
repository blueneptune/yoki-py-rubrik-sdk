"""Tests for the generic `ConnectionQuery` engine, using a small throwaway
domain (`Widget`/`WidgetQuery`) rather than `Cluster`/`SlaDomain` - this
proves the pagination/variable-cleaning logic is genuinely generic, not
something that happens to work only for the two real domains that also use
it (see test_cluster.py/test_sla_domain.py for those)."""

import json
from typing import Any

import respx
from pydantic import BaseModel

from rubrik_sdk import RubrikClient
from rubrik_sdk.query import ConnectionQuery

from .conftest import GRAPHQL_URL, graphql_responder, make_page_info


class Widget(BaseModel):
    id: str
    name: str


_WIDGET_DOCUMENT = """
query Widgets($first: Int, $after: String) {
  widgetConnection(first: $first, after: $after) {
    edges { node { id name } }
    pageInfo { startCursor endCursor hasNextPage hasPreviousPage }
  }
}
"""


class WidgetQuery(ConnectionQuery[Widget]):
    document = _WIDGET_DOCUMENT
    operation_name = "Widgets"
    connection_path = ("widgetConnection",)
    node_model = Widget


def _widget_page(*, ids: list[str], has_next_page: bool, end_cursor: str | None) -> dict[str, Any]:
    return {
        "data": {
            "widgetConnection": {
                "edges": [{"node": {"id": i, "name": f"widget-{i}"}} for i in ids],
                "pageInfo": make_page_info(has_next_page=has_next_page, end_cursor=end_cursor),
            }
        }
    }


@respx.mock
def test_fetch_page_parses_edges_and_page_info(client: RubrikClient) -> None:
    respx.post(GRAPHQL_URL).mock(
        side_effect=graphql_responder(
            {"Widgets": [_widget_page(ids=["1", "2"], has_next_page=True, end_cursor="c1")]}
        )
    )

    page = WidgetQuery.fetch_page(client, first=10)

    assert [w.id for w in page.items] == ["1", "2"]
    assert page.page_info.has_next_page is True
    assert page.page_info.end_cursor == "c1"


@respx.mock
def test_fetch_page_drops_none_variables(client: RubrikClient) -> None:
    route = respx.post(GRAPHQL_URL).mock(
        side_effect=graphql_responder(
            {"Widgets": [_widget_page(ids=[], has_next_page=False, end_cursor=None)]}
        )
    )

    WidgetQuery.fetch_page(client, first=None, after=None)

    sent_variables = json.loads(route.calls.last.request.content)["variables"]
    assert sent_variables == {}


@respx.mock
def test_fetch_all_walks_every_page_until_has_next_page_is_false(client: RubrikClient) -> None:
    respx.post(GRAPHQL_URL).mock(
        side_effect=graphql_responder(
            {
                "Widgets": [
                    _widget_page(ids=["1", "2"], has_next_page=True, end_cursor="c1"),
                    _widget_page(ids=["3"], has_next_page=False, end_cursor=None),
                ]
            }
        )
    )

    widgets = list(WidgetQuery.fetch_all(client))

    assert [w.id for w in widgets] == ["1", "2", "3"]


@respx.mock
def test_fetch_all_passes_end_cursor_as_next_after(client: RubrikClient) -> None:
    route = respx.post(GRAPHQL_URL).mock(
        side_effect=graphql_responder(
            {
                "Widgets": [
                    _widget_page(ids=["1"], has_next_page=True, end_cursor="c1"),
                    _widget_page(ids=["2"], has_next_page=False, end_cursor=None),
                ]
            }
        )
    )

    list(WidgetQuery.fetch_all(client))

    first_call_variables = json.loads(route.calls[0].request.content)["variables"]
    second_call_variables = json.loads(route.calls[1].request.content)["variables"]
    assert "after" not in first_call_variables
    assert second_call_variables["after"] == "c1"


@respx.mock
def test_fetch_all_stops_on_next_page_true_but_missing_end_cursor(client: RubrikClient) -> None:
    """Defensive: a malformed/edge-case response claiming more pages exist
    but without a cursor to fetch them with should stop rather than loop
    forever re-requesting the same page."""
    respx.post(GRAPHQL_URL).mock(
        side_effect=graphql_responder(
            {"Widgets": [_widget_page(ids=["1"], has_next_page=True, end_cursor=None)]}
        )
    )

    widgets = list(WidgetQuery.fetch_all(client))

    assert [w.id for w in widgets] == ["1"]
