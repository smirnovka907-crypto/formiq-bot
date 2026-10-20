
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
        "Есть ли боль, травма, заболевание или "
        "другое ограничение, из-за которого "
        "нагрузка может быть небезопасной?",
        [
            ("Нет, ограничений не знаю", "none"),
            ("Да, есть ограничения", "yes"),
            ("Не уверен(а)", "unsure")
        ]
    )
]

FIELDS = [q[0] for q in QUESTIONS]

LABELS = {
    (field, value): title
    for field, _, opts in QUESTIONS
    for title, value in opts
}

TITLES = {
    "goal": "Цель",
    "level": "Опыт",
    "days": "Дней в неделю",
    "equipment": "Место",
    "age_group": "Возраст",
    "minutes": "Длительность",
    "clearance": "Ограничения"
}


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


def get_profile(chat_id):
    with connect() as conn:
        row = conn.execute(
            """
            SELECT
                goal,
                level,
                days,
                equipment,
                age_group,
                minutes,
                clearance
            FROM profiles
            WHERE chat_id = %s
            """,
            (chat_id,)
        ).fetchone()

    return dict(zip(FIELDS, row)) if row else {}


def reset_profile(chat_id):
    with connect() as conn:
        conn.execute(
            "DELETE FROM profiles WHERE chat_id=%s",
            (chat_id,)
        )
        conn.execute(
            "INSERT INTO profiles (chat_id) VALUES (%s)",
            (chat_id,)
        )


def save_answer(chat_id, field, value):
    if field not in FIELDS:
        raise ValueError("Bad field")

    with connect() as conn:
        conn.execute(
            """
            INSERT INTO profiles (chat_id)
            VALUES (%s)
            ON CONFLICT DO NOTHING
            """,
            (chat_id,)
        )

        conn.execute(
            f"UPDATE profiles "
            f"SET {field}=%s, updated_at=NOW() "
            f"WHERE chat_id=%s",
            (value, chat_id)
        )


def keyboard(*buttons):
    kb = types.InlineKeyboardMarkup(row_width=1)

    for title, data in buttons:
        kb.add(
            types.InlineKeyboardButton(
                title,
                callback_data=data
            )
        )

    return kb


def ask(chat_id, index):
    if index >= len(QUESTIONS):
        show_profile(chat_id)
        return

    _, prompt, options = QUESTIONS[index]

    kb = keyboard(
        *[
            (title, f"answer:{index}:{value}")
            for title, value in options
        ]
    )

    bot.send_message(
        chat_id,
        f"Вопрос {index + 1} из "
        f"{len(QUESTIONS)}\n\n{prompt}",
        reply_markup=kb
    )


def show_profile(chat_id):
    profile = get_profile(chat_id)

    if not profile:
        bot.send_message(
            chat_id,
            "Профиля ещё нет. Нажми /start"
        )
        return

    lines = [
        f"• {TITLES[field]}: "
        f"{LABELS.get((field, profile.get(field)), '—')}"
        for field in FIELDS
    ]

    bot.send_message(
        chat_id,
        "✅ Твой профиль FORMIQ\n\n"
        + "\n".join(lines)
        + "\n\n💾 Ответы сохранены.",
        reply_markup=keyboard(
            ("🏋️ Мой план", "plan"),
            ("🔄 Заполнить заново", "restart")
        )
    )


@bot.message_handler(commands=["start", "help"])
def start(message):
    bot.send_message(
        message.chat.id,
        "💪 FORMIQ — тренировочный помощник "
        "(тестовая версия).\n\n"
        "Пройди анкету, затем открой /plan.\n"
        "Это не медицинская консультация.",
        reply_markup=keyboard(
            ("🚀 Начать анкету", "restart"),
            ("👤 Мой профиль", "profile"),
            ("🏋️ Мой план", "plan")
        )
    )


@bot.message_handler(commands=["profile"])
def profile_command(message):
    show_profile(message.chat.id)


