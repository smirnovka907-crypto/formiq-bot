"""Telegram button regression tests: no API credentials or network requests."""
import importlib
import os
import unittest
from io import BytesIO
from unittest.mock import patch
from telebot import types


class Telegram3813(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with patch.dict(os.environ, {
            'TELEGRAM_BOT_TOKEN': '123456789:TESTONLY_not_real',
            'DATABASE_URL': 'postgresql://test:test@localhost:5432/test',
            'RENDER_EXTERNAL_URL': 'https://example.invalid',
        }):
            cls.botmod = importlib.import_module('main')

    def test_welcome_art_changes_and_is_valid_jpeg(self):
        from welcome_art import welcome_jpeg
        from PIL import Image
        content = welcome_jpeg()
        self.assertTrue(content.startswith(b'\xff\xd8\xff'))
        image = Image.open(BytesIO(content))
        self.assertEqual(image.size, (1200,675))
        self.assertLess(len(content), 5_000_000)
        self.assertEqual(self.botmod.APP.test_client().get('/mini/welcome-cover.jpg').data, content)

    def test_inline_webapp_has_auth_capable_entry(self):
        kb = self.botmod.formiq_chat_keyboard()
        self.assertIsInstance(kb, types.InlineKeyboardMarkup)
        self.assertEqual(len(kb.keyboard[0]), 2)
        opener, wake = kb.keyboard[0]
        self.assertIn('mini', opener.web_app.url)
        self.assertEqual(opener.web_app.url, 'https://example.invalid/mini')
        self.assertEqual(wake.callback_data, 'wake')
        self.assertIsNone(wake.web_app)

    def test_no_chat_message_for_wake_callback(self):
        from types import SimpleNamespace
        call = SimpleNamespace(data='wake', id='TEST', message=SimpleNamespace(
            chat=SimpleNamespace(id=123, type='private')), from_user=SimpleNamespace(id=123))
        with patch.object(self.botmod.BOT, 'answer_callback_query') as answer, \
             patch.object(self.botmod.BOT, 'send_message') as send, \
             patch.object(self.botmod.BOT, 'send_photo') as send_photo:
            self.botmod.callback(call)
            answer.assert_called_once()
            self.assertIn('на связи', answer.call_args.kwargs['text'])
            send.assert_not_called()
            send_photo.assert_not_called()

    def test_welcome_photo_is_the_only_new_message(self):
        from types import SimpleNamespace
        with patch.object(self.botmod.BOT, 'send_photo',
                          return_value=SimpleNamespace(message_id=57)) as photo, \
             patch.object(self.botmod.BOT, 'edit_message_reply_markup') as edit, \
             patch.object(self.botmod.BOT, 'send_message') as text_message:
            self.botmod.home(123, welcome_image=True)
        photo.assert_called_once()
        self.assertTrue(photo.call_args.args[1].getvalue().startswith(b'\\xff\\xd8'))
        self.assertIsInstance(photo.call_args.kwargs['reply_markup'], types.ReplyKeyboardRemove)
        edit.assert_called_once()
        self.assertEqual(edit.call_args.kwargs['message_id'], 57)
        self.assertIsInstance(edit.call_args.kwargs['reply_markup'], types.InlineKeyboardMarkup)
        text_message.assert_not_called()

    def test_plain_welcome_cleans_old_keyboard_without_service_text(self):
        from types import SimpleNamespace
        with patch.object(self.botmod.BOT, 'send_message',
                          return_value=SimpleNamespace(message_id=58)) as send, \
             patch.object(self.botmod.BOT, 'edit_message_reply_markup') as edit:
            self.botmod.home(123, welcome_image=False)
        send.assert_called_once()
        self.assertIn('FORMIQ', send.call_args.args[1])
        self.assertNotIn('Кнопки запуска', send.call_args.args[1])
        self.assertIsInstance(send.call_args.kwargs['reply_markup'], types.ReplyKeyboardRemove)
        self.assertIsInstance(edit.call_args.kwargs['reply_markup'], types.InlineKeyboardMarkup)

    def test_fallback_if_telegram_refuses_inline_edit(self):
        from types import SimpleNamespace
        with patch.object(self.botmod.BOT, 'send_photo',
                          return_value=SimpleNamespace(message_id=59)), \
             patch.object(self.botmod.BOT, 'edit_message_reply_markup',
                          side_effect=RuntimeError('edit failed')), \
             patch.object(self.botmod.BOT, 'send_message') as send:
            self.botmod.home(123, welcome_image=True)
        self.assertEqual(send.call_count, 1)
        self.assertIsInstance(send.call_args.kwargs['reply_markup'], types.InlineKeyboardMarkup)


if __name__=='__main__':
    unittest.main()
