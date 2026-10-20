
import os
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
import telebot

TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
bot = telebot.TeleBot(TOKEN)

class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"FORMIQ is running")

def run_server():
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(("0.0.0.0", port), HealthHandler)
    server.serve_forever()

@bot.message_handler(commands=["start"])
def start(message):
    bot.reply_to(
        message,
        "💪 Привет! Я FORMIQ — твой ИИ-тренер!\n"
        "🎁 Первые 14 дней бесплатно.\n"
        "Скоро мы начнём тренироваться вместе!"
    )

threading.Thread(target=run_server, daemon=True).start()
print("FORMIQ started!")
bot.infinity_polling()
  
