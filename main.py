
import os
import hashlib
import hmac
import logging

import psycopg
import telebot
from flask import Flask, request, abort
from telebot import types

logging.basicConfig(level=logging.INFO)

TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
DATABASE_URL = os.environ["DATABASE_URL"]

URL = os.environ.get(
    "RENDER_EXTERNAL_URL",
    "https://formiq-bot.onrender.com"
).rstrip("/")

SECRET = hashlib.sha256(TOKEN.encode()).hexdigest()

bot = telebot.TeleBot(TOKEN, threaded=False)
app = Flask(__name__)

QUESTIONS = [
    (
        "goal",
        "Какая у тебя цель?",
        [
            ("Похудеть", "loss"),
            ("Набрать мышцы", "muscle"),
            ("Стать выносливее", "endurance"),
            ("Поддерживать форму", "general")
        ]
    ),
    (
        "level",
        "Какой у тебя опыт?",
        [
            ("Новичок", "beginner"),
            ("Иногда тренируюсь", "some"),
            ("Регулярно тренируюсь", "experienced")
        ]
    ),
    (
        "days",
        "Сколько тренировок в неделю?",
        [
            ("2 дня", "2"),
            ("3 дня", "3"),
            ("4 дня", "4"),
            ("5 дней", "5")
        ]
    ),
    (
        "equipment",
        "Где тренируешься?",
        [
            ("Дома без инвентаря", "home"),
            ("Дома с инвентарём", "homegear"),
            ("В спортзале", "gym")
        ]
    ),
    (
        "age_group",
        "Тебе уже есть 18 лет?",
        [
            ("Да, мне 18+", "adult"),
            ("Нет", "minor")
        ]
    ),
    (
        "minutes",
        "Сколько минут есть на тренировку?",
        [
            ("20 минут", "20"),
            ("30 минут", "30"),
            ("45 минут", "45"),
            ("60 минут", "60")
        ]
    ),
    (
        "clearance",
        "Есть ли боль, травма или ограничение, "
        "из-за которого нагрузка может быть "
        "небезопасной?",
        [
            ("Нет, ограничений не знаю", "none"),
            ("Да, есть ограничения", "yes"),
            ("Не уверен(а)", "unsure")
        ]
    )
]

FIELDS = [item[0] for item in QUESTIONS]

LABELS = {
    (field, val): label
    for field, _, choices in QUESTIONS
    for label, val in choices
}

TITLES = [
    "Цель",
    "Опыт",
    "Дней в неделю",
    "Место",
    "Возраст",
    "Длительность",
    "Ограничения"
]


def connect():
    return psycopg.connect(
        DATABASE_URL,
        connect_timeout=10
    )


def init_db():
    with connect() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS profiles (
                chat_id BIGINT PRIMARY KEY,
                goal TEXT,
                level TEXT,
                days TEXT,
                equipment TEXT,
                updated_at TIMESTAMPTZ DEFAULT NOW()
            )
        """)

        for field in (
            "age_group",
            "minutes",
            "clearance"
        ):
            conn.execute(
                f"ALTER TABLE profiles "
                f"ADD COLUMN IF NOT EXISTS {field} TEXT"
            )

        conn.execute("""
            CREATE TABLE IF NOT EXISTS workouts (
                id BIGSERIAL PRIMARY KEY,
                chat_id BIGINT NOT NULL,
                plan_day TEXT NOT NULL,
                started_at TIMESTAMPTZ
                    NOT NULL DEFAULT NOW(),
                finished_at TIMESTAMPTZ,
                difficulty TEXT,
                status TEXT NOT NULL DEFAULT 'active'
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS workout_items (
                workout_id BIGINT NOT NULL
                    REFERENCES workouts(id)
                    ON DELETE CASCADE,
                position INT NOT NULL,
                exercise TEXT NOT NULL,
                target TEXT NOT NULL,
                done BOOLEAN NOT NULL DEFAULT FALSE,
                PRIMARY KEY (workout_id, position)
            )
        """)

        conn.execute("""
            CREATE INDEX IF NOT EXISTS workouts_chat_idx
            ON workouts(chat_id, started_at DESC)
        """)


def profile_for(chat_id):
    with connect() as conn:
        row = conn.execute(
            """
            SELECT goal, level, days, equipment,
                   age_group, minutes, clearance
            FROM profiles
            WHERE chat_id=%s
            """,
            (chat_id,)
        ).fetchone()

    return dict(zip(FIELDS, row)) if row else {}


def save_answer(chat_id, field, value):
    if field not in FIELDS:
        return

    with connect() as conn:
        conn.execute(
            """
            INSERT INTO profiles(chat_id)
            VALUES (%s)
            ON CONFLICT DO NOTHING
            """,
            (chat_id,)
        )

        conn.execute(
            f"UPDATE profiles SET {field}=%s, "
            "updated_at=NOW() WHERE chat_id=%s",
            (value, chat_id)
        )


def reset_profile(chat_id):
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO profiles(chat_id)
            VALUES (%s)
            ON CONFLICT(chat_id)
            DO UPDATE SET
                goal=NULL,
                level=NULL,
                days=NULL,
                equipment=NULL,
                age_group=NULL,
                minutes=NULL,
                clearance=NULL,
                updated_at=NOW()
            """,
            (chat_id,)
        )


