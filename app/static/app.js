"use strict";

const $ = (selector) => document.querySelector(selector);
const esc = (value) =>
  String(value ?? "").replace(
    /[&<>"']/g,
    (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        c
      ],
  );
const num = (value) => Number(value).toLocaleString("ru-RU");
const time = (value) =>
  new Date(value).toLocaleString("ru-RU", {
    day: "2-digit",
    month: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    timeZone: "Europe/Moscow",
  });
const titles = {
  stock: ["Остатки", "Остатки", "Товар на складах, в резерве и в пути."],
  flows: [
    "Отправки и резервы",
    "Отправки и резервы",
    "Резервы заказов, отправка и подтверждение приёмки.",
  ],
  history: [
    "История операций",
    "История операций",
    "Все изменения остатков в порядке поступления.",
  ],
  warehouses: ["Склады", "Склады", "Действующие и архивные фулфилменты."],
};
const iconPaths = {
  box: '<path d="m12 3 9 5v8l-9 5-9-5V8l9-5Z"/><path d="m3 8 9 5 9-5M12 13v8M7.5 5.5l9 5V15"/>',
  stock:
    '<rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/>',
  transfer: '<path d="M4 7h16m-4-4 4 4-4 4M20 17H4m4-4-4 4 4 4"/>',
  history: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
  warehouse:
    '<path d="M3 21V8l9-5 9 5v13H3Z"/><path d="M7 21V11h10v10M7 15h10M7 18h10"/>',
  refresh:
    '<path d="M20 7a9 9 0 0 0-15-2L3 7m0-5v5h5M4 17a9 9 0 0 0 15 2l2-2m0 5v-5h-5"/>',
  plus: '<path d="M12 5v14M5 12h14"/>',
  chevron: '<path d="m6 9 6 6 6-6"/>',
  close: '<path d="m6 6 12 12M18 6 6 18"/>',
  more: '<circle cx="5" cy="12" r="1"/><circle cx="12" cy="12" r="1"/><circle cx="19" cy="12" r="1"/>',
  search: '<circle cx="10" cy="10" r="6"/><path d="m15 15 5 5"/>',
  check: '<path d="m5 12 4 4L19 6"/>',
  arrow: '<path d="M4 12h16m-6-6 6 6-6 6"/>',
  reserve: '<path d="M6 3h12v18l-6-4-6 4V3Z"/>',
  outbound: '<path d="M7 17 17 7M7 7h10v10"/>',
  receipt: '<path d="M12 3v12m-5-5 5 5 5-5M4 16v5h16v-5"/>',
};
function icon(name) {
  return `<svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${iconPaths[name] || iconPaths.box}</svg>`;
}
const actionNames = {
  receipt: "Приход товара",
  transfer: "Перемещение между складами",
  fbo: "Отправка FBO",
  reserve_fbs: "Резерв FBS",
  ship_fbs: "Отправка FBS",
  cancel_fbs: "Отмена резерва",
  receive_transfer: "Приёмка на ФФ",
  receive_fbo: "Приёмка FBO",
  deliver_fbs: "Доставка клиенту",
  create_warehouse: "Новый склад",
  rename_warehouse: "Переименование склада",
  archive_warehouse: "Удаление в архив",
  restore_warehouse: "Восстановление склада",
};
const statusNames = {
  reserved: ["В резерве", "amber"],
  in_transit: ["В пути", "purple"],
  received: ["Принято", "green"],
  delivered: ["Доставлено", "green"],
  cancelled: ["Отменено", "gray"],
};
const kindNames = { transfer: "Между ФФ", fbo: "FBO", fbs: "FBS" };
let data = null;
let page = "stock";
let query = "";
let warehouseFilter = "";
let flowFilter = "active";
let kindFilter = "";
let historyQuery = "";
let busy = false;
let currentAction = null;
let contextId = null;
let toastTimer;
let refreshSequence = 0;
let pending = null;
try {
  pending = JSON.parse(sessionStorage.getItem("checkstock.pending"));
} catch {
  /* Empty session. */
}

function storePending(value) {
  pending = value;
  if (value)
    sessionStorage.setItem("checkstock.pending", JSON.stringify(value));
  else sessionStorage.removeItem("checkstock.pending");
  $("#pending-banner").hidden = !pending;
}
function toast(message) {
  $("#toast").textContent = message;
  $("#toast").hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => {
    $("#toast").hidden = true;
  }, 4000);
}
async function api(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    signal: AbortSignal.timeout(12000),
  });
  let body;
  try {
    body = await response.json();
  } catch {
    throw new Error("Сервер вернул неполный ответ. Повторите запрос.");
  }
  if (!response.ok)
    throw Object.assign(
      new Error(body.error?.message || "Не удалось выполнить запрос."),
      { detail: body.error, status: response.status },
    );
  return {
    body,
    replayed: response.headers.get("Idempotency-Replayed") === "true",
  };
}
async function refresh() {
  const sequence = ++refreshSequence;
  $("#refresh").disabled = true;
  try {
    const result = await api("/api/state");
    if (sequence !== refreshSequence) return;
    data = result.body;
    $("#loading").hidden = true;
    $("#page-content").hidden = false;
    $("#new-operation").disabled = false;
    $("#connection-error").hidden = true;
    $("#updated-at").textContent = `Обновлено ${time(new Date())} · МСК`;
    render();
  } catch (error) {
    if (sequence !== refreshSequence) return;
    $("#loading").hidden = true;
    $("#connection-error").textContent =
      `${error.message || "Нет связи с сервером."} ${data ? "Показаны последние загруженные данные." : "Запустите приложение и нажмите «Обновить»."}`;
    $("#connection-error").hidden = false;
  } finally {
    if (sequence === refreshSequence) $("#refresh").disabled = false;
  }
}
function product(id) {
  return data?.products.find((p) => p.id === Number(id));
}
function warehouse(id) {
  return data?.warehouses.find((w) => w.id === Number(id));
}
function cell(productId, warehouseId) {
  return (
    data.stocks.find(
      (s) =>
        s.product_id === Number(productId) &&
        s.warehouse_id === Number(warehouseId),
    ) || { on_hand: 0, available: 0, reserved: 0 }
  );
}
function productLabel(p) {
  return `<span class="product-info"><span class="product-name">${esc(p.name)}</span><span class="sku">${esc(p.sku)}</span></span>`;
}
let menuAnchor = null;
function closeOperationMenu(restoreFocus = false) {
  if ($("#operation-menu").matches(":popover-open"))
    $("#operation-menu").hidePopover();
  if (restoreFocus) menuAnchor?.focus();
}
function openOperationMenu(anchor) {
  if (!data || busy) return;
  const menu = $("#operation-menu");
  // The native popovertarget handles toggling, including a second trigger click.
  if (menu.matches(":popover-open") && anchor === menuAnchor) return;
  closeOperationMenu();
  menuAnchor = anchor;
  const productId = anchor.dataset.operationMenu;
  menu.innerHTML = [
    ["receipt", "receipt", "Приход товара"],
    ["transfer", "transfer", "Перемещение между складами"],
    ["reserve_fbs", "reserve", "Резерв FBS"],
    ["fbo", "outbound", "Отправка FBO"],
  ]
    .map(
      ([action, symbol, label], index) =>
        `<button role="menuitem" tabindex="-1" ${index === 0 ? "autofocus" : ""} data-create="${action}" data-product="${esc(productId)}">${icon(symbol)}${label}</button>`,
    )
    .join("");
  menu.setAttribute(
    "aria-label",
    productId ? `Операции с ${product(productId).sku}` : "Новая операция",
  );
}
function positionOperationMenu() {
  const menu = $("#operation-menu");
  if (!menuAnchor || !menu.matches(":popover-open")) return;
  menuAnchor.setAttribute("aria-expanded", "true");
  const rect = menuAnchor.getBoundingClientRect();
  if (rect.bottom < 0 || rect.top > innerHeight) {
    closeOperationMenu();
    return;
  }
  const left = Math.max(
    12,
    Math.min(rect.right - menu.offsetWidth, innerWidth - menu.offsetWidth - 12),
  );
  const top =
    rect.bottom + menu.offsetHeight + 12 <= innerHeight
      ? rect.bottom + 8
      : Math.max(12, rect.top - menu.offsetHeight - 8);
  menu.style.left = `${left}px`;
  menu.style.top = `${top}px`;
}
function stat(label, value, caption, key) {
  return `<div class="stat" data-stat="${key}"><div class="stat-label">${label}</div><div class="stat-value">${num(value)}<small>ед.</small></div><div class="stat-caption">${caption}</div></div>`;
}
function stats() {
  const t = data.totals;
  return `<div class="stats">${stat("На складах", t.on_hand, "Включая резерв и архив", "physical")}${stat("Доступно", t.available, "На складах − резерв", "available")}${stat("В резерве FBS", t.reserved, "Закреплено за заказами", "reserved")}${stat("В пути", t.transfer_transit + t.fbo_transit + t.fbs_transit, "Все отправленные товары", "transit")}</div>`;
}

