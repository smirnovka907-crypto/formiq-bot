
import os
import hashlib
import telebot
from flask import Flask, request, abort
from telebot import types

TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
URL = os.environ.get(
    "RENDER_EXTERNAL_URL",
    "https://formiq-bot.onrender.com"
).rstrip("/")

SECRET = hashlib.sha256(
    TOKEN.encode("utf-8")
).hexdigest()

bot = telebot.TeleBot(TOKEN, threaded=False)
app = Flask(__name__)

profiles = {}

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

LABELS = {
    (field, value): title
    for field, _, options in QUESTIONS
    for title, value in options
}


def ask_question(chat_id, index):
    if index >= len(QUESTIONS):
        profile = profiles.get(chat_id, {})

        fields = [
            ("goal", "Цель"),
            ("level", "Уровень"),
            ("days", "Дней в неделю"),
            ("equipment", "Формат"),
        ]

        lines = []
        for field, title in fields:
            value = profile.get(field, "")
            answer = LABELS.get((field, value), "—")
            lines.append(f"• {title}: {answer}")

        keyboard = types.InlineKeyboardMarkup()
        keyboard.add(
            types.InlineKeyboardButton(
                "🔄 Пройти анкету заново",
                callback_data="restart",
            )
        )

        bot.send_message(
            chat_id,
            "✅ Анкета готова!\n\n"
            + "\n".join(lines)
            + "\n\nЭто тестовая версия FORMIQ."
            "\nПерсональные планы появятся позже.",
            reply_markup=keyboard,
        )
        return

    field, question, options = QUESTIONS[index]

    keyboard = types.InlineKeyboardMarkup(row_width=1)
    for title, value in options:
        keyboard.add(
            types.InlineKeyboardButton(
                title,
                callback_data=f"answer:{index}:{value}",
            )
        )

    bot.send_message(
        chat_id,
        f"Вопрос {index + 1} из {len(QUESTIONS)}"
        f"\n\n{question}",
        reply_markup=keyboard,
    )


@bot.message_handler(commands=["start"])
def start(message):
    keyboard = types.InlineKeyboardMarkup()
    keyboard.add(
        types.InlineKeyboardButton(
            "🚀 Начать анкету",
            callback_data="restart",
        )
    )

    bot.send_message(
        message.chat.id,
        "💪 Привет! Я FORMIQ — твой ИИ-тренер!\n\n"
        "🏋️ Индивидуальные тренировки\n"
        "🥗 Рекомендации по питанию\n"
        "📊 Контроль прогресса\n\n"
        "🎁 Планируем 14 дней бесплатно.\n\n"
        "Пока работает тестовая анкета. "
        "Начнём знакомство?",
        reply_markup=keyboard,
    )


@bot.callback_query_handler(func=lambda call: True)
def handle_callback(call):
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
        _, index_text, value = data.split(":", 2)
        index = int(index_text)
        field, _, options = QUESTIONS[index]
    except (ValueError, IndexError):
        return

    valid = {item[1] for item in options}
    if value not in valid:
        return

    profile = profiles.setdefault(chat_id, {})
    profile[field] = value

    ask_question(chat_id, index + 1)


@bot.message_handler(
    commands=[
        "plan", "progress", "nutrition",
        "coach", "help",
    ]
)
def other_commands(message):
    bot.send_message(
        message.chat.id,
        "💪 FORMIQ развивается!\n\n"
        "Эта функция появится позже.\n"
        "Для начала анкеты нажми /start.",
    )


@app.route("/", methods=["GET"])
def home():
    return "FORMIQ is running", 200


@app.route("/telegram-webhook", methods=["POST"])
def webhook():
    received_secret = request.headers.get(
        "X-Telegram-Bot-Api-Secret-Token", ""
    )

    if received_secret != SECRET:
        abort(403)

    if not request.is_json:
        abort(415)

    update = types.Update.de_json(
        request.get_data(as_text=True)
    )
    bot.process_new_updates([update])

    return "OK", 200


if __name__ == "__main__":
    webhook_url = URL + "/telegram-webhook"

    bot.set_webhook(
        url=webhook_url,
        secret_token=SECRET,
        drop_pending_updates=True,
    )

    print("FORMIQ webhook configured")

    port = int(os.environ.get("PORT", 10000))
    app.run(
        host="0.0.0.0",
        port=port,
        debug=False,
    )
