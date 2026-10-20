import os
import telebot

TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
bot = telebot.TeleBot(TOKEN)

@bot.message_handler(commands=["start"])
def start(message):
    bot.reply_to(
        message,
        "💪 Привет! Я FORMIQ — твой ИИ-тренер!\n"
        "🎁 Первые 14 дней бесплатно.\n"
        "Скоро мы начнём тренироваться вместе!"
    )

print("FORMIQ запущен!")
bot.infinity_polling()
