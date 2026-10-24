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
- Изолированные тесты PostgreSQL 16 в CI, JavaScript runtime/Chromium
  360×740 и 393×852, API и миграции. Последний baseline:
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

## Разграничение уровней проверки

- Код в PR: да. Ветка не объединена с main.
- CI success для baseline и wake callback fix: да.
- Новые проверки dump/restore, ограниченного DDL и итоговый workflow:
  требуют подтверждения последнего Actions run.
- Реальный restore **копии production**: НЕ проводился.
- Telegram Android WebView именно для кода PR: НЕ проверен.
- Пользовательская визуальная приёмка: НЕ пройдена.
- Published in Render: только **старый main**, не PR.

## Подтверждённые риски и блокеры

- PostgreSQL **18** в production и **16** в текущем Actions-контейнере:
  сопоставимость проверяется логикой тестов, но PG18 E2E до выпуска обязателен.
- Бесплатная БД имеет дату окончания 19 ноября 2026; наличие полноценного
  восстановимого backup на стороне Render **не подтверждено**. Директория
  с названием «резервные копии» не доказывает существование backup.
- Старое приложение не понимает `retired` и выбранные `weekdays`.
  Кодовый откат после реального переноса расписания небезопасен без
  совместимого хотфикса/заморозки изменений. Колонки не удалять.
- Render production logs: 23 октября два примера старого wake callback 400;
  веточное исправление ещё не опубликовано. Отдельно измерить задержку API
  `/mini/api` на холодном старте.
- Существующий бот имеет единственный webhook. Нельзя направить его сразу на
  два независимых backend. Проверка PR на том же боте требует согласованного
  временного production переключения после backup — **не выполнять сейчас**.

## Следующий этап / release gate

1. Получить зелёный последний GitHub Actions, проверить реально выполненный
   dump/restore в disposable test DB и логи PG-сервиса.
2. По отдельному разрешению сделать защищённый backup production (read-only)
   и проверить восстановление копии в изолированной БД без записи в production.
3. Подтвердить совместимый откат с `retired`/новыми weekdays и работу на PG18.
4. Ручная проверка в настоящем Telegram Android WebView и согласование
   Aluminium v5 пользователем; не выдавать Chromium за Telegram.
5. Лишь после нового разрешения: решение о merge PR #15 и публикации текущего
   `@formiqcoachbot`. Не создавать другого бота или платные ресурсы.

**Статус: релиз заблокирован до выполнения gate.**
