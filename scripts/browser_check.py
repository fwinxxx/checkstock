"""Real-browser acceptance test. Resets only the explicitly selected *_test database."""

import json
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

from alembic import command
from alembic.config import Config
from playwright.sync_api import expect, sync_playwright
from sqlalchemy.engine import make_url

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
URL = os.environ.get("TEST_DATABASE_URL", "")
if not URL or not (make_url(URL).database or "").endswith("_test"):
    raise SystemExit("Set TEST_DATABASE_URL to a separate database whose name ends in _test")
os.environ["DATABASE_URL"] = URL

from sqlalchemy import text  # noqa: E402

from app.db import SessionLocal  # noqa: E402
from app.seed import seed  # noqa: E402

command.upgrade(Config(str(ROOT / "alembic.ini")), "head")
with SessionLocal.begin() as session:
    session.execute(
        text(
            "TRUNCATE commands, events, flows, stocks, warehouses, products, shops "
            "RESTART IDENTITY CASCADE"
        )
    )
    seed(session)

port = os.environ.get("BROWSER_TEST_PORT", "8011")
base = f"http://127.0.0.1:{port}"
output = ROOT / "output" / "screenshots"
output.mkdir(parents=True, exist_ok=True)
server = subprocess.Popen(
    [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", port],
    cwd=ROOT,
    stdout=subprocess.DEVNULL,
    stderr=subprocess.DEVNULL,
)
try:
    for _ in range(100):
        if server.poll() is not None:
            raise RuntimeError(
                "Browser test server failed to start; choose an unused BROWSER_TEST_PORT"
            )
        try:
            urllib.request.urlopen(base + "/health", timeout=1)
            break
        except OSError:
            time.sleep(0.1)
    else:
        raise RuntimeError("Browser test server did not become ready")
    with sync_playwright() as p:
        options = {"headless": True}
        if os.environ.get("PLAYWRIGHT_CHANNEL"):
            options["channel"] = os.environ["PLAYWRIGHT_CHANNEL"]
        browser = p.chromium.launch(**options)
        context = browser.new_context(viewport={"width": 1440, "height": 1000}, locale="ru-RU")
        page = context.new_page()
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        # Unknown hashes, including Object.prototype keys, must fall back to stock.
        page.goto(base + "/#__proto__")
        expect(page.locator('[data-stat="physical"] .stat-value')).to_contain_text("25")
        page.goto(base)
        expect(page.locator("[data-sku]")).to_have_count(3)
        # Row actions retain the selected SKU and support keyboard dismissal.
        row_menu = page.get_by_role("button", name="Операции с SKU-102", exact=True)
        row_menu.click()
        page.get_by_role("menuitem", name="Приход товара", exact=True).click()
        expect(page.locator("#f-product_id")).to_have_value("2")
        page.locator("#cancel-dialog").click()
        expect(row_menu).to_be_focused()
        row_menu.click()
        page.keyboard.press("Escape")
        expect(page.locator("#operation-menu")).not_to_be_visible()
        expect(row_menu).to_be_focused()
        page.locator("#new-operation").click()
        page.locator("#new-operation").click()
        expect(page.locator("#operation-menu")).not_to_be_visible()
        page.locator("#new-operation").click()
        page.locator("#page-title").click()
        expect(page.locator("#operation-menu")).not_to_be_visible()
        expect(page.locator("#new-operation")).to_have_attribute("aria-expanded", "false")
        page.goto(base + "#flows")
        page.locator(".skip-link").focus()
        page.keyboard.press("Enter")
        expect(page).to_have_url(base + "/#flows")
        expect(page.locator("#main-content")).to_be_focused()
        page.goto(base + "#stock")
        page.screenshot(
            path=str(output / "overview-desktop.png"), full_page=True, animations="disabled"
        )

        def create(action, quantity=1, source="1", product="1", destination=None):
            page.locator("#new-operation").click()
            page.locator(f'[data-create="{action}"]').first.click()
            page.locator("#f-product_id").select_option(product)
            page.locator("#f-warehouse_id").select_option(source)
            page.locator("#f-quantity").fill(str(quantity))
            if destination is not None:
                field = "#f-destination_id" if action == "transfer" else "#f-destination"
                if action == "transfer":
                    page.locator(field).select_option(destination)
                else:
                    page.locator(field).fill(destination)

        def submit():
            page.locator("#submit-action").click()
            expect(page.locator("#action-dialog")).not_to_be_visible()
            expect(page.locator("#refresh")).to_be_enabled()

        def read():
            result = context.request.get(base + "/api/state").json()
            assert result["audit"]["ok"], result["audit"]
            return result

        def transition(action, flow):
            page.goto(base + "#flows")
            page.locator('[data-flow-filter="all"]').click()
            page.locator(f'[data-flow="{flow}"] [data-transition="{action}"]').click()
            submit()

        create("reserve_fbs", 3, destination="FBS-001")
        submit()
        expect(page.locator("#toast")).to_contain_text("Органайзер: 3 ед. в резерве")
        expect(page.locator('[data-stat="reserved"] .stat-value')).to_contain_text("3")
        fbs_id = read()["flows"][0]["id"]

        create("reserve_fbs", 1, source="2", destination="FBS-002")
        submit()
        cancel_id = read()["flows"][0]["id"]
        transition("cancel_fbs", cancel_id)
        assert read()["totals"]["reserved"] == 3

        page.goto(base + "#stock")
        create("fbo", 8, source="2", destination="WB · Коледино")
        page.locator("#submit-action").click()
        expect(page.locator("#form-error")).to_contain_text("Не хватает 2 ед.")
        expect(page.locator("#form-error")).to_contain_text("«Юг» доступно 6")
        expect(page.locator("#form-error")).to_contain_text("Север — 7")
        page.screenshot(path=str(output / "local-shortage.png"), animations="disabled")
        page.locator("#cancel-dialog").click()
        assert read()["totals"]["on_hand"] == 25

        create("transfer", 2, destination="2")
        submit()
        transfer_id = read()["flows"][0]["id"]
        assert read()["totals"]["transfer_transit"] == 2
        transition("receive_transfer", transfer_id)
        page.goto(base + "#stock")
        create("fbo", 8, source="2", destination="WB · Коледино")
        submit()
        fbo_id = read()["flows"][0]["id"]
        transition("ship_fbs", fbs_id)
        assert read()["totals"]["fbs_transit"] == 3
        page.screenshot(
            path=str(output / "shipments-desktop.png"), full_page=True, animations="disabled"
        )
        transition("receive_fbo", fbo_id)
        assert read()["totals"]["marketplace"] == 8

        page.goto(base + "#warehouses")
        page.locator('[data-warehouse="1"] [data-warehouse-action="archive_warehouse"]').click()
        submit()
        expect(page.locator('[data-warehouse="1"]')).to_contain_text("В архиве")
        assert read()["totals"]["archived_on_hand"] == 10
        page.screenshot(
            path=str(output / "archived-warehouse.png"), full_page=True, animations="disabled"
        )
        transition("deliver_fbs", fbs_id)
        assert read()["totals"]["delivered"] == 3

        page.goto(base + "#warehouses")
        page.locator('[data-create="create_warehouse"]').click()
        page.locator("#f-name").fill("Восток <тест>")
        submit()
        expect(page.locator('[data-warehouse="3"]')).to_contain_text("Восток <тест>")
        assert page.locator("тест").count() == 0
        page.locator('[data-warehouse="3"] [data-warehouse-action="rename_warehouse"]').click()
        page.locator("#f-name").fill("Восточный")
        submit()
        expect(page.locator('[data-warehouse="3"]')).to_contain_text("Восточный")
        create("receipt", 2, source="3", product="3")
        submit()
        assert read()["audit"]["received_total"] == 27

        # Server commits but the browser loses the reply. Recovery after reload must not add twice.
        def lose_response(route):
            response = route.fetch()
            assert response.status == 200
            route.abort()
            page.unroute("**/api/commands", lose_response)

        create("receipt", 1, source="3", product="3")
        page.route("**/api/commands", lose_response)
        page.locator("#submit-action").click()
        expect(page.locator("#form-error")).to_be_visible()
        page.reload()
        expect(page.locator("#pending-banner")).to_be_visible()
        page.locator("#retry-pending").click()
        submit()
        expect(page.locator("#pending-banner")).not_to_be_visible()
        assert read()["audit"]["received_total"] == 28
        assert read()["totals"]["on_hand"] == 17

        page.goto(base + "#history")
        page.locator("#history-search").fill("SKU-103")
        expect(page.locator("#history-table")).not_to_contain_text("Органайзер")
        expect(page.locator("#history-table")).to_contain_text("Корзина")
        page.goto(base + "#stock")
        page.locator("#stock-search").fill("SKU-102")
        expect(page.locator("#stock-table tbody tr")).to_have_count(1)
        page.locator("#stock-search").fill("")
        page.locator('[data-detail="1"]').click()
        expect(page.locator("#dialog-body")).to_contain_text("Принято на маркетплейсе")
        page.locator("#cancel-dialog").click()
        page.set_viewport_size({"width": 390, "height": 844})
        # Wait for the resized layout before Chrome captures a full-page image.
        page.evaluate(
            "() => new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)))"
        )
        page.screenshot(
            path=str(output / "overview-mobile.png"), full_page=True, animations="disabled"
        )
        assert not page.evaluate("document.documentElement.scrollWidth > innerWidth")
        page.locator("#new-operation").click()
        menu_box = page.locator("#operation-menu").bounding_box()
        assert 0 <= menu_box["x"] and menu_box["x"] + menu_box["width"] <= 390
        page.keyboard.press("End")
        expect(page.get_by_role("menuitem", name="Отправка FBO", exact=True)).to_be_focused()
        page.keyboard.press("Escape")

        # A pending operation must recover even if the initial inventory GET fails.
        # These responses are mocked; the real test inventory is not changed.
        for status in [200, 409]:
            recovery_context = browser.new_context()
            pending_command = {
                "request_id": "bd446057-9ac0-433f-b3f9-1db83c91ecc3",
                "action": "fbo",
                "product_id": 1,
                "warehouse_id": 2,
                "quantity": 8,
                "destination": "WB",
            }
            recovery_context.add_init_script(
                "sessionStorage.setItem('checkstock.pending', "
                + json.dumps(json.dumps(pending_command))
                + ");"
            )
            recovery = recovery_context.new_page()
            recovery.on("pageerror", lambda e: errors.append(str(e)))
            state_requests = []

            def unavailable_state(route, _request, requests=state_requests):
                requests.append(route.request.url)
                route.abort()

            recovery.route("**/api/state", unavailable_state)
            response = (
                {"changed": True, "flow_id": 999, "event_id": 999}
                if status == 200
                else {
                    "error": {
                        "code": "insufficient_stock",
                        "message": "Недостаточно товара",
                        "missing": 2,
                        "available_here": 6,
                        "available_total": 6,
                        "alternatives": [],
                    }
                }
            )
            recovery.route(
                "**/api/commands",
                lambda route, _request, code=status, body=response: route.fulfill(
                    status=code, json=body
                ),
            )
            recovery.goto(base)
            expect(recovery.locator("#connection-error")).to_be_visible()
            recovery.locator("#retry-pending").click()
            recovery.locator("#submit-action").click()
            if status == 200:
                expect(recovery.locator("#action-dialog")).not_to_be_visible()
                expect(recovery.locator("#toast")).to_contain_text("Операция выполнена")
                expect(recovery.locator("#refresh")).to_be_enabled()
                assert len(state_requests) == 2
            else:
                expect(recovery.locator("#form-error")).to_contain_text(
                    "На выбранном складе доступно 6"
                )
                expect(recovery.locator("#submit-action")).not_to_be_visible()
                expect(recovery.locator("#cancel-dialog")).to_have_text("Закрыть")
            assert recovery.evaluate("sessionStorage.getItem('checkstock.pending')") is None
            recovery_context.close()
        assert not errors, errors
        browser.close()
        print(
            "Browser acceptance: PASS (inventory, shortage, transitions, archive, "
            "CRUD, XSS, lost response, filters, mobile)."
        )
finally:
    server.terminate()
    server.wait(timeout=10)
