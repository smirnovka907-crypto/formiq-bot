"""Exercise cards: verified mapping and non-invented movement instructions."""
import importlib
import os
import unittest
from unittest.mock import patch


class ExerciseCardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with patch.dict(os.environ, {
            'TELEGRAM_BOT_TOKEN': '123456789:TESTONLY_exercise_media',
            'DATABASE_URL': 'postgresql://unused:unused@example.invalid/never_connect',
            'RENDER_EXTERNAL_URL': 'https://example.invalid',
        }):
            cls.app = importlib.import_module('main')

    def test_media_matches_actual_movement(self):
        app = self.app
        self.assertIsNone(app.exercise_card_details('chair_squat')['image_url'])
        self.assertIsNone(app.exercise_card_details('calf')['image_url'])
        self.assertIsNone(app.exercise_card_details('wall_push')['image_url'])
        self.assertIn('стул', app.exercise_card_details('chair_squat')['start_position'])
        self.assertIn('стопы', app.exercise_card_details('leg_press')['start_position'])
        self.assertIn('таз', app.exercise_card_details('bridge')['steps'][0])
        for key, pair in app.EXERCISE_PHOTOS.items():
            image_url, credit = pair
            self.assertIn(key, app.EX)
            self.assertTrue(image_url.startswith(
                'https://raw.githubusercontent.com/yuhonas/free-exercise-db/main/exercises/'))
            self.assertTrue(image_url.endswith('/0.jpg'))
            self.assertIn('Everkinetic', credit)
            result = app.exercise_card_details(key)
            self.assertEqual(result['image_url'], image_url)
            self.assertEqual(result['image_credit'], credit)
            self.assertEqual(result['image_license_url'],
                             'https://creativecommons.org/licenses/by-sa/4.0/')
            self.assertTrue(result['steps'])
            self.assertTrue(result['mistakes'])

    def test_no_fabricated_image_or_start_position_for_unknown_cues(self):
        app = self.app
        found = app.exercise_card_details('band_curl')
        self.assertIsNone(found['image_url'])
        self.assertIsNone(found['start_position'])
        self.assertEqual(found['steps'], [app.EX['band_curl'][1]])
        self.assertEqual(found['mistakes'], app.EX['band_curl'][2])
        unknown = app.exercise_card_details('__does_not_exist__')
        self.assertFalse(unknown['steps'])
        self.assertIsNone(unknown['image_url'])


if __name__ == '__main__':
    unittest.main()
