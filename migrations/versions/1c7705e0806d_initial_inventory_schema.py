"""initial inventory schema

Revision ID: 1c7705e0806d
Revises:
Create Date: 2026-11-15 07:22:58.460122

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "1c7705e0806d"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "commands",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("response", sa.JSON(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "products",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("sku", sa.String(length=50), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("sku"),
    )
    op.create_table(
        "shops",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "warehouses",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("name_key", sa.String(length=160), nullable=False),
        sa.Column("archived", sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name_key"),
    )
    op.create_table(
        "flows",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("product_id", sa.Integer(), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("source_id", sa.Integer(), nullable=False),
        sa.Column("destination_id", sa.Integer(), nullable=True),
        sa.Column("destination", sa.String(length=120), nullable=False),
        sa.Column("reference", sa.String(length=100), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "(kind = 'transfer' AND destination_id IS NOT NULL AND destination_id <> source_id "
            "AND status IN ('in_transit', 'received')) OR "
            "(kind = 'fbo' AND destination_id IS NULL AND status IN ('in_transit', 'received')) OR "
            "(kind = 'fbs' AND destination_id IS NULL "
            "AND status IN ('reserved', 'in_transit', 'delivered', 'cancelled'))",
            name="flow_shape",
        ),
        sa.CheckConstraint("kind IN ('transfer', 'fbo', 'fbs')", name="flow_kind"),
        sa.CheckConstraint("quantity > 0", name="flow_positive"),
        sa.ForeignKeyConstraint(
            ["destination_id"],
            ["warehouses.id"],
        ),
        sa.ForeignKeyConstraint(
            ["product_id"],
            ["products.id"],
        ),
        sa.ForeignKeyConstraint(
            ["source_id"],
            ["warehouses.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "stocks",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("warehouse_id", sa.Integer(), nullable=False),
        sa.Column("product_id", sa.Integer(), nullable=False),
        sa.Column("on_hand", sa.Integer(), nullable=False),
        sa.Column("reserved", sa.Integer(), nullable=False),
        sa.CheckConstraint("on_hand >= 0", name="stock_nonnegative"),
        sa.CheckConstraint("reserved >= 0 AND reserved <= on_hand", name="valid_reserve"),
        sa.ForeignKeyConstraint(
            ["product_id"],
            ["products.id"],
        ),
        sa.ForeignKeyConstraint(
            ["warehouse_id"],
            ["warehouses.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("warehouse_id", "product_id"),
    )
    op.create_table(
        "events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("action", sa.String(length=30), nullable=False),
        sa.Column("product_id", sa.Integer(), nullable=True),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("flow_id", sa.Integer(), nullable=True),
        sa.Column("warehouse_id", sa.Integer(), nullable=True),
        sa.Column("on_hand_delta", sa.Integer(), nullable=False),
        sa.Column("reserved_delta", sa.Integer(), nullable=False),
        sa.Column("source", sa.String(length=120), nullable=False),
        sa.Column("destination", sa.String(length=120), nullable=False),
        sa.Column("note", sa.String(length=240), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["flow_id"],
            ["flows.id"],
        ),
        sa.ForeignKeyConstraint(
            ["product_id"],
            ["products.id"],
        ),
        sa.ForeignKeyConstraint(
            ["warehouse_id"],
            ["warehouses.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("events")
    op.drop_table("stocks")
    op.drop_table("flows")
    op.drop_table("warehouses")
    op.drop_table("shops")
    op.drop_table("products")
    op.drop_table("commands")
