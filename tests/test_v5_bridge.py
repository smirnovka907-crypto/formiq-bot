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

    def test_history_page_scoped_to_telegram_owner_and_paginated(self):
        from datetime import datetime, timezone
        from unittest.mock import MagicMock
        dt = datetime(2026, 10, 23, 12, tzinfo=timezone.utc)
        conn = MagicMock()
        conn.__enter__.return_value = conn
        conn.execute.return_value.fetchall.return_value = [
            (35, dt, 'workout', 'A', 'Зал', None, None),
            (-12, dt, 'cardio', None, None, 60, 'cycling'),
            (34, dt, 'workout', 'B', 'Другая тренировка', None, None),
        ]
        with patch.object(self.mod, 'db', return_value=conn), \
             patch.object(self.mod, 'profile', return_value={'goal':'general'}):
            result = self.mod.mini_history_page(777, {'offset': 0, 'limit': 2})
        query, params = conn.execute.call_args.args
        self.assertEqual(params, (777, 777, 3, 0))
        self.assertIn('FROM workouts', query)
        self.assertIn('FROM cardio_sessions', query)
        self.assertEqual(query.count('chat_id=%s'), 2)
        self.assertEqual(result['next_offset'], 2)
        self.assertEqual([row['id'] for row in result['history']], [35, -12])
        self.assertEqual(result['history'][1]['title'], 'Велосипед · 60 мин')

    def test_history_month_uses_owner_and_month_boundaries(self):
        from datetime import date
        from unittest.mock import MagicMock
        conn = MagicMock()
        conn.__enter__.return_value = conn
        conn.execute.return_value.fetchall.side_effect = [
            [(date(2026, 10, 23),), (date(2026, 10, 19),)],
            [(date(2026, 10, 23),)],
        ]
        with patch.object(self.mod, 'db', return_value=conn):
            result = self.mod.mini_history_month(777, {'month': '2026-10'})
        self.assertEqual(result['dates'], ['2026-10-19', '2026-10-23'])
        from datetime import datetime, timezone
        month_queries = [c for c in conn.execute.call_args_list
                         if 'SELECT DISTINCT' in c.args[0]]
        self.assertEqual(len(month_queries), 2)
        for c in month_queries:
            self.assertEqual(c.args[1], (
                'Europe/Moscow', 777,
                datetime(2026,9,30,21,tzinfo=timezone.utc),
                datetime(2026,10,31,21,tzinfo=timezone.utc)))
            self.assertIn('chat_id=%s', c.args[0])
            self.assertIn('AT TIME ZONE %s', c.args[0])

    def test_history_validation_rejects_bad_dates_and_offsets(self):
        for payload in [
            {'offset': -1}, {'offset': True}, {'limit': 51},
            {'limit': 0}, {'date':'2026-02-30'}, {'date':'yesterday'}
        ]:
            with self.assertRaises(ValueError):
                self.mod.mini_history_page(777, payload)
        for value in ['2026-13', 'x', '2026-2', '', None, '1900-01']:
            with self.assertRaises(ValueError):
                self.mod.mini_history_month(777, {'month': value})

    def test_cardio_activity_saved_as_validated_existing_equipment(self):
        from unittest.mock import MagicMock
        conn = MagicMock()
        conn.__enter__.return_value = conn
        with patch.object(self.mod, 'db', return_value=conn), \
             patch.object(self.mod, 'require_tier'):
            self.mod.mini_aux(777, 'cardio', {
                'minutes': 60, 'avg_hr': 120, 'type': 'Велосипед'})
        sql, params = conn.execute.call_args.args
        self.assertIn('cardio_sessions', sql)
        self.assertIn('equipment', sql)
        self.assertEqual(params, (777, 60, 120, 'cycling'))
        with patch.object(self.mod, 'require_tier'), \
             patch.object(self.mod, 'db', return_value=conn):
            with self.assertRaises(ValueError):
                self.mod.mini_aux(777, 'cardio', {
                    'minutes': 30, 'avg_hr': None, 'type': 'Неизвестно'})


    def test_signed_v5_workout_and_history_api_contract(self):
        """Flask dispatches authenticated actions without touching real DB."""
        actions = [
            ('start', {'mood': 'normal'}, 'workout', 'mini_write'),
            ('record', {'reps': 12, 'weight': 60}, 'workout', 'mini_write'),
            ('skip', {}, 'workout', 'mini_write'),
            ('finish', {}, 'data', 'mini_write'),
            ('cardio', {'minutes': 60, 'avg_hr': 120, 'type': 'Велосипед'},
             'data', 'mini_aux'),
            ('history_page', {'offset': 0, 'limit': 30},
             'history', 'mini_history_page'),
            ('history_month', {'month': '2026-10'}, 'dates',
             'mini_history_month'),
            ('detail', {'id': 8}, 'detail', 'mini_aux'),
        ]
        for action, extra, expected, dispatcher in actions:
            with self.subTest(action=action), \
                 patch.object(self.mod, 'mini_auth', return_value=777) as auth, \
                 patch.object(self.mod, 'mini_write', return_value=False) as write, \
                 patch.object(self.mod, 'mini_aux', return_value={'detail': {'title':'Зал'}}) as aux, \
                 patch.object(self.mod, 'mini_state', return_value={'history': []}) as state, \
                 patch.object(self.mod, 'mini_workout_delta',
                              return_value={'workout': {'id': 4}}) as delta, \
                 patch.object(self.mod, 'mini_history_page',
                              return_value={'history': []}) as history_page, \
                 patch.object(self.mod, 'mini_history_month',
                              return_value={'dates': ['2026-10-23']}) as history_month:
                payload = {'action': action, **extra}
                response = self.client.post('/mini/api',
                    json=payload, headers={'X-Formiq-Init':'signed-for-test'})
                self.assertEqual(response.status_code, 200, action)
                data = response.get_json()
                self.assertTrue(data.get('ok'), action)
                if expected == 'workout':
                    self.assertIn('patch', data, action)
                    self.assertIn('workout', data['patch'], action)
                else:
                    self.assertIn(expected, data, action)
                auth.assert_called_once_with('signed-for-test')
                if dispatcher == 'mini_write':
                    write.assert_called_once_with(777, action, payload)
                elif dispatcher == 'mini_aux':
                    aux.assert_called_once_with(777, action, payload)
                elif dispatcher == 'mini_history_page':
                    history_page.assert_called_once_with(777, payload)
                elif dispatcher == 'mini_history_month':
                    history_month.assert_called_once_with(777, payload)
                if action in ('start','record','skip'):
                    delta.assert_called_once_with(777)
                if action == 'finish':
                    state.assert_called_once_with(777, False)

    def test_signed_api_rejects_invalid_payload_without_database(self):
        with patch.object(self.mod, 'mini_auth', return_value=777), \
             patch.object(self.mod, 'mini_write') as write:
            result = self.client.post('/mini/api',
                data='not-json', headers={'X-Formiq-Init':'signed-for-test'},
                content_type='text/plain')
            self.assertEqual(result.status_code, 415)
            write.assert_not_called()

    def test_profile_weight_patch_updates_only_owned_metric_column(self):
        from decimal import Decimal
        from unittest.mock import MagicMock
        conn = MagicMock()
        conn.__enter__.return_value = conn
        conn.execute.return_value.rowcount = 1
        with patch.object(self.mod, 'db', return_value=conn):
            self.mod.save_metrics(777, {'metrics': {'weight_kg': '84,5'}})
        sql, params = conn.execute.call_args.args
        self.assertIn('UPDATE profile_metrics SET weight_kg=%s', sql)
        self.assertIn('WHERE chat_id=%s', sql)
        self.assertNotIn('height_cm=', sql)
        self.assertNotIn('age=', sql)
        self.assertNotIn('resting_hr=', sql)
        self.assertNotIn('DELETE', sql)
        self.assertEqual(params, (Decimal('84.5'), 777))
        self.assertEqual(conn.execute.call_count, 1)

    def test_profile_metrics_validation_rejects_unsafe_values_before_database(self):
        for metrics in ({'age': 10}, {'weight_kg': 999},
                        {'height_cm': 'NaN'}, {'weight_kg': '85', 'workouts': 1},
                        {}):
            with patch.object(self.mod, 'db') as conn:
                with self.assertRaises(ValueError):
                    self.mod.save_metrics(777, {'metrics': metrics})
                conn.assert_not_called()

    def test_signed_profile_metric_api_response_keeps_history_unchanged(self):
        with patch.object(self.mod, 'mini_auth', return_value=777), \
             patch.object(self.mod, 'mini_aux') as aux, \
             patch.object(self.mod, 'metrics', return_value={
                 'age': 34, 'height_cm': 181, 'weight_kg': 84.5
             }) as metrics, \
             patch.object(self.mod, 'health_profile', return_value=None), \
             patch.object(self.mod, 'heart_zones', return_value=[]) as zones, \
             patch.object(self.mod, 'mini_state') as state:
            payload = {'action': 'save_metrics', 'metrics': {'weight_kg': 84.5}}
            response = self.client.post('/mini/api', json=payload,
                headers={'X-Formiq-Init':'signed-for-test'})
            self.assertEqual(response.status_code, 200)
            data = response.get_json()
            self.assertTrue(data['ok'])
            self.assertEqual(data['patch']['metrics']['weight_kg'], 84.5)
            self.assertNotIn('history', data['patch'])
            aux.assert_called_once_with(777, 'save_metrics', payload)
            metrics.assert_called_once_with(777)
            zones.assert_called_once()
            state.assert_not_called()




    def test_rest_timer_resumes_from_saved_postgres_set(self):
        from decimal import Decimal
        from unittest.mock import MagicMock
        conn=MagicMock()
        p={'goal':'general','level':'some'}
        conn.execute.return_value.fetchone.return_value=('done','reps','leg_press',Decimal('50.25'))
        self.assertEqual(self.mod.workout_rest_remaining(conn,91,p),70)
        query,args=conn.execute.call_args.args
        self.assertIn("s.state IN ('done', 'skipped')",query)
        self.assertIn('NOW() - s.completed_at',query)
        self.assertEqual(args,(91,))
        conn.execute.return_value.fetchone.return_value=('skipped','reps','leg_press',Decimal('1'))
        self.assertEqual(self.mod.workout_rest_remaining(conn,91,p),0)
        conn.execute.return_value.fetchone.return_value=('done','reps','leg_press',Decimal('210'))
        self.assertEqual(self.mod.workout_rest_remaining(conn,91,p),0)
        conn.execute.return_value.fetchone.return_value=('done','min','elliptical',Decimal('1'))
        self.assertEqual(self.mod.workout_rest_remaining(conn,91,p),0)


if __name__ == '__main__':
    unittest.main()