def plan_text(chat_id):
    p = get_profile(chat_id)

    if any(not p.get(k) for k in FIELDS):
        return (
            "Для плана заполни или обнови "
            "анкету через /start."
        )

    if p["age_group"] != "adult":
        return (
            "Эта тестовая версия предназначена "
            "только для взрослых 18+. "
            "Индивидуальный план не формирую."
        )

    if p["clearance"] != "none":
        return (
            "Пока не составляю программу при "
            "боли, травмах или сомнениях "
            "в безопасности нагрузки. "
            "Обсуди допустимые упражнения "
            "с квалифицированным специалистом."
        )

    gym = p["equipment"] == "gym"
    minutes = int(p["minutes"])
    beginner = p["level"] == "beginner"

    sets = 2 if beginner or minutes <= 20 else 3

    if gym:
        a = [
            "Присед к скамье или жим ногами",
            "Тяга верхнего блока",
            "Жим от груди в тренажёре",
            "Ягодичный мост",
            "Планка 15–30 сек"
        ]
        b = [
            "Степ-ап на невысокую платформу",
            "Горизонтальная тяга",
            "Жим гантелей сидя с лёгким весом",
            "Румынская тяга с лёгким весом "
            "(с инструктором)",
            "Птица-собака"
        ]
    else:
        a = [
            "Приседания к стулу",
            "Отжимания от стены",
            "Ягодичный мост",
            "Птица-собака",
            "Ходьба на месте"
        ]
        b = [
            "Подъём на невысокую ступень",
            "Отжимания от высокой опоры",
            "Подъём на носки",
            "Планка у стены",
            "Ходьба на месте"
        ]

    exercises = [a, b]

    target_days = min(
        int(p["days"]),
        3 if beginner else 4
    )

    names = ["А", "Б", "А", "Б"]

    header = (
        f"🏋️ Базовый план на неделю: "
        f"{target_days} тренировки "
        f"по {minutes} мин.\n"
    )

    header += (
        "Цель: "
        + LABELS.get(
            ("goal", p["goal"]),
            "общая форма"
        )
        + ".\n"
    )

    header += (
        "Нагрузка лёгкая–умеренная: "
        "оставляй запас 2–3 повторения.\n\n"
    )

    parts = []

    for i in range(target_days):
        group = exercises[i % 2]
        lines = []

        for ex in group:
            if "Ходьба" in ex:
                volume = "3–5 минут"
            elif "Планка" in ex:
                volume = f"{sets} × 15–30 сек"
            else:
                volume = f"{sets} × 8–12"

            lines.append(f"• {ex}: {volume}")

        parts.append(
            "День "
            + str(i + 1)
            + " ("
            + names[i]
            + ")\n"
            + "\n".join(lines)
        )

    footer = (
        "\n\nРазминка 5 мин, отдых 60–90 сек, "
        "заминка 3 мин. Между силовыми — "
        "день восстановления."
    )

    footer += (
        "\nНачни с удобного диапазона движений, "
        "без боли. При боли, головокружении, "
        "необычной одышке или боли в груди "
        "остановись; при серьёзных симптомах "
        "нужна срочная помощь."
    )

    footer += (
        "\nЭто стартовый шаблон, "
        "не индивидуальное медицинское назначение."
    )

    if int(p["days"]) > target_days:
        footer += (
            "\nОстальные дни: спокойная ходьба "
            "или отдых, по самочувствию."
        )

    if p["goal"] in ("loss", "endurance"):
        footer += (
            "\nДополнительно: посильная ходьба "
            "в свободные дни."
        )

    return header + "\n\n".join(parts) + footer


@bot.message_handler(commands=["plan"])
def plan_command(message):
    bot.send_message(
        message.chat.id,
        plan_text(message.chat.id)
    )


@bot.message_handler(commands=["delete_me"])
def delete_me(message):
    bot.send_message(
        message.chat.id,
        "Удалить анкету из базы FORMIQ?",
        reply_markup=keyboard(
            ("Да, удалить профиль", "delete_confirm"),
            ("Отмена", "delete_cancel")
        )
    )


@bot.message_handler(
    commands=["progress", "nutrition", "coach"]
)
def coming_soon(message):
    bot.send_message(
        message.chat.id,
        "Эта функция ещё разрабатывается. "
        "Пока доступны /start, /profile и /plan."
    )


@bot.callback_query_handler(func=lambda call: True)
def handle_callback(call):
    chat_id = call.message.chat.id
    data = call.data or ""

    bot.answer_callback_query(call.id)

    if data == "restart":
        reset_profile(chat_id)
        ask(chat_id, 0)

    elif data == "profile":
        show_profile(chat_id)

    elif data == "plan":
        bot.send_message(
            chat_id,
            plan_text(chat_id)
        )

    elif data == "delete_cancel":
        bot.send_message(
            chat_id,
            "Удаление отменено."
        )

    elif data == "delete_confirm":
        with connect() as conn:
            conn.execute(
                "DELETE FROM profiles WHERE chat_id=%s",
                (chat_id,)
            )

        bot.send_message(
            chat_id,
            "Анкета удалена из таблицы FORMIQ. "
            "Сообщения Telegram и внешние "
            "резервные копии не удаляются."
        )

    elif data.startswith("answer:"):
        try:
            _, idx_str, value = data.split(":", 2)
            idx = int(idx_str)
            field, _, opts = QUESTIONS[idx]
        except (ValueError, IndexError):
            return

        if value not in {v for _, v in opts}:
            return

        existing = get_profile(chat_id)

        if any(
            not existing.get(previous)
            for previous in FIELDS[:idx]
        ):
            bot.send_message(
                chat_id,
                "Этот шаг анкеты устарел. "
                "Начни заново через /start."
            )
            return

        save_answer(chat_id, field, value)
        ask(chat_id, idx + 1)


@app.get("/")
def health():
    return "FORMIQ online", 200


@app.post("/telegram-webhook")
def webhook():
    candidate = request.headers.get(
        "X-Telegram-Bot-Api-Secret-Token",
        ""
    )

    if not hmac.compare_digest(
        candidate,
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
        os.environ.get("PORT", "10000")
    )

    app.run(
        host="0.0.0.0",
        port=port,
        debug=False
    )
