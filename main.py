import os
import hmac
import hashlib
import logging

import psycopg
import telebot

from flask import Flask, request, abort
from telebot import types
from psycopg.errors import UniqueViolation


# ==========================================
# FORMIQ 7.0 — SMART INTERFACE
# ==========================================

logging.basicConfig(level=logging.INFO)

TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
DATABASE_URL = os.environ["DATABASE_URL"]

URL = os.environ.get(
    "RENDER_EXTERNAL_URL",
    "https://formiq-bot.onrender.com"
).rstrip("/")

SECRET = hashlib.sha256(
    TOKEN.encode()
).hexdigest()

bot = telebot.TeleBot(
    TOKEN,
    threaded=False
)

app = Flask(__name__)


# ==========================================
# АНКЕТА
# ==========================================

QUESTIONS = [
    (
        "goal",
        "Какая у тебя цель?",
        [
            ("🔥 Похудеть", "loss"),
            ("💪 Набрать мышцы", "muscle"),
            ("🏃 Стать выносливее", "endurance"),
            ("❤️ Поддерживать форму", "general"),
        ],
    ),
    (
        "level",
        "Какой у тебя опыт?",
        [
            ("🌱 Новичок", "beginner"),
            ("🙂 Иногда тренируюсь", "some"),
            ("💪 Регулярно тренируюсь", "experienced"),
        ],
    ),
    (
        "days",
        "Сколько тренировок в неделю?",
        [
            ("2 дня", "2"),
            ("3 дня", "3"),
            ("4 дня", "4"),
            ("5 дней", "5"),
        ],
    ),
    (
        "equipment",
        "Где тренируешься?",
        [
            ("🏠 Дома без инвентаря", "home"),
            ("🏠 Дома с инвентарём", "homegear"),
            ("🏋️ В спортзале", "gym"),
        ],
    ),
    (
        "age_group",
        "Тебе уже есть 18 лет?",
        [
            ("✅ Да, мне 18+", "adult"),
            ("Нет", "minor"),
        ],
    ),
    (
        "minutes",
        "Сколько времени на тренировку?",
        [
            ("20 минут", "20"),
            ("30 минут", "30"),
            ("45 минут", "45"),
            ("60 минут", "60"),
        ],
    ),
    (
        "clearance",
        "Есть ли боль, травмы или ограничения, "
        "которые могут сделать нагрузку небезопасной?",
        [
            ("✅ Нет", "none"),
            ("⚠️ Да", "yes"),
            ("❓ Не уверен", "unsure"),
        ],
    ),
]

FIELDS = [
    question[0]
    for question in QUESTIONS
]

TITLES = [
    "Цель",
    "Опыт",
    "Тренировок в неделю",
    "Место",
    "Возраст",
    "Длительность",
    "Ограничения",
]

LABELS = {
    (field, value): label
    for field, _, options in QUESTIONS
    for label, value in options
}


# ==========================================
# DATABASE
# ==========================================

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
            "clearance",
        ):
            conn.execute(
                f"""
                ALTER TABLE profiles
                ADD COLUMN IF NOT EXISTS {field} TEXT
                """
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
            ALTER TABLE workout_items
            ADD COLUMN IF NOT EXISTS skipped
            BOOLEAN NOT NULL DEFAULT FALSE
        """)

        # Новое поле FORMIQ 7.0
        conn.execute("""
            ALTER TABLE workouts
            ADD COLUMN IF NOT EXISTS message_id BIGINT
        """)

        conn.execute("""
            CREATE INDEX IF NOT EXISTS workouts_chat_idx
            ON workouts(chat_id, started_at DESC)
        """)

        conn.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS
            one_active_workout_per_user
            ON workouts(chat_id)
            WHERE status = 'active'
        """)


# ==========================================
# КНОПКИ И МЕНЮ
# ==========================================

def kb(*buttons):
    markup = types.InlineKeyboardMarkup(
        row_width=1
    )

    for label, data in buttons:
        markup.add(
            types.InlineKeyboardButton(
                text=label,
                callback_data=data
            )
        )

    return markup


