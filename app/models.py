from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class Shop(Base):
    __tablename__ = "shops"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))


class Product(Base):
    __tablename__ = "products"
    id: Mapped[int] = mapped_column(primary_key=True)
    sku: Mapped[str] = mapped_column(String(50), unique=True)
    name: Mapped[str] = mapped_column(String(100))


class Warehouse(Base):
    __tablename__ = "warehouses"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(80))
    name_key: Mapped[str] = mapped_column(String(160), unique=True)
    archived: Mapped[bool] = mapped_column(default=False)


class Stock(Base):
    __tablename__ = "stocks"
    __table_args__ = (
        UniqueConstraint("warehouse_id", "product_id"),
        CheckConstraint("on_hand >= 0", name="stock_nonnegative"),
        CheckConstraint("reserved >= 0 AND reserved <= on_hand", name="valid_reserve"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    warehouse_id: Mapped[int] = mapped_column(ForeignKey("warehouses.id"))
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    on_hand: Mapped[int] = mapped_column(Integer, default=0)
    reserved: Mapped[int] = mapped_column(Integer, default=0)


class Flow(Base):
    __tablename__ = "flows"
    __table_args__ = (
        CheckConstraint("quantity > 0", name="flow_positive"),
        CheckConstraint("kind IN ('transfer', 'fbo', 'fbs')", name="flow_kind"),
        CheckConstraint(
            "(kind = 'transfer' AND destination_id IS NOT NULL "
            "AND destination_id <> source_id AND status IN ('in_transit', 'received')) OR "
            "(kind = 'fbo' AND destination_id IS NULL AND status IN ('in_transit', 'received')) OR "
            "(kind = 'fbs' AND destination_id IS NULL "
            "AND status IN ('reserved', 'in_transit', 'delivered', 'cancelled'))",
            name="flow_shape",
        ),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(20))
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    quantity: Mapped[int]
    source_id: Mapped[int] = mapped_column(ForeignKey("warehouses.id"))
    destination_id: Mapped[int | None] = mapped_column(ForeignKey("warehouses.id"))
    destination: Mapped[str] = mapped_column(String(120))
    reference: Mapped[str] = mapped_column(String(100), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Event(Base):
    """Append-only journal. Names capture the route at the moment of the operation."""

    __tablename__ = "events"
    id: Mapped[int] = mapped_column(primary_key=True)
    action: Mapped[str] = mapped_column(String(30))
    product_id: Mapped[int | None] = mapped_column(ForeignKey("products.id"))
    quantity: Mapped[int] = mapped_column(default=0)
    flow_id: Mapped[int | None] = mapped_column(ForeignKey("flows.id"))
    warehouse_id: Mapped[int | None] = mapped_column(ForeignKey("warehouses.id"))
    on_hand_delta: Mapped[int] = mapped_column(default=0)
    reserved_delta: Mapped[int] = mapped_column(default=0)
    source: Mapped[str] = mapped_column(String(120), default="")
    destination: Mapped[str] = mapped_column(String(120), default="")
    note: Mapped[str] = mapped_column(String(240), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class CommandRecord(Base):
    __tablename__ = "commands"
    id: Mapped[UUID] = mapped_column(primary_key=True)
    payload: Mapped[dict] = mapped_column(JSON)
    response: Mapped[dict] = mapped_column(JSON)
