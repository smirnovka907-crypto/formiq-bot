"""Read-only local calendar tests; no production database or Telegram requests."""
import importlib
import os
import unittest
from datetime import date, datetime, timezone
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo


class HistoryLocalDayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with patch.dict(os.environ, {
            'TELEGRAM_BOT_TOKEN': '123456789:TESTONLY_tz',
            'DATABASE_URL': 'postgresql://test:test@localhost:5432/test',
            'RENDER_EXTERNAL_URL': 'https://example.invalid',
        }):
            cls.m = importlib.import_module('main')

    def test_moscow_after_midnight_display(self):
        recorded = datetime(2026, 10, 22, 22, 40, tzinfo=timezone.utc)
        self.assertEqual(
            self.m.history_local_date(recorded, ZoneInfo('Europe/Moscow')),
            '23.10.2026')

    def test_local_date_range_uses_utc_instants(self):
        a, b = self.m.history_day_bounds(date(2026, 10, 23),
                                         ZoneInfo('Asia/Tokyo'))
        self.assertEqual(a, datetime(2026,10,22,15,tzinfo=timezone.utc))
        self.assertEqual(b, datetime(2026,10,23,15,tzinfo=timezone.utc))

    def test_dst_day_is_25_hours_in_helsinki(self):
        a, b = self.m.history_day_bounds(date(2026, 10, 25),
                                         ZoneInfo('Europe/Helsinki'))
        self.assertEqual(a, datetime(2026,10,24,21,tzinfo=timezone.utc))
        self.assertEqual(b, datetime(2026,10,25,22,tzinfo=timezone.utc))
        self.assertEqual((b-a).total_seconds(), 25*3600)

    def test_history_page_filters_user_local_date_without_deleting_data(self):
        user = 777
        timestamp = datetime(2026,10,22,23,35,tzinfo=timezone.utc)
        conn = MagicMock()
        conn.__enter__.return_value = conn

        def select(query, params):
            cursor = MagicMock()
            if 'SELECT timezone FROM profile_metrics' in query:
                self.assertEqual(params, (user,))
                cursor.fetchone.return_value = ('Asia/Tokyo',)
            else:
                self.assertIn('FROM workouts', query)
                self.assertIn('FROM cardio_sessions', query)
                self.assertNotIn('DELETE', query.upper())
                self.assertEqual(params, (
                    user,
                    datetime(2026,10,22,15,tzinfo=timezone.utc),
                    datetime(2026,10,23,15,tzinfo=timezone.utc),
                    user,
                    datetime(2026,10,22,15,tzinfo=timezone.utc),
                    datetime(2026,10,23,15,tzinfo=timezone.utc),
                    11,0))
                cursor.fetchall.return_value = [
                    (20,timestamp,'workout','A','Тренировка',None,None,None,None,None)]
            return cursor

        conn.execute.side_effect = select
        with patch.object(self.m, 'db', return_value=conn), \
             patch.object(self.m, 'profile', return_value={'goal':'general'}):
            response = self.m.mini_history_page(user, {
                'date':'2026-10-23','limit':10,'offset':0})
        self.assertEqual(response['history'][0]['date'], '23.10.2026')
        self.assertEqual(response['history'][0]['id'], 20)

    def test_timezone_from_profile_is_validated_and_falls_back(self):
        conn = MagicMock()
        conn.__enter__.return_value = conn
        for stored, expected in [
            ('Europe/Helsinki','Europe/Helsinki'),
            ('Invalid/BadZone','Europe/Moscow'),
            (None,'Europe/Moscow'),
        ]:
            conn.execute.return_value.fetchone.return_value = (stored,)
            with patch.object(self.m, 'db', return_value=conn):
                zone = self.m.history_local_zone(777)
            self.assertEqual(zone.key, expected)


if __name__ == '__main__':
    unittest.main()
