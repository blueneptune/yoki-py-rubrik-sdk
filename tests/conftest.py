"""Shared test fixtures and helpers.

RSC serves every GraphQL operation through one endpoint (`/api/graphql`), so
unlike a REST SDK's tests (which mock a different URL per resource/verb),
these tests all mock the *same* URL and instead dispatch on the request
body's `operationName` - `graphql_responder()` below is the small helper
that makes that dispatch reusable across test modules instead of
reimplementing it per test.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import httpx
import pytest

from rubrik_rsc import RscClient

BASE_URL = "https://test-instance.my.rubrik.com"
GRAPHQL_URL = f"{BASE_URL}/api/graphql"


def graphql_responder(
    responses_by_operation: dict[str, list[dict[str, Any]]],
) -> Callable[[httpx.Request], httpx.Response]:
    """Build a respx `side_effect` callable that returns the next queued
    GraphQL response body for whatever `operationName` the request carries.

    Each value in `responses_by_operation` is a list consumed in order - one
    entry per expected call to that operation, which is what lets a single
    test drive a multi-page pagination sequence (one list entry per page).
    """
    queues = {name: list(pages) for name, pages in responses_by_operation.items()}

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        operation_name = body.get("operationName")
        queue = queues[operation_name]
        payload = queue.pop(0)
        return httpx.Response(200, json=payload)

    return handler


@pytest.fixture
def client() -> RscClient:
    return RscClient(BASE_URL, token="test-token")


def make_page_info(*, has_next_page: bool = False, end_cursor: str | None = None) -> dict[str, Any]:
    return {
        "startCursor": None,
        "endCursor": end_cursor,
        "hasNextPage": has_next_page,
        "hasPreviousPage": False,
    }
