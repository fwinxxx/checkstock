from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Event, Flow, Product, Stock, Warehouse
from app.service import lock_shop


def snapshot(session: Session) -> dict:
    """Shared shop lock keeps all SELECTs consistent with atomic commands."""
    shop = lock_shop(session, read=True)
    products = session.scalars(select(Product).order_by(Product.id)).all()
    warehouses = session.scalars(select(Warehouse).order_by(Warehouse.id)).all()
    stocks = session.scalars(select(Stock)).all()
    flows = session.scalars(select(Flow).order_by(Flow.id.desc())).all()
    events = session.scalars(select(Event).order_by(Event.id.desc())).all()
    wh_by_id = {w.id: w for w in warehouses}
    stock_by_pair = {(s.warehouse_id, s.product_id): s for s in stocks}
    totals = dict.fromkeys(
        [
            "on_hand",
            "reserved",
            "available",
            "active_available",
            "archived_on_hand",
            "transfer_transit",
            "fbo_transit",
            "fbs_transit",
            "marketplace",
            "delivered",
        ],
        0,
    )
    cells = []
    for p in products:
        for w in warehouses:
            s = stock_by_pair.get((w.id, p.id))
            on_hand, reserved = (s.on_hand, s.reserved) if s else (0, 0)
            cells.append(
                {
                    "product_id": p.id,
                    "warehouse_id": w.id,
                    "archived": w.archived,
                    "on_hand": on_hand,
                    "reserved": reserved,
                    "available": on_hand - reserved,
                }
            )
            totals["on_hand"] += on_hand
            totals["reserved"] += reserved
            totals["available"] += on_hand - reserved
            totals["active_available"] += 0 if w.archived else on_hand - reserved
            totals["archived_on_hand"] += on_hand if w.archived else 0
    product_totals = {
        p.id: dict.fromkeys(
            [
                "on_hand",
                "reserved",
                "available",
                "transfer_transit",
                "fbo_transit",
                "fbs_transit",
                "marketplace",
                "delivered",
            ],
            0,
        )
        for p in products
    }
    for cell in cells:
        for key in ("on_hand", "reserved", "available"):
            product_totals[cell["product_id"]][key] += cell[key]
    flow_rows = []
    reserves = defaultdict(int)
    for flow in flows:
        key = None
        if flow.status == "in_transit":
            key = f"{flow.kind}_transit"
        elif flow.kind == "fbo" and flow.status == "received":
            key = "marketplace"
        elif flow.kind == "fbs" and flow.status == "delivered":
            key = "delivered"
        if key:
            totals[key] += flow.quantity
            product_totals[flow.product_id][key] += flow.quantity
        if flow.status == "reserved":
            reserves[(flow.source_id, flow.product_id)] += flow.quantity
        flow_rows.append(
            {
                "id": flow.id,
                "kind": flow.kind,
                "status": flow.status,
                "product_id": flow.product_id,
                "quantity": flow.quantity,
                "source_id": flow.source_id,
                "source": wh_by_id[flow.source_id].name,
                "destination_id": flow.destination_id,
                "destination": wh_by_id[flow.destination_id].name
                if flow.destination_id
                else flow.destination,
                "reference": flow.reference,
                "created_at": flow.created_at.isoformat(),
            }
        )

    # Reconcile projection vs journal, reserves vs orders, and conservation per SKU.
    ledger = defaultdict(lambda: [0, 0])
    receipts = defaultdict(int)
    for event in events:
        ledger[(event.warehouse_id, event.product_id)][0] += event.on_hand_delta
        ledger[(event.warehouse_id, event.product_id)][1] += event.reserved_delta
        if event.action == "receipt":
            receipts[event.product_id] += event.quantity
    errors = []
    for cell in cells:
        pair = (cell["warehouse_id"], cell["product_id"])
        if ledger[pair] != [cell["on_hand"], cell["reserved"]]:
            errors.append(f"Журнал не совпадает с остатком: SKU #{pair[1]}, ФФ #{pair[0]}")
        if reserves[pair] != cell["reserved"]:
            errors.append(f"Резерв не совпадает с заказами: SKU #{pair[1]}, ФФ #{pair[0]}")
    for product in products:
        t = product_totals[product.id]
        accounted = sum(
            t[k]
            for k in (
                "on_hand",
                "transfer_transit",
                "fbo_transit",
                "fbs_transit",
                "marketplace",
                "delivered",
            )
        )
        if accounted != receipts[product.id]:
            errors.append(
                f"Нарушен баланс {product.sku}: приход {receipts[product.id]}, учтено {accounted}"
            )
    return {
        "shop": {"id": shop.id, "name": shop.name},
        "products": [
            {"id": p.id, "sku": p.sku, "name": p.name, **product_totals[p.id]} for p in products
        ],
        "warehouses": [{"id": w.id, "name": w.name, "archived": w.archived} for w in warehouses],
        "stocks": cells,
        "flows": flow_rows,
        "totals": totals,
        "events": [
            {
                "id": e.id,
                "action": e.action,
                "product_id": e.product_id,
                "quantity": e.quantity,
                "flow_id": e.flow_id,
                "warehouse_id": e.warehouse_id,
                "on_hand_delta": e.on_hand_delta,
                "reserved_delta": e.reserved_delta,
                "source": e.source,
                "destination": e.destination,
                "note": e.note,
                "created_at": e.created_at.isoformat(),
            }
            for e in events
        ],
        "audit": {"ok": not errors, "errors": errors, "received_total": sum(receipts.values())},
    }
