
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import telebot
from telebot import types

TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
bot = telebot.TeleBot(TOKEN)

# Временные данные пользователей
profiles = {}

QUESTIONS = [
    (
        "goal",
        "Какая у тебя главная цель?",
        [
            ("Похудеть", "loss"),
            ("Набрать мышцы", "muscle"),
            ("Стать выносливее", "endurance"),
            ("Поддерживать форму", "general")
        ]
    ),
    (
        "level",
        "Какой у тебя опыт тренировок?",
        [
            ("Новичок", "beginner"),
            ("Иногда тренируюсь", "some"),
            ("Тренируюсь регулярно", "experienced")
        ]
    ),
    (
        "days",
        "Сколько дней в неделю удобно тренироваться?",
        [
            ("2 дня", "2"),
            ("3 дня", "3"),
            ("4 дня", "4"),
            ("5 дней", "5")
        ]
    ),
    (
        "equipment",
        "Где планируешь тренироваться?",
        [
            ("Дома без инвентаря", "home"),
            ("Дома с инвентарём", "homegear"),
            ("В тренажёрном зале", "gym")
        ]
    )
]

LABELS = {
    value: title
    for _, _, options in QUESTIONS
    for title, value in options
}


class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header(
            "Content-Type",
            "text/plain; charset=utf-8"
        )
        self.end_headers()
        self.wfile.write(b"FORMIQ prototype running")

    def log_message(self, fmt, *args):
        pass


def serve_healthcheck():
    port = int(os.environ.get("PORT", "10000"))
    server = ThreadingHTTPServer(
        ("0.0.0.0", port),
        HealthHandler
    )
    server.serve_forever()


def ask_question(chat_id, index):
    if index == len(QUESTIONS):
        profile = profiles.get(chat_id, {})

        summary = "\n".join(
            f"• {key}: "
            f"{LABELS.get(profile.get(field, ''), '—')}"
            for field, key in [
                ("goal", "Цель"),
                ("level", "Уровень"),
                ("days", "Дней в неделю"),
                ("equipment", "Формат")
            ]
        )

        keyboard = types.InlineKeyboardMarkup()
        keyboard.add(
            types.InlineKeyboardButton(
                "🔄 Пройти анкету заново",
                callback_data="restart"
            )
        )

        bot.send_message(
            chat_id,
            f"✅ Анкета готова!\n\n{summary}\n\n"
            "Это тестовая версия FORMIQ. "
            "Персональные планы и подписка "
            "пока не подключены.\n\n"
            "Если есть ограничения по здоровью, "
            "обсуди нагрузки со специалистом.",
            reply_markup=keyboard
        )
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


@bot.message_handler(commands=["start"])
def start(message):
    keyboard = types.InlineKeyboardMarkup()
    keyboard.add(
        types.InlineKeyboardButton(
            "🚀 Начать анкету",
            callback_data="restart"
        )
    )

    bot.send_message(
        message.chat.id,
        "💪 Привет! Я FORMIQ — "
        "твой будущий умный тренер.\n\n"
        "Помогу определить цель и собрать "
        "основу программы тренировок.\n\n"
        "Сейчас идёт тестирование: "
        "ИИ-рекомендации и оплата "
        "пока не работают.\n\n"
        "Нажми кнопку, чтобы пройти "
        "короткую анкету.",
        reply_markup=keyboard
    )


@bot.callback_query_handler(func=lambda call: True)
def on_click(call):
    chat_id = call.message.chat.id
    data = call.data or ""

    bot.answer_callback_query(call.id)

    if data == "restart":
        profiles[chat_id] = {}
        ask_question(chat_id, 0)
        return

    if not data.startswith("answer:"):
        return

    try:
        _, raw_index, value = data.split(":", 2)
        index = int(raw_index)
        field, _, options = QUESTIONS[index]
    except (ValueError, IndexError):
        return

    if value not in {
        option_value for _, option_value in options
    }:
        return

    profile = profiles.setdefault(chat_id, {})
    profile[field] = value
    ask_question(chat_id, index + 1)


@bot.message_handler(
    commands=["help", "plan", "progress", "nutrition", "coach"]
)
def upcoming(message):
    bot.send_message(
        message.chat.id,
        "Эта функция появится в следующей "
        "версии FORMIQ. "
        "Для анкеты нажми /start."
    )


if __name__ == "__main__":
    threading.Thread(
        target=serve_healthcheck,
        daemon=True
    ).start()

    print("FORMIQ prototype started")
    bot.infinity_polling(skip_pending=True)