def kb(*buttons):
    markup = types.InlineKeyboardMarkup(row_width=1)

    for label, data in buttons:
        markup.add(
            types.InlineKeyboardButton(
                label,
                callback_data=data
            )
        )

    return markup


def ask(chat_id, index):
    if index == len(QUESTIONS):
        show_profile(chat_id)
        return

    _, prompt, options = QUESTIONS[index]

    buttons = [
        (label, f"answer:{index}:{value}")
        for label, value in options
    ]

    bot.send_message(
        chat_id,
        f"Вопрос {index + 1} из {len(QUESTIONS)}"
        f"\n\n{prompt}",
        reply_markup=kb(*buttons)
    )


def show_profile(chat_id):
    p = profile_for(chat_id)

    if not p:
        bot.send_message(
            chat_id,
            "Профиля нет. Напиши /start"
        )
        return

    lines = [
        f"• {title}: "
        f"{LABELS.get((field, p.get(field)), '—')}"
        for title, field in zip(TITLES, FIELDS)
    ]

    bot.send_message(
        chat_id,
        "👤 Профиль FORMIQ\n\n"
        + "\n".join(lines)
        + "\n\n💾 Данные сохранены.",
        reply_markup=kb(
            ("🏋️ План и запуск", "plan"),
            ("📊 Дневник", "history"),
            ("🔄 Новая анкета", "restart")
        )
    )


def plan_data(p):
    if any(not p.get(field) for field in FIELDS):
        return None, (
            "Заполни все вопросы анкеты через /start."
        )

    if p["age_group"] != "adult":
        return None, (
            "Тестовые тренировочные планы FORMIQ "
            "предназначены только для 18+."
        )

    if p["clearance"] != "none":
        return None, (
            "При боли, травмах или сомнениях "
            "в безопасности нагрузки план не выдаю. "
            "Сначала уточни допустимые нагрузки "
            "со специалистом."
        )

    beginner = p["level"] == "beginner"
    minutes = int(p["minutes"])

    sets = 2 if beginner or minutes == 20 else 3

    if p["equipment"] == "gym":
        a = [
            "Жим ногами с лёгким весом",
            "Тяга верхнего блока",
            "Жим от груди в тренажёре",
            "Ягодичный мост"
        ]

        b = [
            "Степ-ап на низкую платформу",
            "Горизонтальная тяга",
            "Жим гантелей с лёгким весом",
            "Птица-собака"
        ]

    else:
        a = [
            "Приседания к стулу",
            "Отжимания от стены",
            "Ягодичный мост",
            "Птица-собака"
        ]

        b = [
            "Подъём на невысокую ступень",
            "Отжимания от высокой опоры",
            "Подъём на носки",
            "Планка у стены"
        ]

    count = 3 if minutes == 20 else 4

    def make(items):
        result = []

        for exercise in items[:count]:
            if "Планка" in exercise:
                amount = f"{sets} × 15–30 сек"
            else:
                amount = f"{sets} × 8–12"

            result.append((exercise, amount))

        return result

    return {
        "A": make(a),
        "B": make(b)
    }, None


