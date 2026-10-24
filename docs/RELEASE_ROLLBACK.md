# FORMIQ — безопасный выпуск и откат PR #15

**Не является разрешением на выполнение.** Во время задачи №1 ни один
production-запрос на изменение данных, webhook или Render deployment не запускается.

## Перед выпуском (отдельное согласие владельца)

1. Повторно сравнить `main`, SHA PR, GitHub Actions и Render Live SHA.
   Автодеплой у production включён на `main`: слияние PR автоматически может
   запустить публикацию. Нельзя merge без явного разрешения на deploy.
2. Убедиться в сроке годности/free-tier и доступном объёме PostgreSQL.
   **Render Free PostgreSQL не предоставляет ни резервные копии, ни PITR**
   (https://render.com/docs/free). Прямой pg_dump с совместимого клиента
   и восстановление в отдельной тестовой БД обязательны перед выпуском.
   Имеющаяся production DB free истекает 19 ноября 2026; после
   14-дневного льготного срока Render может удалить её и данные.
3. Снять непротиворечивый `pg_dump --format=custom` через **разрешённое
   read-only** подключение, не выводя DSN/пароли в CI/чат. Хранить защищённо
   с ограниченными правами и зашифрованным внешним доступом.
   Процедура зависит от утверждённого места хранения и прав; ключи не
   коммитить. Для PostgreSQL 18 использовать совместимый pg_dump/pg_restore.
4. Восстановить копию в **изолированной** PostgreSQL с отдельными учётными
   данными и отключёнными интеграциями. Сверить количества и контрольные
   выборки таблиц `profiles`, `scheduled_sessions`, `training_cycles`,
   `workouts`, `workout_items`, `workout_sets`, `cardio_sessions`,
   `rest_timers`, `pending_inputs`; проверить сроки и читаемость истории.
   Никогда не восстанавливать старый дамп поверх текущей production БД.
5. Прогнать SQL `migrations/20261023_weekday_schedule.sql` на **копии**:
   повторное применение идемпотентно, данные сохранены, SQL с таймаутами.
   На production схема должна быть подготовлена **до переключения кода**.
   После разрешения на миграцию сверить колонки и constraint только чтением.
6. Автоматические frontend/API/browser и PostgreSQL18 тесты прошли в
   [Actions 40051902656](https://github.com/smirnovka907-crypto/formiq-bot/actions/runs/40051902656).
   **Не заменяют** Android WebView и проверку на восстановленной production-копии.
   Эти два пункта выполнить отдельно с тестовой учётной записью
   (без изменения webhook на другой сервер).
   В Mini App строго три вкладки, план внутри «Тренировок».
7. После разрешения на выпуск merge в `main`, дождаться Render Live
   нужного SHA, проверить health, логи, вход, профиль, тренировку, кардио,
   историю. Не объявлять успех только по состоянию Live.

## Сетевая безопасность

- На 24 октября Render сообщает `ipAllowList: 0.0.0.0/0` для действующей
  PostgreSQL. Сетевая экспозиция сама по себе не отменяет аутентификацию;
  `ssl=on` подтверждён read-only запросом. Не изменять allowlist без
  тестирования доступности текущего Render web-service и отдельного разрешения.
- Render Free PostgreSQL не имеет гарантированного управляемого backup.
  Успех изолированного теста pg_dump/restore не означает, что создана
  резервная копия личных данных, — это остаётся блокером release.

## Безопасный откат

- Откат **не** включает DROP COLUMN, удаление rows или restore старого
  production backup. Сначала заморозить изменения расписания.
- Если новый алгоритм уже присвоил `retired` либо сохранил `weekdays`,
  прямой возврат на старый `main` запрещён: старый код не понимает эти поля.
  Нужен совместимый rollback/hotfix, который скрывает retired, сохраняет
  недельные предпочтения и не переписывает календарь; такой hotfix
  пока **не подготовлен и не протестирован**.
- При неполадках сначала предпочтителен исправляющий forward-deploy той же
  модели данных. Если необходимо возвращаться к прежнему коду — только
  после проверки совместимости на восстановленной **копии** БД, с явным
  разрешением владельца и freeze расписания.
- Для recovery отдельных строк сравнить транзакционные данные с
  исходным snapshot и разработать точечную процедуру. Запрещён откат всей
  БД, который сотрёт новые тренировки, веса или кардио.
- Убедиться, что работающий Telegram webhook всё ещё у единственного бота
  `@formiqcoachbot`, никаких изменений webhook без разрешения.

## Android сегодня, без риска для production

Откройте **существующий** `@formiqcoachbot` в Telegram на Android,
нажмите «FormIQ», пройдите доступные сценарии и отметьте расхождения.
Это проверка текущего **main SHA 11551f4**, НЕ PR #15. В настоящем
Telegram WebView код PR до отдельного развёртывания проверить нельзя;
одновременный второй webhook невозможен. Не создавайте второго бота.

## Что проверяет CI в изоляции

`tests/test_v5_schedule_postgres.py`: использует только
`FORMIQ_TEST_DATABASE_URL` с hostname localhost/127.0.0.1/postgres
и базой с суффиксом `_test`. Временная schema создаётся по UUID.
Тест архивирует schema через pg_dump, удаляет **только её**, восстанавливает
через pg_restore, сравнивает реальные rows. Это моделирует операцию
восстановления, но **не заменяет backup/restore production-копии**.


## Read-only gate to prevent an unsafe code-only downgrade (PR #15)

The checked-in `scripts/rollback_readonly_gate.py` inspects an **isolated restored
PostgreSQL copy**, not the production database. The CLI accepts only a distinct
`FORMIQ_RESTORE_TEST_DATABASE_URL` whose database name ends in `_test` or
`_restore`; it rejects `DATABASE_URL`. All queries use read-only
transactions with lock and statement timeouts, and output only boolean markers
and a status: no chat IDs, personal rows, or credentials.

Example **only after an isolated restore exists**:

```sh
# Supply the secret through a secure shell environment, not through GitHub.
python scripts/rollback_readonly_gate.py
```

- `blocked / v5_schedule_data_present`: some saved weekday selection or
  non-null `schedule_state` exists. **Never** deploy legacy main's scheduler.
- `blocked / partial_v5_schema` or missing tables: refuse rollback.
- `candidate / no_v5_schedule_markers`: neither V5 marker was found in this
  snapshot. **Not** sufficient to certify downgrade, because migration history,
  concurrent writes, actual restore fidelity and old-code behavior must still
  be verified separately.
- `legacy_schema`: the V5 columns are absent on this snapshot. This describes
  an old schema, not a green light for a production deployment.
- Any connection/query error exits non-zero, without printing driver messages
  which might contain passwords/DSNs.

A red gate means **stop**. A green process exit only means the narrow marker
check completed, **not** that rollback is safe or the release is approved.
Production needs an independently tested compatible fallback/hotfix that
preserves retired/manual slots, weekday choices and workouts; no such hotfix has
been shipped. Prefer a controlled forward fix on the V5 data model.

Automated tests exercise the gate on the disposable PG18 `*_test` schema and
verify that SQL write attempts fail inside the audit transaction. This is not a
production backup or a dry run on real customer data.
