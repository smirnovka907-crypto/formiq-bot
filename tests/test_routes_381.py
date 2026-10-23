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
        page = client.get('/mini/legacy')
        self.assertEqual(page.status_code, 200)
        self.assertIn(b'ux-381.css', page.data)
        self.assertIn(b'ux-381.js', page.data)
        self.assertIn('Отзывы и предложения'.encode('utf-8'), page.data)
        for url, mime, snippet in [
            ('/mini/ux-381.css', 'text/css', b'.today-hero'),
            ('/mini/ux-381.js', 'javascript', b'health-refine'),
        ]:
            response = client.get(url)
            self.assertEqual(response.status_code, 200)
            self.assertIn(mime, response.content_type)
            self.assertIn(snippet, response.data)

    def test_approved_v5_is_default_and_legacy_is_preserved(self):
        client = self.app.test_client()
        new_app = client.get('/mini')
        self.assertEqual(new_app.status_code, 200)
        self.assertIn(b'/mini/v5-live.js', new_app.data)
        self.assertNotIn(b'/mini/ux-381.js', new_app.data)
        self.assertEqual(new_app.headers.get('Cache-Control'), 'no-store')
        old_app = client.get('/mini/legacy')
        self.assertIn(b'/mini/ux-381.js', old_app.data)
        self.assertEqual(client.post('/mini/api', json={'action': 'state'}).status_code,401)

    def test_api_does_not_respond_without_telegram_identity(self):
        client = self.app.test_client()
        response = client.post('/mini/api', json={'action': 'state'})
        self.assertEqual(response.status_code, 401)
        self.assertFalse(response.json['ok'])

    def test_profile_save_uses_compact_patch(self):
        from unittest.mock import patch
        with patch('main.mini_auth', return_value=123), \
             patch('main.mini_aux', return_value=True), \
             patch('main.metrics', return_value={'age': 30, 'weight_kg': 75}), \
             patch('main.health_profile', return_value={'affected': []}), \
             patch('main.heart_zones', return_value=[{'zone': 1}]):
            result = self.app.test_client().post('/mini/api', json={'action': 'save_metrics'})
        self.assertEqual(result.status_code, 200)
        self.assertTrue(result.json['ok'])
        self.assertNotIn('data', result.json)
        self.assertEqual(result.json['patch']['metrics']['age'], 30)
        self.assertIn('Server-Timing', result.headers)

    def test_start_returns_workout_only(self):
        from unittest.mock import patch
        with patch('main.mini_auth', return_value=123), \
             patch('main.mini_write', return_value=False), \
             patch('main.mini_workout_delta', return_value={'workout': {'id': 7}}):
            result = self.app.test_client().post('/mini/api', json={'action': 'start', 'mood':'normal'})
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json['patch']['workout']['id'], 7)
        self.assertNotIn('data', result.json)

    def test_feedback_and_version_assets(self):
        client=self.app.test_client()
        res=client.get('/mini/legacy')
        self.assertEqual(res.status_code,200)
        self.assertIn(b'ux-3811.js',res.data)
        self.assertIn(b'ux-3811.css',res.data)
        js=client.get('/mini/ux-3811.js')
        self.assertEqual(js.status_code,200)
        self.assertIn(b'fq-feedback-quick',js.data)
        self.assertIn(b'prepareHealthSubmission',js.data)
        self.assertIn(b'FORMIQ',js.data)
        css=client.get('/mini/ux-3811.css')
        self.assertEqual(css.status_code,200)
        self.assertIn(b'fq-version-footer',css.data)

    def test_exercise_photo_is_present_and_specific(self):
        client=self.app.test_client()
        photos=('chair_squat','partial_squat','wall_push','incline_push','bridge','bird','step','calf','wall_plank','side_step','hip_hinge','dead_bug','leg_press','lat_pull','chest_press','seated_row','db_press','leg_curl','leg_ext','cable_row')
        for key in photos:
            r=client.get('/mini/technique/'+key)
            self.assertEqual(r.status_code,200)
            self.assertIn(b'class="fq-exercise-photo"',r.data)
            self.assertIn(b'<img src="https://',r.data)
            self.assertIn(b'alt=',r.data)
        unknown=client.get('/mini/technique/unknown_fake')
        self.assertEqual(unknown.status_code,404)
        self.assertEqual(len(importlib.import_module('main').EXERCISE_PHOTOS),20)
        self.assertGreaterEqual(len(importlib.import_module('main').EX),95)

    def test_version(self):
        self.assertEqual(self.app.test_client().get('/').status_code, 200)
        self.assertIn(importlib.import_module('main').VERSION.encode(), self.app.test_client().get('/').data)


if __name__ == '__main__':
    unittest.main()
