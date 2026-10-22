"""38.1.3 Telegram regression checks (no Telegram network or user data)."""
import importlib
import io
import os
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from PIL import Image


class TelegramHotfixTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with patch.dict(os.environ, {
            "TELEGRAM_BOT_TOKEN": "123456789:TESTONLY_fake",
            "DATABASE_URL": "postgresql://test:test@localhost:5432/test",
            "RENDER_EXTERNAL_URL": "https://example.invalid",
        }):
            cls.bot = importlib.import_module("main")

    def test_new_cover_is_actual_jpeg(self):
        from brand_assets import welcome_cover_jpeg
        payload = welcome_cover_jpeg()
        self.assertTrue(payload.startswith(b"\xff\xd8"))
        self.assertLess(len(payload), 600_000)
        im = Image.open(io.BytesIO(payload))
        self.assertEqual(im.size, (1200, 700))
        self.assertEqual(im.format, "JPEG")
        response = self.bot.APP.test_client().get("/mini/welcome-cover.jpg")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, payload)
        self.assertIn("no-store", response.headers["Cache-Control"])

    def test_lower_buttons_both_dispatch_as_text(self):
        markup = self.bot.formiq_chat_keyboard()
        buttons = markup.keyboard[0]
        self.assertEqual([b.text for b in buttons], ["FormIQ", "Разбудить"])
        self.assertIsNone(buttons[0].web_app)
        self.assertIsNone(buttons[1].web_app)

    def test_fallback_inline_buttons_have_valid_targets(self):
        markup = self.bot.formiq_open_links()
        buttons = [r[0] for r in markup.keyboard]
        self.assertEqual(len(buttons), 2)
        self.assertEqual(buttons[0].web_app.url, "https://example.invalid/mini")
        self.assertEqual(buttons[1].url, "https://example.invalid/wake")

    def test_start_posts_new_photo_and_keyboard(self):
        with patch.object(self.bot.BOT, "send_photo") as photo, \
             patch.object(self.bot.BOT, "send_message") as message:
            self.bot.home(171, welcome_image=True)
        self.assertEqual(photo.call_count, 1)
        self.assertEqual(message.call_count, 1)
        binary = photo.call_args.args[1]
        self.assertTrue(binary.read(2) == b"\xff\xd8")
        inline = photo.call_args.kwargs["reply_markup"]
        self.assertIsNotNone(inline.keyboard[0][0].web_app)
        keys = message.call_args.kwargs["reply_markup"]
        self.assertEqual(keys.keyboard[0][0].text, "FormIQ")

    def test_wake_no_longer_repeats_home(self):
        msg = SimpleNamespace(
            chat=SimpleNamespace(type="private", id=171),
            text="Разбудить")
        with patch.object(self.bot.BOT, "send_message") as send, \
             patch.object(self.bot, "home") as home:
            self.bot.plain_text(msg)
        self.assertFalse(home.called)
        self.assertEqual(send.call_count, 1)
        self.assertIn("Сервер FORMIQ на связи", send.call_args.args[1])

    def test_formiq_text_produces_clickable_launch(self):
        msg = SimpleNamespace(
            chat=SimpleNamespace(type="private", id=171),
            text="FormIQ")
        with patch.object(self.bot.BOT, "send_message") as send:
            self.bot.plain_text(msg)
        self.assertEqual(send.call_count, 1)
        self.assertIsNotNone(send.call_args.kwargs["reply_markup"].keyboard[0][0].web_app)


if __name__ == "__main__":
    unittest.main()
