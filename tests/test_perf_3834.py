"""FORMIQ 38.3.4: eliminate N+1 profile reads and retain schedule semantics."""
from datetime import date
from unittest.mock import Mock, MagicMock, patch
import importlib
import os
import unittest


class PerformanceRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with patch.dict(os.environ, {
            'TELEGRAM_BOT_TOKEN':'123456789:TESTONLY_no_real_token',
            'DATABASE_URL':'postgresql://test:test@localhost:5432/test',
            'RENDER_EXTERNAL_URL':'https://example.invalid',
        }):
            cls.app=importlib.import_module('main')

    def test_equipment_filter_does_not_use_database(self):
        p={'equipment':'homegear','equipment_description':'гантели 5 кг и коврик'}
        h={'affected':['shoulder']}
        with patch.object(self.app,'db',side_effect=AssertionError('unexpected DB read')):
            self.assertTrue(self.app.exercise_allowed_for_profile(p,h,'db_curl') is False)
            self.assertFalse(self.app.exercise_allowed_for_profile(p,h,'band_row'))
            self.assertTrue(self.app.exercise_allowed_for_profile(p,{'affected':[]},'db_row'))
            self.assertFalse(self.app.exercise_allowed_for_profile(p,{'affected':[]},'machine_row'))

    def test_user_session_reuses_known_health_and_custom(self):
        p={'equipment':'home','days':'3','level':'beginner','goal':'general','minutes':'40'}
        h={'affected':[],'pain_score':0,'danger_signs':False,
           'symptom_course':'none','activity_cleared':False}
        with patch.object(self.app,'db',side_effect=AssertionError('unexpected DB read')), \
             patch.object(self.app,'get_custom',side_effect=AssertionError('duplicate custom query')), \
             patch.object(self.app,'health_profile',side_effect=AssertionError('duplicate health query')):
            exercises=self.app.user_session(123,p,1,'A',loaded_custom=True,
                                            custom_keys=None,known_health=h)
        self.assertGreaterEqual(len(exercises),3)
        self.assertTrue(all(row[0] in self.app.EX for row in exercises))

    def test_readiness_reuses_prefetched_context_without_database(self):
        p={'goal':'general','level':'beginner','days':'3','equipment':'gym',
           'age_group':'adult','minutes':'50'}
        m={'age':30,'height_cm':180,'weight_kg':80}
        h={'affected':[],'pain_score':0,'danger_signs':False,
           'symptom_course':'none','activity_cleared':False}
        with patch.object(self.app,'db',side_effect=AssertionError('unexpected DB read')):
            self.assertIsNone(self.app.ready(p,123,known_health=h,
                                            known_metrics=m,known_agreement=True))
            self.assertIn('условия',self.app.ready(p,123,known_health=h,
                                  known_metrics=m,known_agreement=False))
            symptomatic={**h,'danger_signs':True}
            self.assertIn('небезопасно',self.app.ready(p,123,known_health=symptomatic,
                                  known_metrics=m,known_agreement=True))

    def test_schedule_insert_uses_one_query_and_preserves_manual_dates(self):
        conn=Mock()
        for days in (1,3,5,7):
            conn.reset_mock()
            self.app._insert_schedule_in(conn,1,5,days,date(2026,10,22))
            self.assertEqual(conn.execute.call_count,1)
            sql, params=conn.execute.call_args.args
            self.assertIn('ON CONFLICT(cycle_id,week_no,day_code) DO NOTHING',sql)
            self.assertEqual(len(params),days*4*5)
            self.assertEqual(sql.count('(%s,%s,%s,%s,%s)'),days*4)

    def test_next_session_batches_upsert(self):
        c=MagicMock()
        c.execute.return_value.fetchone.side_effect=[(date(2026,10,22),),('B',1,date(2026,10,24))]
        self.app.planned_next_in(c,1,5,3)
        self.assertEqual(c.execute.call_count,3)
        query=c.execute.call_args_list[1].args[0]
        self.assertIn('ON CONFLICT(cycle_id,week_no,day_code) DO NOTHING',query)

    def test_state_source_does_not_call_valid_exercise_for_each_catalog_entry(self):
        import inspect
        source=inspect.getsource(self.app.mini_state)
        self.assertIn('exercise_allowed_for_profile(p,h,k)',source)
        self.assertNotIn('if valid_exercise(chat,k)',source)
        self.assertIn('known_health=h',source)
        self.assertIn('loaded_custom=True',source)

if __name__=='__main__':
    unittest.main()
