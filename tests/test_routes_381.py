"""Flask route smoke tests: no real Telegram API, Yandex, or PostgreSQL access."""
import importlib
import os
import unittest
from unittest.mock import patch


class RouteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with patch.dict(os.environ, {
            'TELEGRAM_BOT_TOKEN': '123456789:TESTONLY_no_real_token',
            'DATABASE_URL': 'postgresql://test:test@localhost:5432/test',
            'RENDER_EXTERNAL_URL': 'https://example.invalid',
        }):
            cls.app = importlib.import_module('main').APP
        cls.app.config.update(TESTING=True)

    def test_page_and_assets(self):
        client = self.app.test_client()
        page = client.get('/mini')
        self.assertEqual(page.status_code, 200)
        self.assertIn(b'ux-381.css', page.data)
        self.assertIn(b'ux-381.js', page.data)
        self.assertIn(b'Отзывы и предложения', page.data)
        for url, mime, snippet in [
            ('/mini/ux-381.css', 'text/css', b'.today-hero'),
            ('/mini/ux-381.js', 'javascript', b'health-refine'),
        ]:
            response = client.get(url)
            self.assertEqual(response.status_code, 200)
            self.assertIn(mime, response.content_type)
            self.assertIn(snippet, response.data)

    def test_api_does_not_respond_without_telegram_identity(self):
        client = self.app.test_client()
        response = client.post('/mini/api', json={'action': 'state'})
        self.assertEqual(response.status_code, 401)
        self.assertFalse(response.json['ok'])

    def test_version(self):
        self.assertEqual(self.app.test_client().get('/').status_code, 200)
        self.assertIn(b'38.1.0-rc1', self.app.test_client().get('/').data)


if __name__ == '__main__':
    unittest.main()
