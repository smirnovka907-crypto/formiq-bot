"""Regression tests for FORMIQ 38.2.0. No production database or Telegram access."""
import importlib
import os
import unittest
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock


class Release382Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with patch.dict(os.environ, {
            'TELEGRAM_BOT_TOKEN':'123456789:TESTONLY_no_real_token',
            'DATABASE_URL':'postgresql://test:test@localhost:5432/test',
            'RENDER_EXTERNAL_URL':'https://example.invalid',
        }):
            cls.m=importlib.import_module('main')

    def test_renamed_training_titles(self):
        p={'equipment':'home','days':'4','level':'some','goal':'general','minutes':'40'}
        self.assertEqual(self.m.day_title(p,'A'),'Ноги и пресс')
        self.assertNotIn('корпус',self.m.day_title(p,'C').lower())

    def test_gym_recovery_is_not_a_ten_minute_visit(self):
        p={'equipment':'gym','days':'5','level':'some','goal':'general','minutes':'45'}
        exercises=self.m.make_session(p,1,'B')
        self.assertGreaterEqual(len(exercises),3)
        self.assertEqual(exercises[0][0],'elliptical')
        self.assertGreaterEqual(exercises[0][2],20)
        self.assertEqual(self.m.day_title(p,'B'),'Кардио и подвижность')

    def test_home_inventory_filter(self):
        p={'equipment':'homegear','equipment_description':'только эспандеры и коврик'}
        self.assertFalse(self.m.equipment_available(p,'db_row'))
        self.assertTrue(self.m.equipment_available(p,'band_row'))
        self.assertTrue(self.m.equipment_available(p,'bird'))
        p['equipment_description']='гантели 5 кг'
        self.assertTrue(self.m.equipment_available(p,'db_row'))
        self.assertFalse(self.m.equipment_available(p,'band_row'))

    def test_cardio_history_details_are_owned(self):
        when=datetime(2026,10,22,tzinfo=timezone.utc)
        fake=MagicMock()
        fake.__enter__.return_value=fake
        fake.execute.return_value.fetchone.return_value=(when,35,118,'cycling',None,None,None,None)
        with patch.object(self.m,'db',return_value=fake):
            result=self.m.mini_history_detail(123,-8)
        query,params=fake.execute.call_args.args
        self.assertIn('cardio_sessions',query)
        self.assertIn('chat_id=%s',query)
        self.assertEqual(params,(8,123))
        self.assertEqual(result['title'],'Дополнительная тренировка · Велосипед')
        self.assertEqual(len(result['items']),3)
        self.assertEqual(result['items'][0]['result'],'Велосипед')

    def test_mini_frontend_routes_and_version(self):
        client=self.m.APP.test_client()
        self.assertIn(f'FORMIQ {self.m.VERSION} online'.encode(),client.get('/').data)
        page=client.get('/mini/legacy')
        self.assertIn(b'v5-live.js',page.data)
        self.assertNotIn(b'/mini/ux-382',page.data)
        self.assertEqual(client.get('/mini/ux-382.css').status_code,200)
        self.assertEqual(client.get('/mini/ux-382.js').status_code,200)

    def test_public_api_rejects_unauthorized_analysis(self):
        resp=self.m.APP.test_client().post('/mini/api',
            json={'action':'equipment_analyze','text':'гантели','privacy_ack':True,'adult':True})
        self.assertEqual(resp.status_code,401)


if __name__=='__main__':
    unittest.main()
