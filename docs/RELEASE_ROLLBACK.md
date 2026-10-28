# FORMIQ | PR #37 — межфайловые CSV и реальная резервная готовность, 28.10.2026

**Регламент:** основная Google-инструкция редакция 2.6, решение Управления `NO-GO` до закрытия CSV-коллизий, свежего шифрованного backup и отдельного допуска на точный SHA. История ниже сохранена, приоритетный выпуск PR #37 — этот раздел.

### 1. Решение конфликтов двух разных CSV

- Для CSV с колонками `date,activity,minutes,kcal`, без времени и provider session ID, нельзя автоматически доказать, что одинаковые строки в разных файлах — одна и та же тренировка. Безопасный выбор: при совпадении сначала предупреждение и явный выбор для каждой конфликтной строки: **пропустить** или **сохранить отдельной тренировкой**. Пока выбор `ask`, endpoint возвращает HTTP 409 с номерами строк, **не сохраняя ничего из спорной пачки**. Предпросмотр read-only; после пользовательских исправлений backend повторяет проверку под owner advisory transaction lock (защита от гонки).
- `cardio_sessions.import_canonical` сохраняет исходный нормализованный отпечаток для сравнения даже после выбора «отдельно». `import_file_hash` (SHA-256 исходного файла) и `import_row_no` образуют owner-scoped partial UNIQUE для повторного импорта **точно того же** файла; новая отдельная запись имеет детерминированный `import_fingerprint` от файла, индекса и канонической записи. Данные исходного CSV не сохраняются. Первые legacy CSV fingerprints по-прежнему сравниваются, чтобы не потерять старые записи.
- При повторе одного и того же файла даже после выбора «отдельно» дополнительные строки не создаются; две одинаковые строки в одном файле остаются отдельными сессиями; владелец не может видеть чужие записи. Ккал устройства — только `reported_kcal`; MET/estimated_kcal остаются NULL.
- Ограничение: изменение фактического содержимого CSV даёт другой SHA-256. Без идентификатора события из поставщика пользовательский выбор остаётся единственным доказательством отдельной активности — приложение **не утверждает**, что записи автоматически безошибочно дедуплицированы между всеми файлами.
- Миграция только аддитивная: +nullable `import_file_hash` TEXT, `import_row_no` INTEGER, `import_canonical` TEXT и 2 индекса к ранее уже запланированным `reported_kcal`, `intensity`, `import_fingerprint`. `init_db` должно быть идемпотентно, существующие `workouts`, `workout_sets`, `cardio_sessions` не очищать. UI сохраняет существующие 3 вкладки и дизайн.

### 2. Backup — текущий фактический статус и безопасная инструкция

- Существующий `scripts/formiq_pg_backup.py` использует `pg_dump` / `pg_restore` строго версии 18, скрытый ввод DSN/фразы (не передавать в чат), AES-256-GCM + scrypt, делает приватный `.partial` с последующим атомарным rename после полной проверки тега GCM и `pg_restore --list`; выводит SHA-256 **зашифрованного** архивного файла. Команда `restore` запрещает любые не-локальные цели и требует заранее созданную **пустую LOCAL `*_restore`** PostgreSQL18. Исходный production через `pg_dump` — only read. Скрипт требует клиента PostgreSQL18 и `requirements-backup.txt`; архив нельзя хранить в GitHub или пересылать как открытый дамп.
- Проверенный 27.10.2026 архив `formiq-production-20261027T160419Z-0c5338df.fiqenc` остаётся в закрытой существующей папке Google Drive и был ранее восстановлен локально. 28.10.2026 осмотр существующей закрытой папки показал **только этот архив**; новой версии после 27.10 в ней нет. Следовательно **FRESH BACKUP: NOT CONFIRMED**, `SHA256` нового файла и `ISOLATED RESTORE` новой версии **NOT RUN**, выпуск **NO-GO**. Разрешённого способа безопасно выполнить `pg_dump` через текущие Render tools нет: они предоставляют лишь SQL-запросы в read-only транзакции, а не передают закрытый поток dump в локальное шифрование. Нельзя выгружать содержимое пользователей через JSON/логи/GitHub/чат вместо backup.
- Для владельца/уполномоченного оператора на личном доверенном компьютере, где исходный Render EXTERNAL PostgreSQL URL и отдельная сохранённая приватная парольная фраза доступны **локально**, использовать ранее проверенный механизм (не помещая ни один секрет в CLI или чат):
  `py scripts\formiq_pg_backup.py backup --directory "%USERPROFILE%\FORMIQ-private-backups"`
  затем `py scripts\formiq_pg_backup.py verify "<ПУТЬ_К_НОВОМУ_.fiqenc>"`
  затем `py scripts\formiq_pg_backup.py restore "<ПУТЬ_К_НОВОМУ_.fiqenc>"` только в заранее согласованную **пустую изолированную LOCAL *_restore** базу; если нет пустой цели — не перезаписывать старую `formiq_restore` и **сначала согласовать** временную локальную копию без создания новых облачных БД. Сверить количество таблиц, constraints, последовательностей, исторических записей; записать неперсональные агрегаты, SHA256 шифртекста, дату UTC, исходный exact production SHA и код `LOCAL_ISOLATED_PG18_RESTORE_COMPLETED`. Перенести только `.fiqenc` в существующую закрытую папку Google Drive, проверить побайтовое совпадение, не удалять старую подтверждённую точку.