def main_keyboard():
    return kb(
        ("🏋️ Моя тренировка", "menu_workout"),
        ("📋 Мой план", "plan"),
        ("📊 Мой прогресс", "stats"),
        ("📖 История тренировок", "history"),
        ("👤 Мой профиль", "profile"),
        ("🤖 ИИ-тренер (скоро)", "ai_soon"),
    )


def show_menu(chat_id):
    text = (
        "🔥 FORMIQ 7.0\n\n"
        "Твой персональный тренировочный помощник.\n\n"
        "🏋️ Тренируйся\n"
        "📊 Отслеживай прогресс\n"
        "🎯 Двигайся к своей цели\n\n"
        "Выбирай, что будем делать 👇"
    )

    bot.send_message(
        chat_id,
        text,
        reply_markup=main_keyboard()
    )


def safe_remove_keyboard(call):
    try:
        bot.edit_message_reply_markup(
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            reply_markup=None
        )
    except Exception:
        # Старое сообщение могло быть удалено
        # или уже изменено.
        logging.debug(
            "Could not remove old keyboard",
            exc_info=True
        )


def safe_answer(call, text=None):
    try:
        bot.answer_callback_query(
            call.id,
            text=text
        )
    except Exception:
        logging.debug(
            "Callback answer failed",
            exc_info=True
        )


# ==========================================
# ПРОФИЛЬ
# ==========================================

def profile_for(chat_id):
    with connect() as conn:
        row = conn.execute("""
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
        """, (chat_id,)).fetchone()

    if not row:
        return {}

    return dict(zip(FIELDS, row))


def save_answer(chat_id, field, value):
    if field not in FIELDS:
        return

    with connect() as conn:
        conn.execute("""
            INSERT INTO profiles(chat_id)
            VALUES (%s)
            ON CONFLICT DO NOTHING
        """, (chat_id,))

        conn.execute(
            f"""
            UPDATE profiles
            SET {field} = %s,
                updated_at = NOW()
            WHERE chat_id = %s
            """,
            (value, chat_id)
        )


def reset_profile(chat_id):
    with connect() as conn:
        conn.execute("""
            INSERT INTO profiles(chat_id)
            VALUES (%s)
            ON CONFLICT(chat_id)
            DO UPDATE SET
                goal = NULL,
                level = NULL,
                days = NULL,
                equipment = NULL,
                age_group = NULL,
                minutes = NULL,
                clearance = NULL,
                updated_at = NOW()
        """, (chat_id,))


def ask(chat_id, index):
    if index >= len(QUESTIONS):
        show_profile(chat_id)
        return

    field, question, options = QUESTIONS[index]

    buttons = [
        (
            label,
            f"answer:{index}:{value}"
        )
        for label, value in options
    ]

    bot.send_message(
        chat_id,
        f"📝 Вопрос {index + 1}"
        f" из {len(QUESTIONS)}\n\n"
        f"{question}",
        reply_markup=kb(*buttons)
    )


def show_profile(chat_id):
    p = profile_for(chat_id)

    if not p or not any(p.values()):
        bot.send_message(
            chat_id,
            "👤 Профиль пока не заполнен.",
            reply_markup=kb(
                ("🚀 Заполнить анкету", "restart"),
                ("🏠 Главное меню", "menu")
            )
        )
        return

    lines = []

    for title, field in zip(TITLES, FIELDS):
        value = p.get(field)
        label = LABELS.get(
            (field, value),
            "—"
        )

        lines.append(
            f"• {title}: {label}"
        )

    bot.send_message(
        chat_id,
        "👤 ТВОЙ ПРОФИЛЬ\n\n"
        + "\n".join(lines)
        + "\n\n💾 Данные сохранены.",
        reply_markup=kb(
            ("📋 Мой план", "plan"),
            ("🔄 Изменить анкету", "restart"),
            ("🏠 Главное меню", "menu")
        )
    )


# ==========================================
# ПЛАН ТРЕНИРОВОК
# ==========================================

def plan_data(p):

    if any(
        not p.get(field)
       