function balance() {
  if (!data.audit.ok)
    return `<div class="notice error"><strong>Найдены расхождения в учёте</strong><p>${data.audit.errors.map(esc).join("<br>")}</p></div>`;
  const t = data.totals;
  const transit = t.transfer_transit + t.fbo_transit + t.fbs_transit;
  return `<details class="balance-strip"><summary>${icon("check")}Учёт сходится${icon("chevron")}</summary><p>${num(data.audit.received_total)} ед. принято = ${num(t.on_hand)} на складах + ${num(transit)} в пути + ${num(t.marketplace)} на маркетплейсе + ${num(t.delivered)} у клиентов.</p><p>Резерв входит в остаток склада и не прибавляется к нему.</p></details>`;
}

function stockTable() {
  const products = data.products.filter((p) =>
    `${p.sku} ${p.name}`.toLowerCase().includes(query.toLowerCase()),
  );
  const warehouses = data.warehouses.filter(
    (w) => !warehouseFilter || w.id === Number(warehouseFilter),
  );
  if (!products.length)
    return '<div class="empty">Товары не найдены<p>Попробуйте другое название или артикул.</p></div>';
  return `<table class="stock-table"><thead><tr><th class="product-cell" rowspan="2">Товар</th>${warehouses.map((w) => `<th class="group ${w.archived ? "warehouse-archived" : ""}" colspan="3">${esc(w.name)}${w.archived ? '<span class="archive-label">В архиве · остаток сохранён</span>' : ""}</th>`).join("")}<th class="group" rowspan="2">В пути</th><th rowspan="2"><span class="sr-only">Операции</span></th></tr><tr>${warehouses.map(() => '<th class="number subhead group-start">На складе</th><th class="number subhead">Доступно</th><th class="number subhead">Резерв</th>').join("")}</tr></thead><tbody>${products
    .map(
      (p) =>
        `<tr data-sku="${esc(p.sku)}"><td class="product-cell"><button class="product-link" data-detail="${p.id}" aria-label="Где товар ${esc(p.sku)}">${productLabel(p)}</button></td>${warehouses
          .map((w) => {
            const s = cell(p.id, w.id);
            return `<td class="number group-start ${s.on_hand ? "" : "zero"}">${num(s.on_hand)}</td><td class="number available ${s.available ? "" : "zero"}">${num(s.available)}</td><td class="number ${s.reserved ? "reserved-positive" : "zero"}">${num(s.reserved)}</td>`;
          })
          .join(
            "",
          )}<td class="number group-start ${p.transfer_transit + p.fbo_transit + p.fbs_transit ? "" : "zero"}">${num(p.transfer_transit + p.fbo_transit + p.fbs_transit)}</td><td><button class="icon-button row-menu" data-operation-menu="${p.id}" popovertarget="operation-menu" aria-label="Операции с ${esc(p.sku)}" aria-controls="operation-menu" aria-haspopup="menu" aria-expanded="false">${icon("more")}</button></td></tr>`,
    )
    .join("")}</tbody></table>`;
}
function renderStock() {
  const t = data.totals;
  return `${stats()}${t.archived_on_hand ? `<div class="notice warning"><div><strong>${num(t.archived_on_hand)} ед. остаются на складах в архиве</strong><p>Они включены в итоги. Для новых заказов восстановите ФФ или переместите свободный товар.</p></div><a class="btn secondary small" href="#warehouses">Открыть склады</a></div>` : ""}<section class="panel"><div class="panel-heading"><div><h2>Товары <span class="count-chip">${data.products.length} SKU</span></h2></div></div><div class="toolbar"><div class="search">${icon("search")}<input id="stock-search" aria-label="Поиск товара" placeholder="Найти по названию или артикулу" value="${esc(query)}"></div><select id="warehouse-filter" aria-label="Фильтр склада"><option value="">Все склады</option>${data.warehouses.map((w) => `<option value="${w.id}" ${String(w.id) === warehouseFilter ? "selected" : ""}>${esc(w.name)}${w.archived ? " · архив" : ""}</option>`).join("")}</select></div><div class="table-wrap" id="stock-table" role="region" aria-label="Остатки по складам" tabindex="0">${stockTable()}</div><div class="panel-foot">Количество в единицах. Резерв входит в остаток склада, товар в пути — нет.</div></section><div class="section-heading"><h2>Товар в пути</h2><a href="#flows" class="text-link">Все отправки ${icon("arrow")}</a></div><div class="transit-grid">${[
    ["transfer", "Между складами", "transfer"],
    ["fbo", "На маркетплейс · FBO", "outbound"],
    ["fbs", "К клиенту · FBS", "outbound"],
  ]
    .map(
      ([kind, label, symbol]) =>
        `<a href="#flows" class="transit-card" data-kind-link="${kind}">${icon(symbol)}<span>${label}</span><strong>${num(t[`${kind}_transit`])}<small>ед.</small></strong></a>`,
    )
    .join("")}</div>${balance()}`;
}
function flowButtons(f) {
  const button = (action, text, quiet = false) =>
    `<button class="btn ${quiet ? "quiet" : "secondary"} small" data-transition="${action}" data-id="${f.id}">${text}</button>`;
  if (f.status === "reserved")
    return (
      button("cancel_fbs", "Отменить", true) + button("ship_fbs", "Отправить")
    );
  if (f.status === "in_transit")
    return f.kind === "fbs"
      ? button("deliver_fbs", "Доставлено")
      : button(`receive_${f.kind}`, "Принять товар");
  return '<span class="subtle">Завершено</span>';
}
function renderFlows() {
  const flows = data.flows.filter(
    (f) =>
      (!kindFilter || f.kind === kindFilter) &&
      (flowFilter === "all" ||
        ["reserved", "in_transit"].includes(f.status) ===
          (flowFilter === "active")),
  );
  return `<section class="panel"><div class="panel-heading"><div><h2>Отправки и резервы <span class="count-chip">${flows.length}</span></h2><p>Приёмка и доставка фиксируются отдельным подтверждением</p></div></div><div class="toolbar"><div class="filters">${[
    ["active", "Активные"],
    ["completed", "Завершённые"],
    ["all", "Все"],
  ]
    .map(
      ([v, n]) =>
        `<button class="filter-btn ${flowFilter === v ? "selected" : ""}" data-flow-filter="${v}" aria-pressed="${flowFilter === v}">${n}</button>`,
    )
    .join(
      "",
    )}</div><select id="kind-filter" aria-label="Вид отправки"><option value="">Все виды отправок</option>${Object.entries(
    kindNames,
  )
    .map(
      ([k, n]) =>
        `<option value="${k}" ${kindFilter === k ? "selected" : ""}>${n}</option>`,
    )
    .join(
      "",
    )}</select></div>${flows.length ? `<div class="table-wrap" role="region" aria-label="Отправки и резервы" tabindex="0"><table class="flows-table"><thead><tr><th>Отправка / товар</th><th>Маршрут</th><th>Кол-во</th><th>Статус</th><th></th></tr></thead><tbody>${flows.map((f) => `<tr data-flow="${f.id}"><td>${productLabel(product(f.product_id))}<div class="subtle">${kindNames[f.kind]} · #${String(f.id).padStart(3, "0")}${f.reference ? ` · ${esc(f.reference)}` : ""}</div></td><td><div class="route-line">${esc(f.source)} <span>→</span> ${esc(f.destination)}</div><div class="subtle">${time(f.created_at)} · МСК</div></td><td>${num(f.quantity)} ед.</td><td><span class="badge ${statusNames[f.status][1]}">${statusNames[f.status][0]}</span></td><td><div class="action-row">${flowButtons(f)}</div></td></tr>`).join("")}</tbody></table></div>` : `<div class="empty">${icon("transfer")}Здесь пока нет отправок<p>Используйте «Новую операцию», чтобы оформить отправку или резерв, либо измените фильтры.</p></div>`}</section>${balance()}`;
}
function historyTable() {
  const events = data.events.filter((e) =>
    `${actionNames[e.action]} ${e.source} ${e.destination} ${e.note} ${product(e.product_id)?.sku || ""} ${product(e.product_id)?.name || ""}`
      .toLowerCase()
      .includes(historyQuery.toLowerCase()),
  );
  if (!events.length) return '<div class="empty">Операции не найдены</div>';
  return `<table class="history-table"><thead><tr><th>Дата / операция</th><th>Товар</th><th>Откуда → куда</th><th>Кол-во</th><th>На складе</th><th>Резерв</th></tr></thead><tbody>${events.map((e) => `<tr><td><div>${actionNames[e.action]}</div><div class="subtle">${time(e.created_at)} · #${e.id}</div></td><td>${e.product_id ? productLabel(product(e.product_id)) : '<span class="subtle">Справочник складов</span>'}</td><td><div class="route-line">${esc(e.source) || "—"} <span>→</span> ${esc(e.destination) || "—"}</div><div class="subtle">${esc(e.note)}</div></td><td>${e.quantity ? `${num(e.quantity)} ед.` : "—"}</td>${[e.on_hand_delta, e.reserved_delta].map((n) => `<td class="${n > 0 ? "positive" : n < 0 ? "negative" : "subtle"}">${n > 0 ? "+" : ""}${n || "—"}</td>`).join("")}</tr>`).join("")}</tbody></table>`;
}
function renderHistory() {
  return `<section class="panel"><div class="panel-heading"><div><h2>Журнал движений <span class="count-chip">${data.events.length}</span></h2><p>Названия складов сохранены на момент операции · время МСК</p></div></div><div class="toolbar"><div class="search">${icon("search")}<input id="history-search" aria-label="Поиск в истории" placeholder="Артикул, склад или операция" value="${esc(historyQuery)}"></div></div><div class="table-wrap" id="history-table" role="region" aria-label="История операций" tabindex="0">${historyTable()}</div><div class="panel-foot">Резерв меняет доступность. Отправка меняет физический остаток.</div></section>${balance()}`;
}
function renderWarehouses() {
  return `<div class="section-heading"><h2>Фулфилменты <span class="count-chip">${data.warehouses.length}</span></h2><button class="btn secondary" data-create="create_warehouse">${icon("plus")}Добавить склад</button></div><div class="warehouse-grid">${data.warehouses
    .map((w) => {
      const s = data.stocks.filter((s) => s.warehouse_id === w.id);
      const sum = (k) => s.reduce((a, s) => a + s[k], 0);
      return `<article class="warehouse-card ${w.archived ? "archived" : ""}" data-warehouse="${w.id}"><div class="warehouse-top"><h2>${esc(w.name)}</h2><span class="badge ${w.archived ? "amber" : "green"}">${w.archived ? "В архиве" : "Активен"}</span></div><p>${w.archived ? "Остатки учтены здесь. Можно завершить отправки или переместить свободный товар." : "Приход, резервы и отправки доступны."}</p><div class="warehouse-stats"><div><strong>${num(sum("on_hand"))}</strong><span>На складе</span></div><div><strong>${num(sum("available"))}</strong><span>Доступно</span></div><div><strong>${num(sum("reserved"))}</strong><span>В резерве</span></div></div><div class="action-row"><button class="btn secondary small" data-warehouse-action="rename_warehouse" data-id="${w.id}">Переименовать</button><button class="btn quiet small" data-warehouse-action="${w.archived ? "restore_warehouse" : "archive_warehouse"}" data-id="${w.id}">${w.archived ? "Восстановить" : "Удалить в архив"}</button></div></article>`;
    })
    .join(
      "",
    )}</div><div class="notice info warehouse-note">Удаление переводит ФФ в архив: товар остаётся на этом складе, история и открытые отправки сохраняются. Новые операции ограничены; восстановление доступно в любой момент.</div>`;
}
function render() {
  closeOperationMenu();
  page = Object.hasOwn(titles, location.hash.slice(1))
    ? location.hash.slice(1)
    : "stock";
  document.querySelectorAll("[data-page]").forEach((a) => {
    a.classList.toggle("active", a.dataset.page === page);
    if (a.dataset.page === page) a.setAttribute("aria-current", "page");
    else a.removeAttribute("aria-current");
  });
  $("#breadcrumb-title").textContent = titles[page][0];
  $("#page-title").textContent = titles[page][1];
  document.title = `${titles[page][0]} · CheckStock`;
  $("#page-description").textContent = titles[page][2];
  $("#sku-count").textContent = data.products.length;
  $("#flow-count").textContent = data.flows.filter((f) =>
    ["reserved", "in_transit"].includes(f.status),
  ).length;
  $("#page-content").innerHTML = {
    stock: renderStock,
    flows: renderFlows,
    history: renderHistory,
    warehouses: renderWarehouses,
  }[page]();
  $("#pending-banner").hidden = !pending;
}
function field(name, label, content, hint = "") {
  return `<div class="field"><label for="f-${name}">${label}</label>${content}${hint ? `<div class="field-hint">${hint}</div>` : ""}</div>`;
}
function select(name, label, options) {
  return field(
    name,
    label,
    `<select id="f-${name}" name="${name}" required>${options}</select>`,
  );
}
function input(name, label, type = "text", value = "", extra = "") {
  return field(
    name,
    label,
    `<input id="f-${name}" name="${name}" type="${type}" value="${esc(value)}" ${extra}>`,
  );
}
function availability() {
  if (!$("#f-warehouse_id") || !$("#f-product_id")) return;
  const s = cell($("#f-product_id").value, $("#f-warehouse_id").value);
  $("#availability").innerHTML =
    `<span><strong>${num(s.on_hand)}</strong> на складе</span><span><strong>${num(s.available)}</strong> доступно</span><span><strong>${num(s.reserved)}</strong> в резерве</span>`;
  if ($("#f-destination_id")) {
    const source = $("#f-warehouse_id").value;
    [...$("#f-destination_id").options].forEach((o) => {
      o.disabled = o.value === source;
    });
    if ($("#f-destination_id").value === source)
      $("#f-destination_id").value =
        [...$("#f-destination_id").options].find((o) => !o.disabled)?.value ||
        "";
  }
}
function baseDialog(title, context = "") {
  $("#action-form").reset();
  $("#dialog-title").textContent = title;
  $("#dialog-context").textContent = context;
  $("#dialog-context").hidden = !context;
  $("#form-error").hidden = true;
  $("#submit-action").hidden = false;
  $("#submit-action").className = "btn primary";
  $("#submit-action").textContent = "Подтвердить";
  $("#cancel-dialog").textContent = "Отмена";
}
function openAction(action, id = null, productId = null) {
  if (!data || busy) return;
  if (pending) {
    openPending();
    return;
  }
  closeOperationMenu();
  currentAction = action;
  contextId = id;
  baseDialog(actionNames[action]);
  let body = "";
  if (["receipt", "transfer", "fbo", "reserve_fbs"].includes(action)) {
    const sources = data.warehouses.filter(
      (w) => action === "transfer" || !w.archived,
    );
    body = select(
      "product_id",
      "Товар",
      data.products
        .map(
          (p) =>
            `<option value="${p.id}">${esc(p.sku)} · ${esc(p.name)}</option>`,
        )
        .join(""),
    );
    body += select(
      "warehouse_id",
      action === "receipt" ? "Склад приёмки" : "Со склада",
      sources
        .map(
          (w) =>
            `<option value="${w.id}">${esc(w.name)}${w.archived ? " · архив" : ""}</option>`,
        )
        .join(""),
    );
    body += '<div class="availability" id="availability"></div>';
    if (action === "transfer")
      body += select(
        "destination_id",
        "На склад",
        data.warehouses
          .filter((w) => !w.archived)
          .map((w) => `<option value="${w.id}">${esc(w.name)}</option>`)
          .join(""),
      );
    if (["fbo", "reserve_fbs"].includes(action))
      body += input(
        "destination",
        action === "fbo" ? "Склад маркетплейса" : "Заказ / получатель",
        "text",
        "",
        `required maxlength="120" placeholder="${action === "fbo" ? "WB · Коледино" : "Заказ FBS-001"}"`,
      );
    body += `<div class="field-row">${input("quantity", "Количество, ед.", "number", 1, 'required min="1" max="1000000" step="1"')}${input("reference", "Комментарий (необязательно)", "text", "", 'maxlength="100" placeholder="Номер накладной"')}</div>`;
    body += `<p class="zero-note">${{ receipt: "Товар сразу увеличит физический и доступный остаток выбранного ФФ.", transfer: "Товар спишется с ФФ отправления и будет в пути до подтверждения приёмки.", fbo: "Товар покинет ФФ и будет числиться в пути до приёмки на маркетплейсе.", reserve_fbs: "Товар останется на ФФ, но будет недоступен для других отправок до отмены или отправки заказа." }[action]}</p>`;
    $("#submit-action").textContent = {
      receipt: "Оформить приход",
      transfer: "Отправить перемещение",
      fbo: "Отправить FBO",
      reserve_fbs: "Зарезервировать",
    }[action];
  } else if (["create_warehouse", "rename_warehouse"].includes(action)) {
    body = input(
      "name",
      "Название склада",
      "text",
      id ? warehouse(id).name : "",
      'required maxlength="80" placeholder="Например, Восток"',
    );
    $("#submit-action").textContent = "Сохранить";
  } else if (["archive_warehouse", "restore_warehouse"].includes(action)) {
    const w = warehouse(id),
      rows = data.stocks.filter((s) => s.warehouse_id === w.id);
    const onHand = rows.reduce((a, s) => a + s.on_hand, 0),
      reserved = rows.reduce((a, s) => a + s.reserved, 0);
    body = `<div class="confirm-summary"><strong>ФФ «${esc(w.name)}»</strong><p>${num(onHand)} ед. на складе · ${num(reserved)} ед. в резерве FBS</p></div><p class="dialog-description">${action === "archive_warehouse" ? "Склад уйдёт в архив. Товар останется на нём, остатки и история сохранятся. Новые приходы, резервы и FBO будут недоступны; существующие отправки можно завершить, свободный товар — переместить на активный ФФ." : "Склад снова станет доступен для новых приходов, резервов и отправок. Остатки не изменятся."}</p>`;
    $("#submit-action").textContent =
      action === "archive_warehouse" ? "Удалить в архив" : "Восстановить";
    if (action === "archive_warehouse")
      $("#submit-action").className = "btn danger";
  } else {
    const f = data.flows.find((f) => f.id === Number(id));
    if (!f) return;
    body = `<div class="confirm-summary"><strong>${esc(product(f.product_id).name)} · ${num(f.quantity)} ед.</strong><p>${esc(f.source)} → ${esc(f.destination)}</p><p>${kindNames[f.kind]} · #${String(f.id).padStart(3, "0")}</p></div><p class="dialog-description">${{ ship_fbs: "Резерв закроется, товар покинет ФФ и перейдёт в путь к клиенту.", cancel_fbs: "Резерв снимется. Товар останется на ФФ и снова станет доступен.", receive_transfer: "Товар выйдет из пути и увеличит остаток ФФ назначения.", receive_fbo: "Товар выйдет из пути и будет учтён на складе маркетплейса.", deliver_fbs: "Товар выйдет из пути и будет учтён как доставленный клиенту." }[action]}</p>`;
    $("#submit-action").textContent = {
      ship_fbs: "Отправить заказ",
      cancel_fbs: "Снять резерв",
      receive_transfer: "Подтвердить приёмку",
      receive_fbo: "Подтвердить приёмку",
      deliver_fbs: "Подтвердить доставку",
    }[action];
  }
  $("#dialog-body").innerHTML = body;
  if (productId && $("#f-product_id")) $("#f-product_id").value = productId;
  if (
    warehouseFilter &&
    $("#f-warehouse_id")?.querySelector(`option[value="${warehouseFilter}"]`)
  )
    $("#f-warehouse_id").value = warehouseFilter;
  availability();
  $("#action-dialog").showModal();
}
function openDetail(id) {
  const p = product(id);
  if (!p) return;
  currentAction = null;
  contextId = null;
  baseDialog(p.name, p.sku + " · Расположение товара");
  $("#submit-action").hidden = true;
  $("#cancel-dialog").textContent = "Закрыть";
  $("#dialog-body").innerHTML = `<div class="detail-grid">${[
    ["on_hand", "Физически на ФФ"],
    ["reserved", "Из них в резерве FBS"],
    ["transfer_transit", "В пути между ФФ"],
    ["fbo_transit", "В пути на МП · FBO"],
    ["fbs_transit", "В пути к клиенту · FBS"],
    ["marketplace", "Принято на маркетплейсе"],
    ["delivered", "Доставлено клиентам"],
  ]
    .map(
      ([k, label]) =>
        `<div class="detail-cell">${label}<strong>${num(p[k])} <small>ед.</small></strong></div>`,
    )
    .join("")}</div><div class="dialog-routes">${data.flows
    .filter((f) => f.product_id === p.id && f.status !== "cancelled")
    .map(
      (f) =>
        `${esc(f.source)} → ${esc(f.destination)} · ${f.quantity} ед. <span class="badge ${statusNames[f.status][1]}">${statusNames[f.status][0]}</span>`,
    )
    .join(
      "<br>",
    )}</div><p class="zero-note">Резерв входит в физический остаток и не прибавляется к нему.</p>`;
  $("#action-dialog").showModal();
}
function openPending() {
  if (!pending || busy) return;
  currentAction = "retry";
  contextId = null;
  baseDialog("Проверить результат");
  $("#dialog-body").innerHTML =
    `<p class="dialog-description">Связь прервалась до подтверждения. Повторно проверим ту же операцию. Если она уже выполнена, остатки не изменятся.</p><div class="confirm-summary"><strong>${esc(actionNames[pending.action] || pending.action)}</strong>${pending.quantity ? `<p>${num(pending.quantity)} ед.</p>` : ""}</div>`;
  $("#submit-action").textContent = "Проверить результат";
  $("#action-dialog").showModal();
}
function formPayload() {
  const payload = { action: currentAction, request_id: crypto.randomUUID() };
  for (const [k, v] of new FormData($("#action-form")).entries())
    payload[k] = [
      "product_id",
      "warehouse_id",
      "destination_id",
      "quantity",
    ].includes(k)
      ? Number(v)
      : v;
  if (contextId)
    payload[currentAction.endsWith("warehouse") ? "warehouse_id" : "flow_id"] =
      Number(contextId);
  return payload;
}
function setBusy(value) {
  busy = value;
  $("#action-form")
    .querySelectorAll("input,select,button")
    .forEach((e) => {
      e.disabled = value;
    });
}
function successMessage(payload) {
  if (!data) return "Операция выполнена. Загружаем остатки.";
  const name = product(payload.product_id)?.name;
  const source = warehouse(payload.warehouse_id)?.name;
  const quantity = num(payload.quantity);
  const f = data.flows.find((flow) => flow.id === payload.flow_id);
  const movement = {
    receipt: `${name}: принято ${quantity} ед. на склад «${source}».`,
    transfer: `${name}: ${quantity} ед. отправлено со склада «${source}» на «${warehouse(payload.destination_id)?.name}».`,
    reserve_fbs: `${name}: ${quantity} ед. в резерве на складе «${source}».`,
    fbo: `${name}: ${quantity} ед. отправлено в «${payload.destination}».`,
  };
  if (movement[payload.action]) return movement[payload.action];
  if (f)
    return `${product(f.product_id).name}: ${num(f.quantity)} ед. · ${actionNames[payload.action].toLowerCase()} подтверждена.`;
  return (
    {
      create_warehouse: `Склад «${payload.name}» добавлен.`,
      rename_warehouse: `Склад переименован в «${payload.name}».`,
      archive_warehouse: `Склад «${source}» в архиве. Остатки сохранены.`,
      restore_warehouse: `Склад «${source}» восстановлен.`,
    }[payload.action] || "Операция выполнена."
  );
}
async function submit(event) {
  event.preventDefault();
  if (busy || !currentAction) return;
  const payload = pending || formPayload();
  storePending(payload);
  setBusy(true);
  $("#form-error").hidden = true;
  try {
    const { body, replayed } = await api("/api/commands", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    storePending(null);
    $("#action-dialog").close();
    toast(
      replayed || !body.changed
        ? "Операция уже подтверждена. Остатки не изменились."
        : successMessage(payload),
    );
    await refresh();
  } catch (error) {
    const definitive = error.status && error.status < 500;
    if (definitive) storePending(null);
    let message = esc(
      error.message ||
        "Связь прервалась. Нажмите «Проверить результат»: операция не применится дважды.",
    );
    if (error.detail?.code === "insufficient_stock") {
      const source = warehouse(payload.warehouse_id)?.name;
      const where = source ? `складе «${esc(source)}»` : "выбранном складе";
      message = `Не хватает ${num(error.detail.missing)} ед. На ${where} доступно ${num(error.detail.available_here)} из запрошенных ${num(payload.quantity)}. Уменьшите количество или сначала переместите товар с другого склада.`;
    }
    if (error.detail?.alternatives?.length)
      message += `<p><strong>На других складах:</strong> ${error.detail.alternatives.map((a) => `${esc(a.warehouse_name)}${a.archived ? " (архив)" : ""} — ${num(a.available)} ед.`).join(", ")}. Всего доступно ${num(error.detail.available_total)} ед.</p>`;
    if (!definitive)
      message +=
        "<p>Сохранён исходный запрос. Его можно безопасно повторить, даже после обновления страницы.</p>";
    if (definitive && currentAction === "retry") {
      currentAction = null;
      $("#submit-action").hidden = true;
      $("#cancel-dialog").textContent = "Закрыть";
      message +=
        "<p>Закройте окно и создайте новую операцию с исправленными данными.</p>";
    }
    $("#form-error").innerHTML = message;
    $("#form-error").hidden = false;
  } finally {
    setBusy(false);
    if (pending) {
      $("#action-form")
        .querySelectorAll("input,select")
        .forEach((e) => {
          e.disabled = true;
        });
      $("#submit-action").textContent = "Проверить результат";
    }
  }
}
function closeDialog() {
  if (!busy) $("#action-dialog").close();
}
$("#action-form").addEventListener("submit", submit);
$("#action-form").addEventListener("change", availability);
$("#action-dialog").addEventListener("cancel", (e) => {
  if (busy) e.preventDefault();
});
$("#close-dialog").addEventListener("click", closeDialog);
$("#cancel-dialog").addEventListener("click", closeDialog);
$("#refresh").addEventListener("click", refresh);
$("#retry-pending").addEventListener("click", openPending);
document.addEventListener("click", (event) => {
  const target = event.target.closest("button,a");
  if (!target) return;
  if (target.matches(".skip-link")) {
    event.preventDefault();
    $("#main-content").focus();
    return;
  }
  if (target.hasAttribute("data-operation-menu")) openOperationMenu(target);
  if (target.dataset.create) {
    closeOperationMenu();
    openAction(target.dataset.create, null, target.dataset.product);
  }
  if (target.dataset.transition)
    openAction(target.dataset.transition, target.dataset.id);
  if (target.dataset.warehouseAction)
    openAction(target.dataset.warehouseAction, target.dataset.id);
  if (target.dataset.detail) openDetail(target.dataset.detail);
  if (target.dataset.flowFilter) {
    flowFilter = target.dataset.flowFilter;
    render();
  }
  if (target.dataset.kindLink) {
    kindFilter = target.dataset.kindLink;
    flowFilter = "active";
    if (page === "flows") render();
  }
});
document.addEventListener("input", (event) => {
  if (event.target.id === "stock-search") {
    query = event.target.value;
    $("#stock-table").innerHTML = stockTable();
  }
  if (event.target.id === "history-search") {
    historyQuery = event.target.value;
    $("#history-table").innerHTML = historyTable();
  }
});
document.addEventListener("change", (event) => {
  if (event.target.id === "warehouse-filter") {
    warehouseFilter = event.target.value;
    $("#stock-table").innerHTML = stockTable();
  }
  if (event.target.id === "kind-filter") {
    kindFilter = event.target.value;
    render();
  }
});
window.addEventListener("hashchange", () => {
  if (data) render();
});
$("#operation-menu").addEventListener("beforetoggle", (event) => {
  if (event.newState === "closed")
    menuAnchor?.setAttribute("aria-expanded", "false");
});
$("#operation-menu").addEventListener("toggle", (event) => {
  if (event.newState === "open") positionOperationMenu();
});
$("#operation-menu").addEventListener("keydown", (event) => {
  const items = [...$("#operation-menu").querySelectorAll("button")];
  const index = items.indexOf(document.activeElement);
  if (
    ["ArrowDown", "ArrowUp", "Home", "End", "Escape", "Tab"].includes(event.key)
  ) {
    if (event.key !== "Tab") event.preventDefault();
    if (event.key === "Escape" || event.key === "Tab") closeOperationMenu(true);
    else
      items[
        event.key === "Home"
          ? 0
          : event.key === "End"
            ? items.length - 1
            : (index + (event.key === "ArrowDown" ? 1 : -1) + items.length) %
              items.length
      ].focus();
  }
});
window.addEventListener("resize", () => closeOperationMenu());
document.addEventListener("scroll", positionOperationMenu, true);
document.querySelectorAll("[data-icon]").forEach((element) => {
  element.innerHTML = icon(element.dataset.icon);
});
storePending(pending);
refresh();
