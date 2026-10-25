"""Telegram welcome regression tests — offline, no real API or database access."""
import importlib
import os
import unittest
from io import BytesIO
from types import SimpleNamespace
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

    def test_approved_welcome_art_is_valid_jpeg(self):
        from welcome_art import welcome_jpeg
        from PIL import Image
        content = welcome_jpeg()
        self.assertTrue(content.startswith(b'\xff\xd8\xff'))
        image = Image.open(BytesIO(content))
        self.assertEqual(image.size, (800, 533))
        self.assertLess(len(content), 5_000_000)
        self.assertEqual(
            self.botmod.APP.test_client().get('/mini/welcome-cover.jpg').data,
            content,
        )

    def test_inline_webapp_has_auth_capable_entry(self):
        kb = self.botmod.formiq_chat_keyboard()
        self.assertIsInstance(kb, types.InlineKeyboardMarkup)
        self.assertEqual(len(kb.keyboard), 1)
        self.assertEqual(len(kb.keyboard[0]), 2)
        opener, wake = kb.keyboard[0]
        self.assertEqual(opener.text, 'FormIQ')
        self.assertEqual(opener.web_app.url, 'https://example.invalid/mini')
        self.assertEqual(wake.text, 'Разбудить')
        self.assertEqual(wake.callback_data, 'wake')
        self.assertIsNone(wake.web_app)

    def test_wake_button_sends_real_message_and_preserves_two_buttons(self):
        call = SimpleNamespace(
            data='wake', id='TEST',
            message=SimpleNamespace(chat=SimpleNamespace(id=123, type='private')),
            from_user=SimpleNamespace(id=123),
        )
        with patch.object(self.botmod.BOT, 'answer_callback_query') as answer, \
             patch.object(self.botmod.BOT, 'send_message') as send, \
             patch.object(self.botmod.BOT, 'send_photo') as send_photo:
            self.botmod.callback(call)
        answer.assert_called_once()
        self.assertIn('на связи', answer.call_args.kwargs['text'])
        send.assert_called_once()
        self.assertIn('FORMIQ на связи', send.call_args.args[1])
        markup=send.call_args.kwargs['reply_markup']
        self.assertEqual([b.text for row in markup.keyboard for b in row],
                         ['FormIQ','Разбудить'])
        send_photo.assert_not_called()

    def test_welcome_photo_has_two_inline_buttons_without_extra_message(self):
        with patch.object(self.botmod.BOT, 'set_chat_menu_button') as set_menu, \
             patch.object(self.botmod.BOT, 'get_chat_menu_button',
                          return_value=types.MenuButtonCommands()), \
             patch.object(self.botmod.BOT, 'send_photo',
                          return_value=SimpleNamespace(message_id=57)) as photo, \
             patch.object(self.botmod.BOT, 'edit_message_reply_markup') as edit, \
             patch.object(self.botmod.BOT, 'send_message') as text_message:
            self.botmod.home(123, welcome_image=True)
        set_menu.assert_called_once()
        photo.assert_called_once()
        self.assertTrue(photo.call_args.args[1].getvalue().startswith(b'\xff\xd8'))
        markup = photo.call_args.kwargs['reply_markup']
        self.assertIsInstance(markup, types.InlineKeyboardMarkup)
        self.assertEqual(len(markup.keyboard[0]), 2)
        edit.assert_not_called()
        text_message.assert_not_called()

    def test_plain_welcome_uses_same_inline_keyboard(self):
        with patch.object(self.botmod.BOT, 'set_chat_menu_button'), \
             patch.object(self.botmod.BOT, 'get_chat_menu_button',
                          return_value=types.MenuButtonCommands()), \
             patch.object(self.botmod.BOT, 'send_message',
                          return_value=SimpleNamespace(message_id=58)) as send, \
             patch.object(self.botmod.BOT, 'edit_message_reply_markup') as edit:
            self.botmod.home(123, welcome_image=False)
        send.assert_called_once()
        self.assertIn('FORMIQ', send.call_args.args[1])
        self.assertNotIn('Кнопки запуска', send.call_args.args[1])
        self.assertIsInstance(send.call_args.kwargs['reply_markup'],
                              types.InlineKeyboardMarkup)
        edit.assert_not_called()

    def test_welcome_photo_failure_falls_back_to_text_with_two_buttons(self):
        with patch.object(self.botmod.BOT, 'set_chat_menu_button'), \
             patch.object(self.botmod.BOT, 'get_chat_menu_button',
                          return_value=types.MenuButtonCommands()), \
             patch.object(self.botmod.BOT, 'send_photo',
                          side_effect=RuntimeError('photo unavailable')), \
             patch.object(self.botmod.BOT, 'send_message') as send:
            self.botmod.home(123, welcome_image=True)
        send.assert_called_once()
        self.assertIsInstance(send.call_args.kwargs['reply_markup'],
                              types.InlineKeyboardMarkup)
        self.assertEqual(len(send.call_args.kwargs['reply_markup'].keyboard[0]), 2)


if __name__ == '__main__':
    unittest.main()
