
import os
import hashlib
from datetime import datetime, timezone

import psycopg
import telebot
from flask import Flask, request, abort
from telebot import types

TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
DATABASE_URL = os.environ["DATABASE_URL"]

URL = os.environ.get(
    "RENDER_EXTERNAL_URL",
    "https://formiq-bot.onrender.com"
).rstrip("/")

SECRET = hashlib.sha256(
    TOKEN.encode("utf-8")
).hexdigest()

bot = telebot.TeleBot(TOKEN, threaded=False)
app = Flask(__name__)

QUESTIONS = [
    (
        "goal",
        "Какая у тебя главная цель?",
        [
            ("Похудеть", "loss"),
            ("Набрать мышцы", "muscle"),
            ("Стать выносливее", "endurance"),
            ("Поддерживать форму", "general"),
        ],
    ),
    (
        "level",
        "Какой у тебя опыт тренировок?",
        [
            ("Новичок", "beginner"),
            ("Иногда тренируюсь", "some"),
            ("Тренируюсь регулярно", "experienced"),
        ],
    ),
    (
        "days",
        "Сколько дней в неделю удобно тренироваться?",
        [
            ("2 дня", "2"),
            ("3 дня", "3"),
            ("4 дня", "4"),
            ("5 дней", "5"),
        ],
    ),
    (
        "equipment",
        "Где планируешь тренироваться?",
        [
            ("Дома без инвентаря", "home"),
            ("Дома с инвентарём", "homegear"),
            ("В тренажёрном зале", "gym"),
        ],
    ),
]

FIELDS = ["goal", "level", "days", "equipment"]

LABELS = {
    (field, value): title
    for field, _, options in QUESTIONS
    for title, value in options
}


def db_connection():
    return psycopg.connect(
        DATABASE_URL,
        connect_timeout=10
    )


def initialize_database():
    with db_connection() as conn:
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


def get_profile(chat_id):
    with db_connection() as conn:
        row = conn.execute(
            """
            SELECT goal, level, days, equipment
            FROM profiles
            WHERE chat_id = %s
            """,
            (chat_id,)
        ).fetchone()

    if not row:
        return {}

    return dict(zip(FIELDS, row))


def reset_profile(chat_id):
    with db_connection() as conn:
        conn.execute(
            """
            INSERT INTO profiles (chat_id)
            VALUES (%s)
            ON CONFLICT (chat_id)
            DO UPDATE SET
                goal = NULL,
                level = NULL,
                days = NULL,
                equipment = NULL,
                updated_at = NOW()
            """,
            (chat_id,)
        )


def save_answer(chat_id, field, value):
    if field not in FIELDS:
        raise ValueError("Invalid field")

    query = f"""
        INSERT INTO profiles (chat_id, {field})
        VALUES (%s, %s)
        ON CONFLICT (chat_id)
        DO UPDATE SET
            {field} = EXCLUDED.{field},
            updated_at = NOW()
    """

    with db_connection() as conn:
        conn.execute(query, (chat_id, value))


def ask_question(chat_id, index):
    if index >= len(QUESTIONS):
        show_profile(chat_id)
        return

    field, question, options = QUESTIONS[index]

    keyboard = types.InlineKeyboardMarkup(row_width=1)

    for title, value in options:
        keyboard.add(
            types.InlineKeyboardButton(
                title,
                callback_data=f"answer:{index}:{value}"
            )
        )

    bot.send_message(
        chat_id,
        f"Вопрос {index + 1} из {len(QUESTIONS)}"
        f"\n\n{question}",
        reply_markup=keyboard
    )


