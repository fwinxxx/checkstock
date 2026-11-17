"""Business expectations use the quantities from the assignment, not service internals."""

from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest


def command(client, action, **kwargs):
    return client.post(
        "/api/commands", json={"request_id": str(uuid4()), "action": action, **kwargs}
    )


def state(client):
    response = client.get("/api/state")
    assert response.status_code == 200
    result = response.json()
    assert result["audit"]["ok"], result["audit"]
    return result


def stock(client, product=1, warehouse=1):
    return next(
        s
        for s in state(client)["stocks"]
        if s["product_id"] == product and s["warehouse_id"] == warehouse
    )


def reserve(client, quantity=3, warehouse=1):
    return command(
        client,
        "reserve_fbs",
        product_id=1,
        warehouse_id=warehouse,
        quantity=quantity,
        destination="Заказ FBS-001",
    )


def test_initial_quantities_and_zero_cells(client):
    data = state(client)
    assert len(data["stocks"]) == 6
    assert data["totals"]["on_hand"] == data["totals"]["available"] == 25
    assert stock(client)["on_hand"] == 10
    assert stock(client, 1, 2)["on_hand"] == 6
    assert stock(client, 2, 1)["on_hand"] == 5
    assert stock(client, 2, 2)["on_hand"] == 0
    assert stock(client, 3, 1)["on_hand"] == 0
    assert stock(client, 3, 2)["on_hand"] == 4


def test_receipt_increases_only_selected_stock(client):
    assert command(client, "receipt", product_id=2, warehouse_id=2, quantity=7).status_code == 200
    assert stock(client, 2, 2)["on_hand"] == 7
    assert stock(client, 2, 1)["on_hand"] == 5
    assert state(client)["totals"]["on_hand"] == 32


def test_fbs_reservation_shipping_and_delivery(client):
    flow_id = reserve(client).json()["flow_id"]
    s = stock(client)
    assert (s["on_hand"], s["reserved"], s["available"]) == (10, 3, 7)
    assert command(client, "ship_fbs", flow_id=flow_id).status_code == 200
    s = stock(client)
    assert (s["on_hand"], s["reserved"], s["available"]) == (7, 0, 7)
    assert state(client)["totals"]["fbs_transit"] == 3
    command(client, "deliver_fbs", flow_id=flow_id)
    assert state(client)["totals"]["fbs_transit"] == 0
    assert state(client)["totals"]["delivered"] == 3


def test_cancel_releases_reserve_without_changing_physical_stock(client):
    flow_id = reserve(client, 4).json()["flow_id"]
    command(client, "cancel_fbs", flow_id=flow_id)
    s = stock(client)
    assert (s["on_hand"], s["reserved"], s["available"]) == (10, 0, 10)
    assert command(client, "ship_fbs", flow_id=flow_id).status_code == 409


def test_transfer_requires_receiving_to_increase_destination(client):
    flow_id = command(
        client,
        "transfer",
        product_id=1,
        warehouse_id=1,
        destination_id=2,
        quantity=4,
    ).json()["flow_id"]
    assert stock(client)["on_hand"] == 6
    assert stock(client, 1, 2)["on_hand"] == 6
    assert state(client)["totals"]["transfer_transit"] == 4
    command(client, "receive_transfer", flow_id=flow_id)
    assert stock(client, 1, 2)["on_hand"] == 10
    assert state(client)["totals"]["transfer_transit"] == 0
    assert state(client)["totals"]["on_hand"] == 25


def test_fbo_receipt_moves_stock_from_transit_to_marketplace(client):
    flow_id = command(
        client,
        "fbo",
        product_id=1,
        warehouse_id=1,
        quantity=4,
        destination="WB • Коледино",
    ).json()["flow_id"]
    assert stock(client)["on_hand"] == 6
    assert state(client)["totals"]["fbo_transit"] == 4
    command(client, "receive_fbo", flow_id=flow_id)
    assert state(client)["totals"]["fbo_transit"] == 0
    assert state(client)["totals"]["marketplace"] == 4
    assert stock(client)["on_hand"] == 6


@pytest.mark.parametrize("action", ["fbo", "reserve_fbs", "transfer"])
def test_local_shortage_does_not_spend_other_warehouse_stock(client, action):
    before = state(client)
    extra = {"destination_id": 1} if action == "transfer" else {"destination": "WB"}
    response = command(client, action, product_id=1, warehouse_id=2, quantity=8, **extra)
    assert response.status_code == 409
    detail = response.json()["error"]
    assert detail["code"] == "insufficient_stock"
    assert (detail["available_here"], detail["available_total"], detail["missing"]) == (6, 16, 2)
    assert detail["alternatives"][0]["warehouse_name"] == "Север"
    after = state(client)
    assert after["stocks"] == before["stocks"]
    assert after["events"] == before["events"]


