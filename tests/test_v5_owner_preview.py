"""Owner-only Aluminium V5 Telegram launch. No real credentials or DB calls."""
import importlib
import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from telebot import types


class OwnerPreviewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with patch.dict(os.environ, {
            'TELEGRAM_BOT_TOKEN': '123456789:TESTONLY_owner_v5',
            'DATABASE_URL': 'postgresql://test:test@localhost:5432/test',
            'RENDER_EXTERNAL_URL': 'https://example.invalid',
        }):
            cls.mod = importlib.import_module('main')

    @staticmethod
    def msg(uid, chat_id=None, kind='private'):
        return SimpleNamespace(
            chat=SimpleNamespace(id=uid if chat_id is None else chat_id, type=kind),
            from_user=SimpleNamespace(id=uid),
            text='/v5',
        )

    def test_no_owners_when_admin_not_configured(self):
        with patch.object(self.mod, 'ADMIN_ID', 0), \
             patch.object(self.mod.BOT, 'send_message') as send:
            self.mod.owner_v5_preview(self.msg(123))
        send.assert_not_called()

    def test_non_owner_cannot_receive_preview_launch_button(self):
        for uid, chat_id, kind in [
            (124, 124, 'private'), (123, 124, 'private'),
            (123, -1003, 'supergroup'),
        ]:
            with self.subTest(uid=uid, chat_id=chat_id, kind=kind), \
                 patch.object(self.mod, 'ADMIN_ID', 123), \
                 patch.object(self.mod.BOT, 'send_message') as send:
                self.mod.owner_v5_preview(self.msg(uid, chat_id, kind))
            send.assert_not_called()

    def test_only_owner_gets_opt_in_webapp(self):
        with patch.object(self.mod, 'ADMIN_ID', 123), \
             patch.object(self.mod.BOT, 'send_message') as send:
            self.mod.owner_v5_preview(self.msg(123))
        send.assert_called_once()
        args, kwargs = send.call_args
        self.assertEqual(args[0], 123)
        self.assertIn('настоящий дневник', args[1])
        markup = kwargs['reply_markup']
        self.assertIsInstance(markup, types.InlineKeyboardMarkup)
        self.assertEqual(len(markup.keyboard), 1)
        self.assertEqual(len(markup.keyboard[0]), 1)
        self.assertEqual(markup.keyboard[0][0].web_app.url, 'https://example.invalid/mini/v5')

    def test_public_formiq_button_remains_on_stable_route(self):
        menu = self.mod.formiq_chat_keyboard()
        self.assertEqual(len(menu.keyboard[0]), 2)
        self.assertEqual(menu.keyboard[0][0].text, 'FormIQ')
        self.assertEqual(menu.keyboard[0][0].web_app.url, 'https://example.invalid/mini')
        self.assertEqual(menu.keyboard[0][1].text, 'Разбудить')

    def test_staging_routes_work_but_do_not_bypass_api_auth(self):
        client = self.mod.APP.test_client()
        self.assertEqual(client.get('/mini/v5').status_code, 200)
        self.assertEqual(client.get('/mini/v5-live.js').status_code, 200)
        self.assertEqual(client.post('/mini/api', json={'action': 'state'}).status_code, 401)


if __name__ == '__main__':
    unittest.main()
