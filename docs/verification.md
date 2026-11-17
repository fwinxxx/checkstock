# Проверка CheckStock

Проверены локальный запуск, складские операции, пограничные случаи и работа интерфейса. Серверные тесты выполняются на отдельной PostgreSQL-базе.

## Выполненные проверки

| Проверка | Среда | Результат |
|---|---|---|
| Запуск с пустой базой, миграции, seed, healthcheck | Docker Compose, Linux ARM64, Python 3.12, PostgreSQL 17 | Приложение и БД healthy |
| API и складские сценарии | Настоящий PostgreSQL в отдельной базе | 35 тестов прошли |
| Покрытие Python-кода | pytest-cov в контейнере, 17 ноября | 99% строк; это дополнение к сценариям, а не гарантия отсутствия ошибок |
| Стиль и форматирование | Ruff | Проверки прошли |
| Синтаксис JavaScript | Node.js `--check` | Проверка прошла |
| Сквозной UI | Playwright + Chrome, macOS | Сценарий прошёл без JavaScript-ошибок |
| Адаптивная компоновка | Ширины 320, 390, 1024 и 1440 px | Страница не переполняется; широкие таблицы прокручиваются отдельно |
| Доступность | axe-core 4.11.1, WCAG A/AA, четыре раздела и форма на четырёх размерах | Автоматических нарушений не найдено; отдельно проверены клавиатурные меню и возврат фокуса |
| Списки и обновление интерфейса | Браузер на macOS | Фильтры и четыре формы проверены; CSS/JS получают новый URL при изменении содержимого |

GitHub Actions запускает контейнерные тесты и проверки Ruff при push и pull request.

## Покрытие требований

| Требование | Где проверяется |
|---|---|
| Все SKU и нулевые остатки на каждом ФФ | `test_initial_quantities_and_zero_cells` |
| Приход только на выбранный ФФ | `test_receipt_increases_only_selected_stock` |
| FBS: резерв → отправка → доставка | `test_fbs_reservation_shipping_and_delivery` |
| Отмена освобождает резерв | `test_cancel_releases_reserve_without_changing_physical_stock` |
| Товар в пути между отправкой и приёмкой | `test_transfer_requires_receiving_to_increase_destination` |
| FBO: путь → склад маркетплейса | `test_fbo_receipt_moves_stock_from_transit_to_marketplace` |
| Локальная нехватка при достаточном общем запасе | `test_local_shortage_does_not_spend_other_warehouse_stock`, 3 вида операций |
| Резерв нельзя потратить другой отправкой | `test_reserved_units_cannot_be_sent_by_another_flow` |
| Повтор UUID и конфликт содержимого | `test_same_request_is_replayed_without_new_receipt` |
| Повтор приёмки с новым UUID | `test_duplicate_confirmation_with_new_request_key_is_noop` |
| Повтор отгрузки; отмена уже отправленного FBS | `test_repeated_shipping_and_cancel_cannot_double_spend` |
| Архив с запасом и резервом | `test_archive_preserves_stock_history_and_outstanding_reservations` |
| Получатель ушёл в архив после отправки | `test_transfer_can_arrive_at_warehouse_archived_after_dispatch` |
| Названия в истории сохраняются | `test_rename_preserves_historical_route_names` |
| Некорректные количества, ссылки и переходы | `test_invalid_quantities_cannot_change_stock`, `test_invalid_routes_and_missing_entities` |
| Конкурентный резерв и дубли прихода | `test_competing_reservations_cannot_overbook`, `test_concurrent_duplicate_receipts_are_applied_once` |
| Повтор seed после пользовательских изменений | `test_seed_is_repeatable_after_warehouse_changes` |
| Ограничения самой БД | `test_database_constraints_reject_negative_or_over_reserved_stock` |
| Ошибка записи журнала откатывает всю операцию | `test_journal_write_failure_rolls_back_stock_and_idempotency_record` |
| Реальное обнаружение расхождений | `test_reconciliation_detects_stock_drift`, `test_reconciliation_detects_reserve_drift` |

## Сквозной браузерный тест

`scripts/browser_check.py` запускает отдельный HTTP-сервер, выполняет сценарий через UI и останавливает его. Он очищает **только выбранную тестовую базу**; имя базы обязано заканчиваться на `_test`. Не запускайте его одновременно с pytest на одной базе.

Пример с отдельным одноразовым PostgreSQL:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-browser.txt
.venv/bin/python -m playwright install chromium

docker run -d --rm --name checkstock-browser-db \
  -e POSTGRES_USER=checkstock -e POSTGRES_PASSWORD=browser_test \
  -e POSTGRES_DB=checkstock_browser_test \
  -p 127.0.0.1:55433:5432 postgres:17-alpine
```

Дождитесь `accepting connections`:

```bash
docker exec checkstock-browser-db pg_isready -U checkstock -d checkstock_browser_test
```

Затем:

```bash
TEST_DATABASE_URL=postgresql+psycopg://checkstock:browser_test@127.0.0.1:55433/checkstock_browser_test \
  .venv/bin/python scripts/browser_check.py
```

Если уже установлен Google Chrome, можно вместо установки Chromium добавить переменную `PLAYWRIGHT_CHANNEL=chrome`. На Linux для браузера могут понадобиться системные зависимости: `python -m playwright install --with-deps chromium`.

Результат: `Browser acceptance: PASS …`. Скриншоты сохраняются в `output/screenshots/` (не входят в git). После проверки: `docker stop checkstock-browser-db`.

Сценарий включает выбор SKU из строки, повторное открытие/закрытие меню, Escape/End и возврат фокуса, переход к содержимому без смены раздела, резерв и отмену, локальную нехватку, перемещение и приёмку, FBO/FBS, архив, добавление/переименование склада, экранирование введённого названия, поиск, мобильную версию и неизвестный hash URL. Для проверки потери ответа браузер перехватывает запрос, действительно отправляет его серверу, затем обрывает ответ. После перезагрузки повтор с сохранённым UUID должен оставить ровно один приход. Отдельными подставными HTTP-ответами проверены успех и нехватка при восстановлении операции без загруженного снимка остатков.

## Ограничения проверки

Не выполнялись нагрузочное тестирование больших каталогов, тесты реальных API маркетплейсов, публичного развёртывания, Safari/Firefox и многопользовательских прав. Эти возможности не заявлены как реализованные. Браузерные сценарии проверяют пользовательский путь; серверные тесты отдельно проверяют конкуренцию и откаты.
