"""`Page`/`Collection` are the only two return shapes in this SDK that wrap
more than one domain model together - these tests confirm both are genuine
pydantic `BaseModel`s (not a dataclass/plain list), so every value returned
anywhere in the SDK supports `.model_dump()`/`.model_dump_json()`
uniformly."""

import json

from pydantic import BaseModel

from rubrik_sdk import Collection, Page, PageInfo


class Widget(BaseModel):
    id: str
    name: str


def test_page_is_a_pydantic_model_and_dumps_to_json() -> None:
    page = Page[Widget](
        items=[Widget(id="1", name="widget-1")],
        page_info=PageInfo(has_next_page=True, end_cursor="c1"),
    )

    assert isinstance(page, BaseModel)
    dumped = json.loads(page.model_dump_json())
    assert dumped == {
        "items": [{"id": "1", "name": "widget-1"}],
        "page_info": {
            "start_cursor": None,
            "end_cursor": "c1",
            "has_next_page": True,
            "has_previous_page": False,
        },
    }


def test_collection_is_a_pydantic_model_and_dumps_to_json() -> None:
    collection = Collection[Widget](items=[Widget(id="1", name="widget-1")])

    assert isinstance(collection, BaseModel)
    dumped = json.loads(collection.model_dump_json())
    assert dumped == {"items": [{"id": "1", "name": "widget-1"}]}