def show_profile(chat_id):
    profile = get_profile(chat_id)

    titles = {
        "goal": "Цель",
        "level": "Уровень",
        "days": "Дней в неделю",
        "equipment": "Формат"
    }

    lines = []

    for field in FIELDS:
        value = profile.get(field)
        label = LABELS.get((field, value), "—")
        lines.append(f"• {titles[field]}: {label}")

    keyboard = types.InlineKeyboardMarkup()
    keyboard.add(
        types.InlineKeyboardButton(
            "🔄 Пройти анкету заново",
            callback_data="restart"
        )
    )

    bot.send_message(
        chat_id,
        "✅ Твой профиль FORMIQ\n\n"
        + "\n".join(lines)
        + "\n\n💾 Данные сохранены в базе.\n"
        "Персональные тренировки появятся позже.",
        reply_markup=keyboard
    )


@bot.message_handler(commands=["start"])
def start(message):
    chat_id = message.chat.id

    keyboard = types.InlineKeyboardMarkup()

    keyboard.add(
        types.InlineKeyboardButton(
            "🚀 Начать анкету",
            callback_data="restart"
        )
    )

    profile = get_profile(chat_id)

    if profile.get("equipment"):
        keyboard.add(
            types.InlineKeyboardButton(
                "👤 Мой профиль",
                callback_data="profile"
            )
        )

    bot.send_message(
        chat_id,
        "💪 Привет! Я FORMIQ — "
        "твой будущий ИИ-тренер.\n\n"
        "🏋️ Тренировки\n"
        "🥗 Питание\n"
        "📊 Прогресс\n\n"
        "🎁 Планируем 14 дней бесплатно.\n\n"
        "Сейчас доступна тестовая анкета.",
        reply_markup=keyboard
    )


@bot.message_handler(commands=["profile"])
def profile_command(message):
    show_profile(message.chat.id)


@bot.message_handler(commands=["delete_me"])
def delete_profile(message):
    with db_connection() as conn:
        conn.execute(
            "DELETE FROM profiles WHERE chat_id = %s",
            (message.chat.id,)
        )

    bot.send_message(
        message.chat.id,
        "🗑 Твой профиль удалён из базы FORMIQ."
    )


@bot.callback_query_handler(func=lambda call: True)
def handle_callback(call):
    chat_id = call.message.chat.id
    data = call.data or ""

    bot.answer_callback_query(call.id)

    if data == "restart":
        reset_profile(chat_id)
        ask_question(chat_id, 0)
        return

    if data == "profile":
        show_profile(chat_id)
        return

    if not data.startswith("answer:"):
        return

    try:
        _, index_text, value = data.split(":", 2)
        index = int(index_text)

        field, _, options = QUESTIONS[index]
    except (ValueError, IndexError):
        return

    if value not in {v for _, v in options}:
        return

    current = get_profile(chat_id)

    # Не принимаем ответы на старые этапы анкеты.
    for previous in FIELDS[:index]:
        if not current.get(previous):
            ask_question(chat_id, 0)
            return

    save_answer(chat_id, field, value)
    ask_question(chat_id, index + 1)


@bot.message_handler(
    commands=[
        "plan", "progress",
        "nutrition", "coach", "help"
    ]
)
def upcoming(message):
    bot.send_message(
        message.chat.id,
        "💪 FORMIQ развивается!\n\n"
        "Эта функция появится позже.\n\n"
        "/start — начало\n"
        "/profile — посмотреть анкету\n"
        "/delete_me — удалить профиль"
    )


@app.route("/", methods=["GET"])
def home():
    return "FORMIQ running", 200


@app.route("/telegram-webhook", methods=["POST"])
def webhook():
    received = request.headers.get(
        "X-Telegram-Bot-Api-Secret-Token", ""
    )

    if received != SECRET:
        abort(403)

    if not request.is_json:
        abort(415)

    update = types.Update.de_json(
        request.get_data(as_text=True)
    )

    bot.process_new_updates([update])

    return "OK", 200


if __name__ == "__main__":
    initialize_database()

    bot.set_webhook(
        url=URL + "/telegram-webhook",
        secret_token=SECRET,
        drop_pending_updates=False
    )

    print("FORMIQ database and webhook ready")

    port = int(os.environ.get("PORT", 10000))

    app.run(
        host="0.0.0.0",
        port=port,
        debug=False
    )
