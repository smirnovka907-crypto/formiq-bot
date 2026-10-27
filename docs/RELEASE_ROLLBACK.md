# FORMIQ | P0 — единая приёмка Android/iOS и порядок тестового выпуска (27.10.2026)

**Актуальный лист проверки для владельца.** Старые разделы этого файла про PR #15 остаются историей; для текущего P0 действуют пункты ниже и основная инструкция Google Drive редакции 1.7. Существующие production Telegram `@formiqcoachbot`, Render `formiq-bot`, PostgreSQL и `main` без отдельного разрешения не менять. Не открывать дополнительный бот/сервис/БД.

## A. Исходная контрольная точка

- Render Live до будущего выпуска: `f0f46c2b2e598b2e3811fc8af66d5f161a3d8643` — это проверенный исторический SHA на 27.10.2026; перед релизом перепроверить live статус.
- Тренировки: **Draft PR #31**, HEAD `fb238973e7f330e6073acbfaf98a2304b20e62cb`. Питание: **Draft PR #34**, кодовый HEAD `d6c20ba57fa591f4c24dc45b3e3e9cd3ed47ed90` до этого документального изменения.
- Временная интеграционная ветка `test/integration-p31-p34-20261027`, совместный **SHA `f2b5f0cdbbd1704c39ee82ba1a057786b1e4acf2`**, [GitHub Actions #40558470991](https://github.com/smirnovka907-crypto/formiq-bot/actions/runs/40558470991) — **SUCCESS**: Python/API, PostgreSQL 18, JavaScript, mobile Chromium. Ветка не является релизом, PR или разрешением на production-операции.
- Зашифрованный backup production PostgreSQL, локальный restore `LOCAL_RESTORE_RECONCILED`, 37 таблиц / 218 ограничений / 12 последовательностей / 4 связи и побайтовая сверка скачанного из закрытого Google Drive архива подтверждены владельцем. Для реального cutover нужна **новая свежая финальная копия после freeze writes**.

## B. Одинаковая пользовательская приёмка Telegram Android и iOS

Каждый сценарий отдельно пройти **дважды: на реальном Android Telegram и реальном iOS Telegram**, только после отдельно одобренного тестового выпуска; GitHub Actions mobile Chromium — вспомогательная симуляция, не заменяет это. До старта записать устройство, версию ОС, версию Telegram, дату, часовой пояс аккаунта, SHA Render Live. Вести фактическую отметку `Android: PASS/FAIL/NOT RUN` и `iOS: PASS/FAIL/NOT RUN` с номером ошибки/скриншотом без персональных медицинских данных или секретов.

1. **Полная тренировка.** Начать запланированный день, подтвердить все подходы с весом/повторами, завершить. В «Прогресс → История» и календаре виден тот же день и точные результаты; при повторном открытии ничего не теряется.
2. **Частичная тренировка и пропуск.** Записать один подход, затем нажать «Пропустить/Отменить» и подтвердить. Первый подход, вес, повторения и дата остаются в истории; остальные подходы не выдаются за выполненные. Профиль/план не удаляются.
3. **Ноль подходов, раннее завершение и повторный запрос.** Начать, завершить без подходов, проверить «без подходов» и историю; повторить действие/запрос после закрытия — не появляется вторая запись и не закрывается новая тренировка.
4. **Два продукта одной фразой.** В «Питание» ввести «курица 150 г и рис сухой 80 г», один раз нажать «Сохранить». Оба продукта или исходный текст с явной необходимостью уточнения сохраняются сразу; запроса ожидания Yandex AI перед сохранением нет.
5. **Достоверный КБЖУ.** Для продукта с подтверждённым `FatSecret food.get.v5` проверить пищевую форму, `food_id/serving_id`, массу, источник и ккал/Б/Ж/У; значения пересчитываются по фактическим граммам. Если официальный источник недоступен — не показывать вымышленный полный итог. Проверить вручную исправляемые данные.
6. **Неизвестное смешанное блюдо.** «Домашний салат 250 г» или блюдо без проверенного состава сохраняется как raw text; UI предупреждает о неполном КБЖУ, не ставит 0 ккал и не объявляет сумму полной. Уточнение не удаляет первоначальный текст.
7. **Задержанный FatSecret.** Запустить обогащение, изменить название/вес либо вручную заполнить КБЖУ до ответа. Запоздалый API не изменяет ручной выбор. Повторный расчёт отражает актуальную версию записи.
8. **Потеря сети.** Выключить сеть до ответа на сохранение, вернуться онлайн, открыть Mini App заново и безопасно повторить действие. Предыдущее подтверждённое сохранение остаётся; идемпотентный повтор не создаёт дубль. Несохранённое не обозначается сохранённым.
9. **Малый экран и элементы управления.** Проверить на узком экране (~360–393 px): виртуальная клавиатура, поля веса/питания, календарь, скролл, Telegram safe area и фиксированные нижние вкладки. Никаких перекрытий, уходящих кнопок и случайной потери введённого текста.
10. **Правдивые подключения.** В профиле и питании не показывать FatSecret/Garmin как подключённые, если не подтверждена действующая связь и доступность. Неактивные функции не маскируются «живыми» данными; отсутствие внешнего API не блокирует ручной дневник.

**Приёмка ещё НЕ пройдена**, пока владелец не вернул фактические результаты обоих устройств. Реальное сравнение подключений требует разрешённых рабочих ключей/согласий, не публиковать секреты или пользовательские данные в GitHub.

## C. Один вариант подготовки тестового выпуска — без выполнения

1. Зафиксировать точные актуальные SHA **обоих** PR и `main`; обновить временную интеграционную сборку после любых новых изменений кода, получить зелёный CI **на конечном совместном SHA**; отдельно проверить UI на Android и iOS после тестового выпуска.
2. Перед работой с production получить свежую зашифрованную копию PostgreSQL (без публикации паролей), сверить checksum, успешно восстановить изолированно и проверить объём/права/план отката. Для миграции провайдера отдельно остановить записи, сделать финальный write-frozen backup, повторить контроль.
3. PostgreSQL PR #34: **только аддитивные изменения**, если их нет в production: `manual_food_meals.raw_input_text`, `manual_food_meals.unresolved_fragments JSONB`, `food_save_requests` и `request_hash`; PR #31 новых DDL не требует. Проверить идемпотентность `CREATE/ALTER IF NOT EXISTS` на копии PostgreSQL 18, старые профили и значения. Существующие данные, подходы и журнал питания не удалять.
4. Для **каждого** merge и связанного Render auto-deploy запросить **отдельное явное одобрение владельца**. Возможный порядок: PR #31 → контроль Live/истории → пересборка интеграционной проверки после обновления main → PR #34 → контроль питания. Не называть два green PR одним разрешённым выпуском, не открывать дубликатов PR.
5. После каждого разрешённого выпуска проверить Render **точный Live SHA**, успешный деплой и логи, `/` и `/wake` (с учётом cold-start Render Free), старт Mini App, доступность существующей PostgreSQL, старые записи и новую запись; затем сценарии B на реальных устройствах. CI сам по себе не доказывает работу Telegram.
6. При сбое **не откатывать БД поверх новых записей**. Немедленно зафиксировать Live SHA, логи и симптом, прекратить опасные изменения; по отдельному разрешению откатить только код на заранее зафиксированный SHA/commit при сохранении аддитивных столбцов и всех пользовательских записей. Если проблема в данных, сначала безопасный freeze, экспорт свежих изменений и согласованный план восстановления с reconciliation. Не удалять и не пересоздавать production БД.
7. Не включать аллергенную функцию PR #30 до юридического допуска, согласий и надёжного состава; не менять тариф, webhook, инфраструктуру и не покупать ресурсы в рамках этого плана.

## D. Честный статус готовности

Совместный offline CI: **PASS** на `f2b5f0cdbbd1704c39ee82ba1a057786b1e4acf2`. Yandex AI и FatSecret проверены **только изолированными mock-ответами**; реальная санкционированная проверка API/ключей, лицензирования хранения результатов и Telegram Android/iOS остаётся блокером полной пользовательской приёмки. Никаких merge/main/Render production writes не выполнено.

---

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


## Emergency V5-compatible fallback (`FORMIQ_SCHEDULE_SAFE_MODE=1`)

PR #15 implements a reversible **schedule freeze** in the V5 application,
rather than downgrading to legacy `main` which does not understand
`weekdays` or `schedule_state='retired'`. This is an emergency
**forward-compatible hotfix path**, not an old-code downgrade. Keep the V5
database schema and all existing records intact.

When the env flag equals exactly `1`:
- Read/display existing calendar entries as stored, excluding `retired`.
  Manual dates remain visible, and existing workout history remains in place.
- Refuse onboarding edits and manual schedule moves with an explicit error.
- Skip all automatic schedule reconciliation, inserting or retiring slots.
- Refuse creation of a new training cycle, including after the old cycle
  expires; never synthesize the next cycle from potentially mismatched data.
- Existing completed/active workouts, weights and cardio are not deleted or
  rewritten by this switch. Existing application APIs otherwise remain V5.
  Training availability after cycle expiry is intentionally reduced.

**Activation is a production configuration/redeployment action, NOT
authorized in this preparation phase.** It must only be considered if a
verified protected production backup and successful isolated restore exist,
CI confirms exact release SHA, real operator approval is recorded and
Render deployment is monitored. Changing this env value on Render may itself
trigger a new deployment; never toggle it casually.

To recover normal operation after the cause of the incident is addressed,
restore the value to `0` (or remove it) in a separately approved deployment.
Do not change `main`, drop columns, delete `retired` rows, reset user
profiles, or restore an older snapshot over live user entries.

Integration regression on disposable PostgreSQL 18 tests the freeze against
manually rescheduled dates, retired future slots, the exact 4-week cycle ID,
forbidden edits and frozen-after-expiry behavior. The real production
backup/restore rehearsal and Android postrelease acceptance remain NO-GO
until independently verified.
