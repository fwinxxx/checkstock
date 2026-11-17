from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]
Destination = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
Reference = Annotated[str, StringConstraints(strip_whitespace=True, max_length=100)]
Quantity = Annotated[int, Field(strict=True, gt=0, le=1_000_000)]
Id = Annotated[int, Field(strict=True, gt=0)]


class Command(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: UUID


class Receipt(Command):
    action: Literal["receipt"]
    product_id: Id
    warehouse_id: Id
    quantity: Quantity
    reference: Reference = ""


class Transfer(Command):
    action: Literal["transfer"]
    product_id: Id
    warehouse_id: Id
    destination_id: Id
    quantity: Quantity
    reference: Reference = ""


class Shipment(Command):
    action: Literal["fbo", "reserve_fbs"]
    product_id: Id
    warehouse_id: Id
    destination: Destination
    quantity: Quantity
    reference: Reference = ""


class Transition(Command):
    action: Literal["ship_fbs", "cancel_fbs", "receive_transfer", "receive_fbo", "deliver_fbs"]
    flow_id: Id


class WarehouseCreate(Command):
    action: Literal["create_warehouse"]
    name: Name


class WarehouseRename(Command):
    action: Literal["rename_warehouse"]
    warehouse_id: Id
    name: Name


class WarehouseStatus(Command):
    action: Literal["archive_warehouse", "restore_warehouse"]
    warehouse_id: Id


AnyCommand = Annotated[
    Receipt
    | Transfer
    | Shipment
    | Transition
    | WarehouseCreate
    | WarehouseRename
    | WarehouseStatus,
    Field(discriminator="action"),
]