def show_plan(chat_id):
    p = profile_for(chat_id)
    plans, error = plan_data(p)

    if error:
        bot.send_message(chat_id, error)
        return

    minutes = int(p["minutes"])

    days = min(
        int(p["days"]),
        3 if p["level"] == "beginner" else 4
    )

    lines = [
        f"🏋️ Пример плана: {days} занятий "
        f"в неделю, по {minutes} мин.",
        "Разминка 3–5 мин, заминка 2–3 мин. "
        "Отдых 45–75 сек.",
        "Делай движения спокойно, без боли, "
        "оставляя запас сил."
    ]

    for name, items in plans.items():
        lines.append(f"\nДень {name}:")

        lines.extend(
            f"• {ex}: {amount}"
            for ex, amount in items
        )

    lines.append(
        "\nЧередуй A/Б с днём восстановления "
        "между силовыми. Для 20 минут оставлены "
        "3 упражнения; при нехватке времени "
        "сокращай подходы, а не разминку."
    )

    lines.append(
        "При боли, головокружении или необычной "
        "одышке остановись. Это стартовый шаблон, "
        "не медицинское назначение."
    )

    bot.send_message(
        chat_id,
        "\n".join(lines),
        reply_markup=kb(
            ("▶️ Начать день A", "begin:A"),
            ("▶️ Начать день Б", "begin:B"),
            ("📊 Дневник", "history")
        )
    )


def active_workout(chat_id):
    with connect() as conn:
        return conn.execute(
            """
            SELECT id FROM workouts
            WHERE chat_id=%s AND status='active'
            ORDER BY id DESC
            LIMIT 1
            """,
            (chat_id,)
        ).fetchone()


def start_workout(chat_id, day):
    p = profile_for(chat_id)
    plans, error = plan_data(p)

    if error:
        bot.send_message(chat_id, error)
        return

    if active_workout(chat_id):
        bot.send_message(
            chat_id,
            "У тебя уже есть начатая тренировка. "
            "Открой /workout и заверши её."
        )
        return

    with connect() as conn:
        workout_id = conn.execute(
            """
            INSERT INTO workouts(chat_id, plan_day)
            VALUES (%s, %s)
            RETURNING id
            """,
            (chat_id, day)
        ).fetchone()[0]

        for index, (exercise, amount) in enumerate(
            plans[day]
        ):
            conn.execute(
                """
                INSERT INTO workout_items(
                    workout_id, position,
                    exercise, target
                )
                VALUES (%s, %s, %s, %s)
                """,
                (workout_id, index, exercise, amount)
            )

    show_workout(chat_id, workout_id)


def show_workout(chat_id, workout_id):
    with connect() as conn:
        row = conn.execute(
            """
            SELECT plan_day, status
            FROM workouts
            WHERE id=%s AND chat_id=%s
            """,
            (workout_id, chat_id)
        ).fetchone()

        if not row:
            bot.send_message(
                chat_id,
                "Тренировка не найдена."
            )
            return

        items = conn.execute(
            """
            SELECT position, exercise, target, done
            FROM workout_items
            WHERE workout_id=%s
            ORDER BY position
            """,
            (workout_id,)
        ).fetchall()

    day, status = row

    state = (
        "идёт" if status == "active"
        else "завершена"
    )

    lines = [
        f"🏋️ Тренировка {day} — {state}"
    ]

    buttons = []

    for pos, exercise, target, done in items:
        mark = "✅" if done else "⬜"

        lines.append(
            f"{mark} {exercise}: {target}"
        )

        if status == "active" and not done:
            buttons.append(
                (
                    f"✅ Выполнил: {exercise[:35]}",
                    f"done:{workout_id}:{pos}"
                )
            )

    if status == "active":
        buttons.append(
            (
                "🏁 Завершить тренировку",
                f"finish:{workout_id}"
            )
        )

    bot.send_message(
        chat_id,
        "\n".join(lines),
        reply_markup=kb(*buttons) if buttons else None
    )