- После выполнения нужны **только отметки подтверждения**, не ключи, DSN или сами пользовательские записи. Backup от 27.10 не является свежим, соответствующим текущему состоянию production.
- Render PostgreSQL 18.6 проверена `read-only` после последнего merge: на момент запроса **38 таблиц, 1 workout, 6 sets, 0 cardio**; в `cardio_sessions` существует лишь 1 из 6 полей нового CSV-составa. Это схема и агрегатная сохранность **на один момент времени**, не checksum/полная копия и не гарантия отсутствия будущих записей.

### 3. Выпуск и откат

- Код и тесты проверять на конечном точном SHA: Python, API, JS, PostgreSQL18, mobile Chromium, конфликт раздельных файлов и повтор одного файла, миграция и сохранение истории. Тестовый CI не равен реальной Telegram Android/iOS приёмке.
- Перед merge обновить свежую резервную копию, checksum и изолированный restore; удостовериться, что проверенный архив и ключ физически находятся в двух разных безопасных местах, подготовить кодовый rollback на опубликованный `main` / Render Live `d53b6106a26d61e32526d78dfb3af5688a03ad8f` (перепроверить непосредственно перед публикацией).
- Только после подтверждения backup и явного разрешения владельца на конкретный PR HEAD и штатный Render auto-deploy выполнить один merge. После Live сравнить exact SHA, startup логи, HTTP, только read-only агрегатные проверки таблиц и истории. При ошибке откатывать только код, не перезаписывать production старым дампом, сохранять аддитивные поля и записи.
- Никакие новые сервисы/платные ресурсы/webhook, новый PR, изменение дизайна и OCR скриншотов в этом этапе не допускаются. **Нет допуска → нет merge/deploy.**

---

# FORMIQ | PR #37 — допуск CSV/ккал устройства и безопасный откат (28.10.2026)

**Рабочий документ для текущей ветки.** Следующие исторические разделы о PR #31/#34 и прежних SHA сохранены для восстановления хронологии, но к выпуску PR #37 относятся правила ниже.

