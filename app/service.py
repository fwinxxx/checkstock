"""Atomic inventory commands. Every writer takes the same shop lock first."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import CommandRecord, Event, Flow, Product, Shop, Stock, Warehouse
from app.schemas import (
    Command,
    Receipt,
    Shipment,
    Transfer,
    Transition,
    WarehouseCreate,
    WarehouseRename,
    WarehouseStatus,
)


class DomainError(Exception):
    def __init__(self, code: str, message: str, status: int = 409, **details):
        self.status = status
        self.error = {"code": code, "message": message, **details}


def lock_shop(session: Session, *, read: bool = False) -> Shop:
    shop = session.scalar(select(Shop).where(Shop.id == 1).with_for_update(read=read))
    if shop is None:
        raise DomainError("not_initialized", "Загрузите тестовые данные: python -m app.seed", 503)
    return shop


def entity(session: Session, model, entity_id: int):
    result = session.get(model, entity_id)
    if result is None:
        raise DomainError("not_found", "Объект не найден. Обновите данные.", 404)
    return result


def active(warehouse: Warehouse):
    if warehouse.archived:
        raise DomainError(
            "warehouse_archived",
            f"ФФ «{warehouse.name}» в архиве. Для новых операций восстановите склад.",
        )


def get_stock(session: Session, warehouse_id: int, product_id: int) -> Stock:
    stock = session.scalar(
        select(Stock).where(Stock.warehouse_id == warehouse_id, Stock.product_id == product_id)
    )
    if stock is None:
        stock = Stock(warehouse_id=warehouse_id, product_id=product_id, on_hand=0, reserved=0)
        session.add(stock)
        session.flush()
    return stock


def require_available(session: Session, stock: Stock, quantity: int):
    available = stock.on_hand - stock.reserved
    if available >= quantity:
        return
    rows = session.execute(
        select(Stock, Warehouse)
        .join(Warehouse, Warehouse.id == Stock.warehouse_id)
        .where(Stock.product_id == stock.product_id)
        .order_by(Warehouse.id)
    ).all()
    alternatives = [
        {
            "warehouse_id": w.id,
            "warehouse_name": w.name,
            "available": s.on_hand - s.reserved,
            "archived": w.archived,
        }
        for s, w in rows
        if w.id != stock.warehouse_id and s.on_hand > s.reserved
    ]
    total = sum(s.on_hand - s.reserved for s, _ in rows)
    raise DomainError(
        "insufficient_stock",
        f"На выбранном ФФ доступно {available} из {quantity} ед. "
        "Сначала переместите и примите недостающий товар или выберите другой ФФ.",
        available_here=available,
        available_total=total,
        missing=quantity - available,
        alternatives=alternatives,
    )


def record_event(
    session: Session,
    action: str,
    *,
    stock: Stock | None = None,
    physical: int = 0,
    reserved: int = 0,
    **values,
) -> Event:
    if stock is not None:
        stock.on_hand += physical
        stock.reserved += reserved
        values.update(warehouse_id=stock.warehouse_id, product_id=stock.product_id)
    event = Event(action=action, on_hand_delta=physical, reserved_delta=reserved, **values)
    session.add(event)
    session.flush()
    return event


def result(event: Event | None, **values) -> dict:
    return {"changed": event is not None, "event_id": event.id if event else None, **values}


def change_warehouse(session: Session, command) -> dict:
    if isinstance(command, (WarehouseCreate, WarehouseRename)):
        duplicate = session.scalar(
            select(Warehouse).where(Warehouse.name_key == command.name.casefold())
        )
        own_id = getattr(command, "warehouse_id", None)
        if duplicate is not None and duplicate.id != own_id:
            raise DomainError(
                "duplicate_name", "Склад с таким названием уже существует, в том числе в архиве."
            )
    if isinstance(command, WarehouseCreate):
        warehouse = Warehouse(name=command.name, name_key=command.name.casefold())
        session.add(warehouse)
        session.flush()
        event = record_event(
            session, command.action, warehouse_id=warehouse.id, destination=warehouse.name
        )
    else:
        warehouse = entity(session, Warehouse, command.warehouse_id)
        old_name = warehouse.name
        if isinstance(command, WarehouseRename):
            if warehouse.name == command.name:
                return result(None, warehouse_id=warehouse.id)
            warehouse.name = command.name
            warehouse.name_key = command.name.casefold()
        else:
            archived = command.action == "archive_warehouse"
            if warehouse.archived == archived:
                return result(None, warehouse_id=warehouse.id)
            warehouse.archived = archived
        event = record_event(
            session,
            command.action,
            warehouse_id=warehouse.id,
            source=old_name,
            destination=warehouse.name,
        )
    return result(event, warehouse_id=warehouse.id)


def create_movement(session: Session, command: Receipt | Transfer | Shipment) -> dict:
    entity(session, Product, command.product_id)
    source = entity(session, Warehouse, command.warehouse_id)
    # Archived FF may release its remaining free stock via transfer to an active FF.
    if not isinstance(command, Transfer):
        active(source)
    stock = get_stock(session, source.id, command.product_id)
    if isinstance(command, Receipt):
        event = record_event(
            session,
            "receipt",
            stock=stock,
            physical=command.quantity,
            quantity=command.quantity,
            source="Поставщик",
            destination=source.name,
            note=command.reference,
        )
        return result(event)

    destination_id = None
    if isinstance(command, Transfer):
        if source.id == command.destination_id:
            raise DomainError("same_warehouse", "Выберите другой склад назначения.", 422)
        target = entity(session, Warehouse, command.destination_id)
        active(target)
        destination, destination_id, kind = target.name, target.id, "transfer"
    else:
        destination = command.destination
        kind = "fbo" if command.action == "fbo" else "fbs"
    require_available(session, stock, command.quantity)
    flow = Flow(
        kind=kind,
        status="reserved" if kind == "fbs" else "in_transit",
        product_id=command.product_id,
        quantity=command.quantity,
        source_id=source.id,
        destination_id=destination_id,
        destination=destination,
        reference=command.reference,
    )
    session.add(flow)
    session.flush()
    event = record_event(
        session,
        command.action,
        stock=stock,
        physical=0 if kind == "fbs" else -command.quantity,
        reserved=command.quantity if kind == "fbs" else 0,
        quantity=command.quantity,
        flow_id=flow.id,
        source=source.name,
        destination=destination,
        note=command.reference,
    )
    return result(event, flow_id=flow.id)


# action -> (required kind, starting state, target state, states already beyond this action)
TRANSITIONS = {
    "ship_fbs": ("fbs", "reserved", "in_transit", {"in_transit", "delivered"}),
    "cancel_fbs": ("fbs", "reserved", "cancelled", {"cancelled"}),
    "deliver_fbs": ("fbs", "in_transit", "delivered", {"delivered"}),
    "receive_transfer": ("transfer", "in_transit", "received", {"received"}),
    "receive_fbo": ("fbo", "in_transit", "received", {"received"}),
}


def transition(session: Session, command: Transition) -> dict:
    flow = entity(session, Flow, command.flow_id)
    kind, expected, target_status, completed = TRANSITIONS[command.action]
    if flow.kind != kind:
        raise DomainError("wrong_flow_type", "Это действие не подходит для данного вида отправки.")
    if flow.status in completed:
        return result(None, flow_id=flow.id)
    if flow.status != expected:
        raise DomainError("invalid_transition", "Отправка уже изменилась. Обновите данные.")
    source = entity(session, Warehouse, flow.source_id)
    destination = (
        entity(session, Warehouse, flow.destination_id).name
        if flow.destination_id is not None
        else flow.destination
    )
    stock, physical, reserved = None, 0, 0
    if command.action in {"ship_fbs", "cancel_fbs"}:
        stock = get_stock(session, flow.source_id, flow.product_id)
        reserved = -flow.quantity
        physical = -flow.quantity if command.action == "ship_fbs" else 0
    elif command.action == "receive_transfer":
        stock = get_stock(session, flow.destination_id, flow.product_id)
        physical = flow.quantity
    flow.status = target_status
    event = record_event(
        session,
        command.action,
        stock=stock,
        physical=physical,
        reserved=reserved,
        product_id=flow.product_id,
        quantity=flow.quantity,
        flow_id=flow.id,
        source=source.name,
        destination=destination,
        note=flow.reference,
    )
    return result(event, flow_id=flow.id)


def execute(session: Session, command: Command) -> tuple[dict, bool]:
    """Caller owns the transaction; successful response is sent only after COMMIT."""
    lock_shop(session)
    payload = command.model_dump(mode="json", exclude={"request_id"})
    previous = session.get(CommandRecord, command.request_id)
    if previous is not None:
        if previous.payload != payload:
            raise DomainError(
                "idempotency_conflict", "Этот request_id уже использован с другими данными."
            )
        return previous.response, True
    if isinstance(command, (WarehouseCreate, WarehouseRename, WarehouseStatus)):
        response = change_warehouse(session, command)
    elif isinstance(command, Transition):
        response = transition(session, command)
    else:
        response = create_movement(session, command)
    session.add(CommandRecord(id=command.request_id, payload=payload, response=response))
    session.flush()
    return response, False