def test_reserved_units_cannot_be_sent_by_another_flow(client):
    reserve(client, 8)
    response = command(client, "fbo", product_id=1, warehouse_id=1, quantity=3, destination="WB")
    assert response.status_code == 409
    assert stock(client)["on_hand"] == 10
    assert stock(client)["available"] == 2


def test_same_request_is_replayed_without_new_receipt(client):
    payload = {
        "request_id": str(uuid4()),
        "action": "receipt",
        "product_id": 1,
        "warehouse_id": 1,
        "quantity": 2,
    }
    first = client.post("/api/commands", json=payload)
    second = client.post("/api/commands", json=payload)
    assert first.json() == second.json()
    assert second.headers["Idempotency-Replayed"] == "true"
    assert stock(client)["on_hand"] == 12
    assert len(state(client)["events"]) == 5
    payload["quantity"] = 9
    assert client.post("/api/commands", json=payload).status_code == 409
    assert stock(client)["on_hand"] == 12


@pytest.mark.parametrize("kind,action", [("transfer", "receive_transfer"), ("fbo", "receive_fbo")])
def test_duplicate_confirmation_with_new_request_key_is_noop(client, kind, action):
    extra = {"destination_id": 2} if kind == "transfer" else {"destination": "WB"}
    flow_id = command(client, kind, product_id=1, warehouse_id=1, quantity=3, **extra).json()[
        "flow_id"
    ]
    command(client, action, flow_id=flow_id)
    before = state(client)
    assert command(client, action, flow_id=flow_id).json()["changed"] is False
    assert state(client)["stocks"] == before["stocks"]
    assert state(client)["events"] == before["events"]


def test_repeated_shipping_and_cancel_cannot_double_spend(client):
    flow_id = reserve(client).json()["flow_id"]
    command(client, "ship_fbs", flow_id=flow_id)
    assert command(client, "ship_fbs", flow_id=flow_id).json()["changed"] is False
    assert command(client, "cancel_fbs", flow_id=flow_id).status_code == 409
    assert stock(client)["on_hand"] == 7


def test_archive_preserves_stock_history_and_outstanding_reservations(client):
    flow_id = reserve(client).json()["flow_id"]
    command(client, "archive_warehouse", warehouse_id=1)
    s = stock(client)
    assert (s["on_hand"], s["reserved"], s["available"]) == (10, 3, 7)
    assert s["archived"] is True
    assert state(client)["totals"]["archived_on_hand"] == 15
    assert reserve(client).status_code == 409
    assert command(client, "receipt", product_id=1, warehouse_id=1, quantity=1).status_code == 409
    assert command(client, "ship_fbs", flow_id=flow_id).status_code == 200
    assert (
        command(
            client, "transfer", product_id=1, warehouse_id=1, destination_id=2, quantity=2
        ).status_code
        == 200
    )
    assert stock(client)["on_hand"] == 5
    command(client, "restore_warehouse", warehouse_id=1)
    assert reserve(client, 1).status_code == 200


def test_transfer_can_arrive_at_warehouse_archived_after_dispatch(client):
    flow_id = command(
        client, "transfer", product_id=1, warehouse_id=1, destination_id=2, quantity=2
    ).json()["flow_id"]
    command(client, "archive_warehouse", warehouse_id=2)
    assert command(client, "receive_transfer", flow_id=flow_id).status_code == 200
    assert stock(client, 1, 2)["on_hand"] == 8
    assert (
        command(
            client, "transfer", product_id=1, warehouse_id=1, destination_id=2, quantity=1
        ).status_code
        == 409
    )


def test_rename_preserves_historical_route_names(client):
    command(client, "rename_warehouse", warehouse_id=1, name="Северный")
    assert state(client)["warehouses"][0]["name"] == "Северный"
    receipts = [e for e in state(client)["events"] if e["action"] == "receipt"]
    assert any(e["destination"] == "Север" for e in receipts)
    assert command(client, "create_warehouse", name=" северный ").status_code == 409
    new = command(client, "create_warehouse", name="Восток").json()["warehouse_id"]
    assert stock(client, 1, new)["on_hand"] == 0


@pytest.mark.parametrize("quantity", [0, -1, 1.5, True, "3", 1_000_001])
def test_invalid_quantities_cannot_change_stock(client, quantity):
    assert (
        command(client, "receipt", product_id=1, warehouse_id=1, quantity=quantity).status_code
        == 422
    )
    assert stock(client)["on_hand"] == 10


def test_invalid_routes_and_missing_entities(client):
    assert (
        command(
            client, "transfer", product_id=1, warehouse_id=1, destination_id=1, quantity=1
        ).status_code
        == 422
    )
    assert command(client, "receipt", product_id=999, warehouse_id=1, quantity=1).status_code == 404
    assert command(client, "receipt", product_id=1, warehouse_id=999, quantity=1).status_code == 404
    assert command(client, "receive_fbo", flow_id=999).status_code == 404
    flow_id = reserve(client).json()["flow_id"]
    assert command(client, "receive_fbo", flow_id=flow_id).status_code == 409


