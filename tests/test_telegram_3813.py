"""Tests for the CURRENT approved two-button Telegram welcome (offline)."""
import importlib
import os
import unittest
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import patch
from telebot import types


class TelegramWelcomeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with patch.dict(os.environ, {
            'TELEGRAM_BOT_TOKEN':'123456789:TESTONLY_not_real',
            'DATABASE_URL':'postgresql://test:test@localhost:5432/test',
            'RENDER_EXTERNAL_URL':'https://example.invalid',
        }):
            cls.botmod=importlib.import_module('main')

    def test_approved_banner_is_valid_jpeg(self):
        from welcome_art import welcome_jpeg
        from PIL import Image
        content=welcome_jpeg()
        self.assertTrue(content.startswith(b'\xff\xd8\xff'))
        image=Image.open(BytesIO(content))
        self.assertEqual(image.size,(800,533))
        self.assertLess(len(content),5_000_000)
        self.assertEqual(self.botmod.APP.test_client().get('/mini/welcome-cover.jpg').data,content)

    def test_two_buttons_have_correct_actions(self):
        kb=self.botmod.formiq_chat_keyboard()
        self.assertIsInstance(kb,types.InlineKeyboardMarkup)
        self.assertEqual(len(kb.keyboard),1)
        self.assertEqual(len(kb.keyboard[0]),2)
        opener,wake=kb.keyboard[0]
        self.assertEqual(opener.text,'FormIQ')
        self.assertEqual(opener.web_app.url,'https://example.invalid/mini')
        self.assertEqual(wake.text,'Разбудить')
        self.assertEqual(wake.callback_data,'wake')
        self.assertIsNone(wake.web_app)

    def test_wake_callback_creates_no_chat_message(self):
        call=SimpleNamespace(data='wake',id='TEST',message=SimpleNamespace(
            chat=SimpleNamespace(id=123,type='private')),from_user=SimpleNamespace(id=123))
        with patch.object(self.botmod.BOT,'answer_callback_query') as answer, \
             patch.object(self.botmod.BOT,'send_message') as send, \
             patch.object(self.botmod.BOT,'send_photo') as photo:
            self.botmod.callback(call)
        answer.assert_called_once()
        self.assertIn('на связи',answer.call_args.kwargs['text'])
        send.assert_not_called()
        photo.assert_not_called()

    def test_welcome_photo_includes_two_buttons_and_hides_old_menu(self):
        with patch.object(self.botmod.BOT,'set_chat_menu_button') as menu, \
             patch.object(self.botmod.BOT,'get_chat_menu_button',
                          return_value=SimpleNamespace(type='commands')), \
             patch.object(self.botmod.BOT,'send_photo',
                          return_value=SimpleNamespace(message_id=57)) as photo, \
             patch.object(self.botmod.BOT,'send_message') as send:
            self.botmod.home(123,welcome_image=True)
        menu.assert_called_once()
        self.assertEqual(menu.call_args.kwargs['chat_id'],123)
        self.assertIsInstance(menu.call_args.kwargs['menu_button'],types.MenuButtonCommands)
        photo.assert_called_once()
        self.assertTrue(photo.call_args.args[1].getvalue().startswith(b'\xff\xd8'))
        markup=photo.call_args.kwargs['reply_markup']
        self.assertIsInstance(markup,types.InlineKeyboardMarkup)
        self.assertEqual(len(markup.keyboard[0]),2)
        send.assert_not_called()

    def test_text_only_welcome_has_no_duplicate_messages(self):
        with patch.object(self.botmod.BOT,'set_chat_menu_button') as menu, \
             patch.object(self.botmod.BOT,'get_chat_menu_button',
                          return_value=SimpleNamespace(type='commands')), \
             patch.object(self.botmod.BOT,'send_message',
                          return_value=SimpleNamespace(message_id=58)) as send, \
             patch.object(self.botmod.BOT,'send_photo') as photo:
            self.botmod.home(123,welcome_image=False)
        send.assert_called_once()
        self.assertIn('FORMIQ',send.call_args.args[1])
        self.assertIsInstance(send.call_args.kwargs['reply_markup'],types.InlineKeyboardMarkup)
        photo.assert_not_called()
        menu.assert_called_once()

    def test_photo_failure_falls_back_to_text_with_buttons(self):
        with patch.object(self.botmod.BOT,'set_chat_menu_button'), \
             patch.object(self.botmod.BOT,'get_chat_menu_button',
                          return_value=SimpleNamespace(type='commands')), \
             patch.object(self.botmod.BOT,'send_photo',side_effect=RuntimeError('photo failed')), \
             patch.object(self.botmod.BOT,'send_message') as send:
            self.botmod.home(123,welcome_image=True)
        send.assert_called_once()
        self.assertIsInstance(send.call_args.kwargs['reply_markup'],types.InlineKeyboardMarkup)


if __name__=='__main__':
    unittest.main()