**Границы:** один действующий Draft PR [#37](https://github.com/smirnovka907-crypto/formiq-bot/pull/37), один существующий Mini App и Telegram `@formiqcoachbot`. Main/Render до отдельного разрешения оставлять на опубликованном `d53b6106a26d61e32526d78dfb3af5688a03ad8f`; перед потенциальным выпуском заново сверить актуальный Live SHA. Не создавать новый бот, PR, базу, webhook, сервер, не смешивать PR #30/#25/#36 и не менять 3 вкладки или утверждённый дизайн.

**Проверять до одобрения merge:**
1. Ручной ввод дополнительных тренировок: без устройства — только примерный MET-расход; с `device_kcal` 0–5000 — `reported_kcal` с отображением «введено пользователем», при этом `estimated_met` и `estimated_kcal` NULL и никакого суммирования двух источников. Старые записи с MET не переписываются, owner isolation в карточках истории и отдельной странице.
2. CSV `date,activity,minutes,kcal`: UTF-8, до 64 КБ/30 строк, дата `YYYY-MM-DD`, минуты 1–300, ккал 0–5000 за **конкретную активность**, не за сутки. Предпросмотр без записи; пользователь исправляет значения; затем явно подтверждает; сервер заново проверяет тот же SHA-256 файла, каждую правку и профильный часовой пояс. Не сохранять исходный CSV и не отправлять его во внешние AI.
3. Повторный импорт **того же** подтверждённого файла: `0` новых записей, `duplicates` равен ранее импортированным; конкурентность защищена уникальным PostgreSQL индексом `(chat_id,import_fingerprint)`. Несколько одинаковых строк **в одном CSV** — разные реальные занятия и получают разные deterministic fingerprints по номеру повторения. Важное остающееся ограничение: у четырёх колонок нет времени старта/ID сессии; при полной идентичности записей **в разных файлах** определить, две это разные тренировки или один повторный экспорт, строго невозможно. До следующего согласованного формата не выдавать дедупликацию между разными файлами за безошибочную; случаи раздельных экспортов принимать через ручное создание/изменение отличающегося описания.
4. Сбой сети после подтверждения: повторный запрос не создаёт копии. Поздний предпросмотр ранее выбранного файла не подменяет новый; после успешного server-save неудача обновления state/history не должна выдавать ошибку сохранения. Подтверждённая история остаётся в базе.
5. Время: даты интерпретируются в `profile_metrics.timezone`, для CSV без времени выбирается полдень локального дня (техническая конвенция, **не фактическое время тренировки**) и затем UTC; DST проверить в тестах. Нельзя домысливать время активности, выводы о хронологии внутри дня делать осторожно.
6. PostgreSQL 18: только аддитивные nullable `cardio_sessions.reported_kcal`, `intensity`, `import_fingerprint`, частичный UNIQUE индекс по владельцу; `init_db()` повторяем без удаления истории. Run migrations в изолированном PG18; проверить историю ручных тренировок и предыдущие `estimated_kcal` с NULL для новых устройств.

**Резервная копия/откат:** проверенный шифрованный production архив 27.10.2026 хранится в закрытой папке, локальное восстановление уже подтверждено владельцем (37 таблиц/218 ограничений/12 последовательностей/4 связи на дату копии), но после выпуска #34 production схема изменилась. Старый архив **не является актуальной полной копией на 28.10.2026**. Перед новым production merge желательно сделать актуальный зашифрованный backup с проверкой restore или документированную проверку бэкап-политики; не раскрывать URL с ключами, пароли и пользовательские данные в PR. При неполадках фиксировать Live/CI/SHA и логи и по отдельному разрешению откатывать код на проверенный предыдущий Live SHA **без перезаписи новых записей БД**, сохраняя nullable аддитивные колонки и индекс. Запрещено восстанавливать старый дамп поверх изменившихся пользовательских данных; data rollback только отдельным согласованным безопасным планом с freeze/reconciliation.

**План после разрешённого выпуска:** штатный Render auto-deploy один раз, сверить exact `main` SHA == Render Live SHA, startup, `HEAD /`, `GET /`, `/wake` (если можно безопасно), read-only схема и подсчёт существующих тренировок, отсутствие новых ERROR логов. После публикации владелец отдельно проверяет Android/iOS Telegram: ккал вручную и источник, CSV предпросмотр/правки/повтор, история, 3 вкладки, клавиатура, малый экран. GitHub Chromium CI не заменяет фактическую приёмку. Скриншоты и произвольные FIT/TCX/PDF — другой этап.

**Статус:** выпуск НЕ санкционирован этим документом. На каждый точный PR SHA и связанный Render auto-deploy требуется отдельное явное разрешение владельца.

---

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
