import json
from typing import Annotated, Literal, TypeVar

from fastapi import Query
from pydantic import BaseModel, field_validator

T = TypeVar("T")


class OrderItem(BaseModel):
    column: str
    dir: Literal["asc", "desc"] = "asc"


class ListQueryDTO(BaseModel):
    start: int = 0
    length: int = 10
    search: str = ""
    order: Annotated[str, Query(description='JSON string: "[{"column": "id", "dir": "asc"}]"')] = (
        '"[{"column": "id", "dir": "asc"}]"'
    )
    draw: int = 1

    @field_validator("order", mode="before")
    @classmethod
    def parse_order(_, v):
        if isinstance(v, str):
            try:
                json.loads(v[1:-1])
            except Exception:
                raise ValueError("Invalid JSON string for 'order'")
        return v

    @property
    def order_items(self) -> list[OrderItem]:
        try:
            orders = json.loads(self.order[1:-1])
        except Exception:
            raise ValueError("Invalid JSON string for 'order'")

        order_items_list = []

        if not isinstance(orders, list):
            raise ValueError("Invalid order fields (Not list)")

        for order in orders:
            try:
                order_items_list.append(OrderItem(**order))
            except Exception as e:
                raise ValueError(f"Invalid order item fields: {e}")

        return order_items_list

    @property
    def sort_columns(self) -> list[str]:
        return [item.column for item in self.order_items]

    @property
    def is_sort_ascendings(self) -> list[bool]:
        return [item.dir == "asc" for item in self.order_items]

    @property
    def page(self) -> int:
        return (self.start // self.length) + 1 if self.length else 1

    @property
    def page_size(self) -> int:
        return self.length


class ListDTO[T](BaseModel):
    draw: int
    records_total: int
    records_filtered: int
    data: list[T]
