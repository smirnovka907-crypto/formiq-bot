# FORMIQ — состояние проекта (24 октября 2026)

> Источник истины: GitHub PR #15 и Render. Документ отражает проверки в рамках
> задачи №1, но не заменяет просмотр свежего HEAD/Actions/Deploy перед выпуском.

## Живые ресурсы и запреты

- Единственный рабочий Telegram-бот: `@formiqcoachbot`. Второго не создаём.
- GitHub: `smirnovka907-crypto/formiq-bot`, production ветка `main`.
- Проверенный `main` на начало проверки: `11551f4305212236ee312b4e970eeb4f040c76a9`.
- Render `formiq-bot`: Live, deployed SHA `11551f4305212236ee312b4e970eeb4f040c76a9`,
  URL `https://formiq-bot.onrender.com`, autodeploy **только с main**.
- PR #15: `fix/v5-native-onboarding-fullscreen-20261023`, Draft, **не merged**.
- PostgreSQL production: `formiq-db`, PostgreSQL **18**, plan **free**,
  status available; Render указывает `expiresAt=2026-11-19T19:50:15Z`.
  Это критичный срок, требующий отдельного решения по сохранению данных.
- Только read-only запросом проверено: в production пока **отсутствуют**
  `profiles.weekdays` и `scheduled_sessions.schedule_state`; старые
  `profiles.days`, `scheduled_sessions.planned_date`, `workout_sets.weight_kg`
  присутствуют. Число строк/содержимое персональных записей не публикуется.
- Никаких production DDL/DML, webhook/token changes, merge и deploy в этой задаче.

## Что уже находилось в PR #15 и повторно не реализовывалось

- Aluminium v5 и три нижние вкладки: **Тренировки / Питание / Прогресс**.
- Анкета первого входа, дни Пн–Вс с проверкой сервера, сохранением JSONB,
  календарь 4 недель, локальные даты и DST.
- Сохранение истории, кардио, подходов и весов. Состояния `auto/manual/retired`,
  защита исторических и вручную перенесённых слотов.
