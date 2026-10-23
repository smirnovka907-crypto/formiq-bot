"""Read-only smoke checks for opt-in Aluminium v5 /mini/v5.
Never contact Telegram, PostgreSQL, or external APIs.
"""
import importlib
import os
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


class V5StagingContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with patch.dict(os.environ, {
            'TELEGRAM_BOT_TOKEN': '123456789:TESTONLY_not_real',
            'DATABASE_URL': 'postgresql://test:test@localhost:5432/test',
            'RENDER_EXTERNAL_URL': 'https://example.invalid',
        }):
            cls.mod = importlib.import_module('main')
        cls.client = cls.mod.APP.test_client()

    def test_v5_is_separate_and_does_not_override_stable_route(self):
        stable = self.client.get('/mini')
        v5 = self.client.get('/mini/v5')
        self.assertEqual(stable.status_code, 200)
        self.assertEqual(v5.status_code, 200)
        self.assertIn(b'/mini/ux-381.css', stable.data)
        self.assertNotIn(b'v5-live.js', stable.data)
        self.assertIn(b'v5-live.js', v5.data)
        self.assertEqual(v5.headers.get('Cache-Control'), 'no-store')
        self.assertEqual(v5.headers.get('X-Content-Type-Options'), 'nosniff')
        self.assertEqual(v5.headers.get('Referrer-Policy'), 'no-referrer')

    def test_v5_bridge_uses_only_authenticated_server_api(self):
        response = self.client.get('/mini/v5-live.js')
        self.assertEqual(response.status_code, 200)
        js = response.data.decode('utf-8')
        self.assertIn("X-Formiq-Init", js)
        self.assertIn("credentials:'same-origin'", js)
        self.assertIn("'/mini/api'", js)
        self.assertIn("if(!token)", js)
        self.assertIn("if(!ready())", js)
        self.assertNotIn("localStorage", js)
        self.assertNotIn("formiq_preview_strength_v1", js)
        self.assertNotIn("formiq_design_profile_v3", js)
        self.assertNotIn("DELETE FROM", js)
        self.assertIn("async function send(", js)
        self.assertIn("rest_seconds", js)
        self.assertIn("data-date", js)
        self.assertIn("data-cmd", js)

    def test_unauthorized_api_calls_are_rejected(self):
        for action in ('state', 'start', 'record', 'cardio', 'finish', 'detail'):
            result = self.client.post('/mini/api', json={'action': action})
            self.assertEqual(result.status_code, 401, action)

    def test_approved_visual_identity_still_present(self):
        html = (ROOT / 'web' / 'v5-live.html').read_text(encoding='utf-8')
        for token in (
            '--silver:', '--pistachio:', 'class="app"',
            'viewport-fit=cover', 'FORMIQ · Aluminium v5',
        ):
            self.assertIn(token, html)


if __name__ == '__main__':
    unittest.main()
