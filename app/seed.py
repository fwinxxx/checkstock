"""Repeatable demo seed: reference data and all four receipts are one transaction."""

from uuid import NAMESPACE_URL, uuid5

from sqlalchemy import select, text

from app.db import SessionLocal
from app.models import Product, Shop, Warehouse
from app.schemas import Receipt
from app.service import execute


def seed(session):
    session.execute(text("SELECT pg_advisory_xact_lock(740032001)"))
    if session.get(Shop, 1) is None:
        session.add(Shop(id=1, name="Ракета · Товары для дома"))
        session.add_all(
            [
                Product(sku=sku, name=name)
                for sku, name in [
                    ("SKU-101", "Органайзер"),
                    ("SKU-102", "Контейнер"),
                    ("SKU-103", "Корзина"),
                ]
            ]
        )
        session.add_all(
            [Warehouse(name=name, name_key=name.casefold()) for name in ("Север", "Юг")]
        )
        session.flush()
    products = session.scalars(select(Product).order_by(Product.id)).all()
    warehouses = session.scalars(select(Warehouse).order_by(Warehouse.id)).all()
    for p, w, quantity in ((0, 0, 10), (0, 1, 6), (1, 0, 5), (2, 1, 4)):
        execute(
            session,
            Receipt(
                request_id=uuid5(NAMESPACE_URL, f"checkstock-demo-receipt-{p}-{w}"),
                action="receipt",
                product_id=products[p].id,
                warehouse_id=warehouses[w].id,
                quantity=quantity,
                reference="Тестовый приход из ТЗ",
            ),
        )


if __name__ == "__main__":
    with SessionLocal.begin() as session:
        seed(session)
    print("Demo data ready (repeated runs do not duplicate receipts).")