- Базовые тесты PR выполнялись на PostgreSQL 16; после задачи №1
  полный CI переведён на **PostgreSQL 18**. JavaScript runtime/Chromium
  360×740 и 393×852, API и миграции также проверяются. Старый baseline:
  [Actions 39990351894](https://github.com/smirnovka907-crypto/formiq-bot/actions/runs/39990351894),
  success, 103 Python-теста (по отчёту PR).
- `render.android-test*.yaml` — НЕ развернуты; они предполагают иной бот
  и иной сервис. Для этой задачи их не запускать.

## Изменения задачи №1 (только PR #15)

1. [0387c1f](https://github.com/smirnovka907-crypto/formiq-bot/commit/0387c1f69f6be223758274005070f96f9720baf2):
   устаревший wake callback Telegram HTTP 400 больше не считается аварией.
   Неожиданные сбои продолжают логироваться. Добавлены 2 теста.
   [Actions 40049150094](https://github.com/smirnovka907-crypto/formiq-bot/actions/runs/40049150094):
   **success**.
2. [976681c](https://github.com/smirnovka907-crypto/formiq-bot/commit/976681cd3c509231a0b220ae7641cc823c0e0701):
   реальный `pg_dump`/`pg_restore` regression в уникальной **локальной
   тестовой** схеме; после восстановления сравниваются профиль, расписание
   (включая retired), тренировки, подходы/веса и кардио. Результат смотреть
   в Actions для SHA — на момент составления сводки ещё выполнялся.
3. Добавлены ограниченные таймауты ожидания DDL на старте `init_db()`,
   чтобы не зависнуть на блокировке production миграции; guard тест.
4. Документируется последовательность выпуска и недеструктивного отката
   в `docs/RELEASE_ROLLBACK.md`.

## Продолжение задачи №1: проверка на PostgreSQL 18

- [623f03e](https://github.com/smirnovka907-crypto/formiq-bot/commit/623f03ebc4969f6ecac8b3cbf5f0b892f939bcf2):
  GitHub Actions использует временный `postgres:18`; для dump/restore
  применяются двоичные утилиты PG18 внутри контейнера, а не старые
  системные версии runner. Добавлен тест **точного SQL файла миграции**
  на пустых nullable полях старой схемы: повторное применение, сохранность
  профиля/кардио/календаря, ограничение допустимых состояний.
- [de3fa64](https://github.com/smirnovka907-crypto/formiq-bot/commit/de3fa64b79fbdbfcaf6aad0847fa0044c128601f),
  [2cea8c5](https://github.com/smirnovka907-crypto/formiq-bot/commit/2cea8c5b5cd229040500e249cc2bc27bfc1677f3),
  [1425122](https://github.com/smirnovka907-crypto/formiq-bot/commit/1425122d384e0ee559cd735f00880e1bcc59a41e):
  исправления только CI/тестового файла, удаление дублированного фрагмента,
  ранняя проверка Python-синтаксиса. Промежуточные workflow были красными;
  результаты не выдавались за успешные.
- [Actions 40051902656](https://github.com/smirnovka907-crypto/formiq-bot/actions/runs/40051902656)
  — **SUCCESS**, 108/108 Python-тестов, два новых теста
  `test_checked_in_migration_preserves_legacy_data_and_is_idempotent`
  и `test_isolated_pg_dump_restore_preserves_history_and_retired_slots`
  успешно завершились на PostgreSQL 18; JS, браузер, API и Blueprint
  также прошли.
- Production PostgreSQL Render read-only: текущая версия `18.6`, SSL включён,
  рабочие таблицы истории присутствуют. Новых колонок
  `profiles.weekdays` и `scheduled_sessions.schedule_state` нет.
- Никаких production DDL/DML, PR merge, Render deploy, бот-токенов/webhook,
  платных ресурсов и новых Telegram-ботов.

## Разграничение уровней проверки

- Код в PR: да. Ветка не объединена с main.
- CI success для baseline и wake callback fix: да.
- [Actions 40049382250](https://github.com/smirnovka907-crypto/formiq-bot/actions/runs/40049382250),
  HEAD `1d6e2e590e82f5b91a578d71ee20254a4c3cf228`: **success**.
  107 Python-тестов, включая реальный isolated pg_dump/restore и DDL
  timeouts; JS/Chromium и остальные шаги workflow прошли.
- Реальный restore **копии production**: НЕ проводился.
- Telegram Android WebView именно для кода PR: НЕ проверен.
- Пользовательская визуальная приёмка: НЕ пройдена.
- Published in Render: только **старый main**, не PR.

## Подтверждённые риски и блокеры

- PostgreSQL **18.6** в production; изолированные автоматические тесты
  на PostgreSQL **18** пройдены, в том числе backup/restore и
  точный SQL миграции. Совместимость с **реальной копией production**
  и восстановление её данных ещё не подтверждены.
- **Render Free PostgreSQL не поддерживает встроенные backup или PITR**:
  https://render.com/docs/free и https://render.com/docs/postgresql-backups.
  Production pg_dump вне Render **не сделан**. Без защищённой локальной
  резервной копии выпуск заблокирован. До 19 ноября 2026 нужно решить
  судьбу базы: после истечения доступ закрывается, спустя 14 дней grace
  данные могут быть удалены.
- Старое приложение не понимает `retired` и выбранные `weekdays`.
  Кодовый откат после реального переноса расписания небезопасен без
  совместимого хотфикса/заморозки изменений. Колонки не удалять.
- Render Postgres `ipAllowList` в конфигурации содержит `0.0.0.0/0`:
  внешняя сетевая поверхность открыта для соединений с аутентификацией.
  База показывает `ssl=on`. Ограничение публичного доступа требуется
  отдельно спланировать, чтобы не нарушить подключение текущего бота;
  ни один сетевой параметр сейчас не менялся.
- Render production logs: 23 октября два примера старого wake callback 400;
  веточное исправление ещё не опубликовано. Отдельно измерить задержку API
  `/mini/api` на холодном старте.
- Существующий бот имеет единственный webhook. Нельзя направить его сразу на
  два независимых backend. Проверка PR на том же боте требует согласованного
  временного production переключения после backup — **не выполнять сейчас**.

## Следующий этап / release gate

1. **Выполнено в тестах:** успешный CI 40051902656 и фактический
   pg_dump/restore в изолированной PostgreSQL 18. После следующего
   коммита документации повторно проверить HEAD + workflow.
2. По отдельному разрешению сделать защищённый backup production (read-only)
   и проверить восстановление копии в изолированной БД без записи в production.
3. Подтвердить совместимый откат с `retired`/новыми weekdays и работу на PG18.
4. Ручная проверка в настоящем Telegram Android WebView и согласование
   Aluminium v5 пользователем; не выдавать Chromium за Telegram.
5. Лишь после нового разрешения: решение о merge PR #15 и публикации текущего
   `@formiqcoachbot`. Не создавать другого бота или платные ресурсы.

**Статус: релиз заблокирован до выполнения gate.**