def mark_done(chat_id, workout_id, position):
    with connect() as conn:
        conn.execute(
            """
            UPDATE workout_items SET done=TRUE
            WHERE workout_id=%s AND position=%s
            AND EXISTS (
                SELECT 1 FROM workouts
                WHERE id=%s AND chat_id=%s
                AND status='active'
            )
            """,
            (workout_id, position, workout_id, chat_id)
        )

    show_workout(chat_id, workout_id)


def finish_workout(chat_id, workout_id):
    with connect() as conn:
        row = conn.execute(
            """
            UPDATE workouts
            SET status='finished',
                finished_at=NOW()
            WHERE id=%s AND chat_id=%s
            AND status='active'
            RETURNING id
            """,
            (workout_id, chat_id)
        ).fetchone()

    if not row:
        bot.send_message(
            chat_id,
            "Эта тренировка уже завершена "
            "или не найдена."
        )
        return

    bot.send_message(
        chat_id,
        "🏁 Тренировка сохранена! "
        "Как тебе нагрузка?",
        reply_markup=kb(
            ("Легко 🙂", f"rate:{workout_id}:easy"),
            ("Нормально 💪", f"rate:{workout_id}:ok"),
            ("Тяжело 😮‍💨", f"rate:{workout_id}:hard")
        )
    )


def rate_workout(chat_id, workout_id, rating):
    if rating not in ("easy", "ok", "hard"):
        return

    with connect() as conn:
        row = conn.execute(
            """
            UPDATE workouts SET difficulty=%s
            WHERE id=%s AND chat_id=%s
            AND status='finished'
            RETURNING id
            """,
            (rating, workout_id, chat_id)
        ).fetchone()

    if row:
        bot.send_message(
            chat_id,
            "✅ Оценка записана. "
            "Посмотреть историю: /progress"
        )
    else:
        bot.send_message(
            chat_id,
            "Не удалось найти завершённую тренировку."
        )


