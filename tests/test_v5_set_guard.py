"""Regression: V5 retries must not consume the next pending set.

Offline tests with mocked database; no Telegram token, PostgreSQL or real data.
"""
import importlib
import os
import unittest
from unittest.mock import MagicMock, patch


class V5SetIdentityGuard(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with patch.dict(os.environ, {
            'TELEGRAM_BOT_TOKEN': '123456789:TESTONLY_offline_token',
            'DATABASE_URL': 'postgresql://test:test@localhost:5432/test',
            'RENDER_EXTERNAL_URL': 'https://example.invalid',
        }):
            cls.mod = importlib.import_module('main')

    def run_write(self, payload, pending=(0, 2, 'reps', 'pending'), workout_id=57):
        conn = MagicMock()
        conn.__enter__.return_value = conn
        conn.execute.return_value.fetchone.return_value = pending
        with patch.object(self.mod, 'db', return_value=conn), \
             patch.object(self.mod, 'has_agreement', return_value=True), \
             patch.object(self.mod, 'mini_current', return_value=workout_id), \
             patch.object(self.mod, 'recalc_item') as recalc:
            try:
                result = self.mod.mini_write(101, 'record', payload)
                return conn, recalc, result, None
            except ValueError as error:
                return conn, recalc, None, str(error)

    def test_current_v5_set_is_saved_once(self):
        conn, recalc, result, error = self.run_write({
            'reps': 12, 'weight': 60,
            'expected_workout': 57,
            'expected_position': 0,
            'expected_set': 2,
        })
        self.assertIsNone(error)
        self.assertFalse(result)
        writes = [args.args[0] for args in conn.execute.call_args_list
                  if 'UPDATE workout_sets SET actual_value' in args.args[0]]
        self.assertEqual(len(writes), 1)
        recalc.assert_called_once_with(conn, 57, 0)

    def test_retry_cannot_overwrite_next_set(self):
        for stale in (
            {'expected_workout':57, 'expected_position':0, 'expected_set':1},
            {'expected_workout':56, 'expected_position':0, 'expected_set':2},
            {'expected_workout':57, 'expected_position':1, 'expected_set':2},
        ):
            with self.subTest(stale=stale):
                conn, recalc, result, error = self.run_write({'reps':12, **stale})
                self.assertIn('Обнови тренировку', error)
                self.assertFalse(any(
                    'UPDATE workout_sets SET actual_value' in c.args[0]
                    for c in conn.execute.call_args_list))
                recalc.assert_not_called()

    def test_partial_or_boolean_guard_rejected(self):
        for guard in (
            {'expected_workout':57},
            {'expected_workout':True,'expected_position':0,'expected_set':2},
            {'expected_workout':57,'expected_position':0,'expected_set':2.0},
        ):
            with self.subTest(guard=guard):
                conn, _, _, error = self.run_write({'reps':10, **guard})
                self.assertIn('Обнови тренировку', error)
                self.assertFalse(any(
                    'UPDATE workout_sets SET actual_value' in c.args[0]
                    for c in conn.execute.call_args_list))

    def test_legacy_client_without_guard_still_works(self):
        conn, recalc, _, error = self.run_write({'reps':8})
        self.assertIsNone(error)
        self.assertTrue(any(
            'UPDATE workout_sets SET actual_value' in c.args[0]
            for c in conn.execute.call_args_list))
        recalc.assert_called_once()

if __name__ == '__main__':
    unittest.main()