def test_competing_reservations_cannot_overbook(client):
    with ThreadPoolExecutor(max_workers=2) as executor:
        responses = list(executor.map(lambda _: reserve(client, 7), range(2)))
    assert sorted(r.status_code for r in responses) == [200, 409]
    assert stock(client)["reserved"] == 7
    assert stock(client)["available"] == 3


def test_concurrent_duplicate_receipts_are_applied_once(client):
    payload = {
        "request_id": str(uuid4()),
        "action": "receipt",
        "product_id": 1,
        "warehouse_id": 1,
        "quantity": 2,
    }
    with ThreadPoolExecutor(max_workers=4) as executor:
        responses = list(
            executor.map(lambda _: client.post("/api/commands", json=payload), range(4))
        )
    assert [r.status_code for r in responses] == [200] * 4
    assert stock(client)["on_hand"] == 12


def test_seed_is_repeatable_after_warehouse_changes(client):
    from app.db import SessionLocal
    from app.seed import seed

    command(client, "rename_warehouse", warehouse_id=1, name="Северный")
    command(client, "archive_warehouse", warehouse_id=2)
    command(client, "receipt", product_id=1, warehouse_id=1, quantity=2)
    before = state(client)
    with SessionLocal.begin() as session:
        seed(session)
    after = state(client)
    assert after["stocks"] == before["stocks"]
    assert after["events"] == before["events"]
    assert after["warehouses"] == before["warehouses"]


def test_duplicate_warehouse_changes_do_not_add_history(client):
    before = state(client)
    assert (
        command(client, "rename_warehouse", warehouse_id=1, name="Север").json()["changed"] is False
    )
    assert command(client, "restore_warehouse", warehouse_id=1).json()["changed"] is False
    assert state(client)["events"] == before["events"]
    command(client, "archive_warehouse", warehouse_id=1)
    assert command(client, "archive_warehouse", warehouse_id=1).json()["changed"] is False


def test_database_constraints_reject_negative_or_over_reserved_stock(client):
    from sqlalchemy import text
    from sqlalchemy.exc import IntegrityError

    from app.db import SessionLocal

    for assignment in ("on_hand = -1", "reserved = 11"):
        with pytest.raises(IntegrityError), SessionLocal.begin() as session:
            session.execute(
                text(f"UPDATE stocks SET {assignment} WHERE warehouse_id=1 AND product_id=1")
            )
    assert stock(client)["on_hand"] == 10
    assert stock(client)["reserved"] == 0


def test_journal_write_failure_rolls_back_stock_and_idempotency_record(client):
    from sqlalchemy import select, text
    from sqlalchemy.exc import IntegrityError

    from app.db import SessionLocal
    from app.models import CommandRecord

    before = state(client)
    request_id = uuid4()
    with SessionLocal.begin() as session:
        session.execute(
            text("ALTER TABLE events ADD CONSTRAINT test_reject_13 CHECK (quantity <> 13)")
        )
    try:
        with pytest.raises(IntegrityError):
            client.post(
                "/api/commands",
                json={
                    "request_id": str(request_id),
                    "action": "receipt",
                    "product_id": 1,
                    "warehouse_id": 1,
                    "quantity": 13,
                },
            )
        assert state(client)["stocks"] == before["stocks"]
        assert state(client)["events"] == before["events"]
        with SessionLocal() as session:
            assert (
                session.scalar(select(CommandRecord).where(CommandRecord.id == request_id)) is None
            )
    finally:
        with SessionLocal.begin() as session:
            session.execute(text("ALTER TABLE events DROP CONSTRAINT test_reject_13"))


def test_reconciliation_detects_stock_drift(client):
    from sqlalchemy import text

    from app.db import SessionLocal

    with SessionLocal.begin() as session:
        session.execute(text("UPDATE stocks SET on_hand=11 WHERE warehouse_id=1 AND product_id=1"))
    audit = client.get("/api/state").json()["audit"]
    assert audit["ok"] is False
    assert len(audit["errors"]) == 2  # Journal mismatch + SKU conservation mismatch.


def test_reconciliation_detects_reserve_drift(client):
    from sqlalchemy import text

    from app.db import SessionLocal

    with SessionLocal.begin() as session:
        session.execute(text("UPDATE stocks SET reserved=1 WHERE warehouse_id=1 AND product_id=1"))
    audit = client.get("/api/state").json()["audit"]
    assert audit["ok"] is False
    assert len(audit["errors"]) == 2  # Journal mismatch + open-order mismatch.


def test_health_and_openapi_contract(client):
    assert client.get("/health").json() == {"status": "ok"}
    schema = client.get("/openapi.json").json()
    assert "/api/commands" in schema["paths"]
    assert "/api/state" in schema["paths"]