def history(chat_id):
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT
                w.plan_day,
                w.started_at,
                w.finished_at,
                w.difficulty,
                count(i.position),
                count(i.position) FILTER (WHERE i.done)
            FROM workouts w
            LEFT JOIN workout_items i
                ON i.workout_id=w.id
            WHERE w.chat_id=%s
            AND w.status='finished'
            GROUP BY w.id
            ORDER BY w.started_at DESC
            LIMIT 10
            """,
            (chat_id,)
        ).fetchall()

    if not rows:
        bot.send_message(
            chat_id,
            "Пока нет завершённых тренировок. "
            "Начни с /plan."
        )
        return

    labels = {
        "easy": "легко",
        "ok": "нормально",
        "hard": "тяжело"
    }

    lines = ["📊 Последние тренировки:"]

    for day, started, finished, diff, total, done in rows:
        lines.append(
            f"• {started:%d.%m} · {day} · "
            f"{done}/{total} упражнений · "
            f"{labels.get(diff, 'без оценки')}"
        )

    bot.send_message(
        chat_id,
        "\n".join(lines)
    )


@bot.message_handler(commands=["start", "help"])
def start(message):
    bot.send_message(
        message.chat.id,
        "💪 FORMIQ — тестовый тренировочный "
        "помощник. Заполни анкету, получи план "
        "и веди дневник.",
        reply_markup=kb(
            ("👤 Профиль", "profile"),
            ("🚀 Анкета", "restart"),
            ("🏋️ План", "plan"),
            ("📊 Прогресс", "history")
        )
    )


@bot.message_handler(commands=["profile"])
def profile_command(message):
    show_profile(message.chat.id)


@bot.message_handler(commands=["plan"])
def plan_command(message):
    show_plan(message.chat.id)


@bot.message_handler(commands=["progress", "history"])
def progress_command(message):
    history(message.chat.id)


@bot.message_handler(commands=["workout"])
def workout_command(message):
    row = active_workout(message.chat.id)

    if row:
        show_workout(message.chat.id, row[0])
    else:
        bot.send_message(
            message.chat.id,
            "Нет активной тренировки. "
            "Начни с /plan."
        )


@bot.message_handler(commands=["delete_me"])
def delete_me(message):
    bot.send_message(
        message.chat.id,
        "Удалить профиль и историю тренировок "
        "FORMIQ?",
        reply_markup=kb(
            ("Да, удалить", "delete_confirm"),
            ("Отмена", "delete_cancel")
        )
    )


@bot.message_handler(commands=["nutrition", "coach"])
def coming_soon(message):
    bot.send_message(
        message.chat.id,
        "Эту функцию добавим позже. "
        "Сейчас доступны /plan, /workout "
        "и /progress."
    )


@bot.callback_query_handler(func=lambda call: True)
def callback(call):
    chat_id = call.message.chat.id
    data = call.data or ""

    bot.answer_callback_query(call.id)

    if data == "restart":
        reset_profile(chat_id)
        ask(chat_id, 0)

    elif data == "profile":
        show_profile(chat_id)

    elif data == "plan":
        show_plan(chat_id)

    elif data == "history":
        history(chat_id)

    elif data == "delete_cancel":
        bot.send_message(
            chat_id,
            "Удаление отменено."
        )

    elif data == "delete_confirm":
        with connect() as conn:
            conn.execute(
                """
                DELETE FROM workout_items
                WHERE workout_id IN (
                    SELECT id FROM workouts
                    WHERE chat_id=%s
                )
                """,
                (chat_id,)
            )

            conn.execute(
                """
                DELETE FROM workouts
                WHERE chat_id=%s
                """,
                (chat_id,)
            )

            conn.execute(
                """
                DELETE FROM profiles
                WHERE chat_id=%s
                """,
                (chat_id,)
            )

        bot.send_message(
            chat_id,
            "Профиль и история занятий удалены "
            "из базы FORMIQ. Сообщения в Telegram "
            "и внешние копии не удаляются."
        )

    elif data.startswith("answer:"):
        try:
            _, index_text, value = data.split(":", 2)
            index = int(index_text)
            field, _, options = QUESTIONS[index]
        except (IndexError, ValueError):
            return

        if value not in {
            item[1] for item in options
        }:
            return

        p = profile_for(chat_id)

        if any(
            not p.get(previous)
            for previous in FIELDS[:index]
        ):
            bot.send_message(
                chat_id,
                "Этот шаг анкеты устарел. "
                "Начни через /start."
            )
            return

        save_answer(chat_id, field, value)
        ask(chat_id, index + 1)

    elif data.startswith("begin:"):
        day = data.split(":", 1)[1]

        if day in ("A", "B"):
            start_workout(chat_id, day)

    elif data.startswith("done:"):
        try:
            _, wid, pos = data.split(":")
            mark_done(
                chat_id,
                int(wid),
                int(pos)
            )
        except ValueError:
            return

    elif data.startswith("finish:"):
        try:
            workout_id = int(data.split(":")[1])
            finish_workout(chat_id, workout_id)
        except ValueError:
            return

    elif data.startswith("rate:"):
        try:
            _, wid, rating = data.split(":")
            rate_workout(
                chat_id,
                int(wid),
                rating
            )
        except ValueError:
            return


@app.get("/")
def health():
    return "FORMIQ online", 200


@app.post("/telegram-webhook")
def webhook():
    received = request.headers.get(
        "X-Telegram-Bot-Api-Secret-Token",
        ""
    )

    if not hmac.compare_digest(
        received,
        SECRET
    ):
        abort(403)

    if not request.is_json:
        abort(415)

    update = types.Update.de_json(
        request.get_data(as_text=True)
    )

    bot.process_new_updates([update])

    return "OK", 200


if __name__ == "__main__":
    init_db()

    bot.set_webhook(
        url=URL + "/telegram-webhook",
        secret_token=SECRET,
        drop_pending_updates=False
    )

    port = int(
        os.environ.get("PORT", 10000)
    )

    app.run(
        host="0.0.0.0",
        port=port,
        debug=False
    )
