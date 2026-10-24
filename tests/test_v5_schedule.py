"""Weekday scheduling regressions. No real database, Telegram, or network."""
import importlib
import os
import unittest
from datetime import date, timedelta
from unittest.mock import MagicMock, patch


class WeekdayScheduleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with patch.dict(os.environ, {
            'TELEGRAM_BOT_TOKEN':'123456789:TESTONLY_schedule',
            'DATABASE_URL':'postgresql://test:test@localhost:5432/test',
            'RENDER_EXTERNAL_URL':'https://example.invalid',
        }):
            cls.m = importlib.import_module('main')

    def test_startup_schema_changes_fail_fast_when_locked(self):
        db_connection = MagicMock()
        db_connection.__enter__.return_value = db_connection
        with patch.object(self.m, 'db', return_value=db_connection):
            self.m.init_db()
        sql_statements = [call.args[0] for call in db_connection.execute.call_args_list]
        self.assertEqual(sql_statements[:2], [
            "SET LOCAL lock_timeout = '5s'",
            "SET LOCAL statement_timeout = '30s'",
        ])
        self.assertTrue(any('ADD COLUMN IF NOT EXISTS weekdays' in statement
                            for statement in sql_statements))
        self.assertTrue(any('ADD COLUMN IF NOT EXISTS schedule_state' in statement
                            for statement in sql_statements))

    def test_all_frequencies_match_selected_civil_weekdays(self):
        start = date(2026,10,23)  # Friday; includes the DST transition weekend.
        for count in range(1,8):
            selected = list(range(count))
            updates,slots = self.m.schedule_reconciliation([],start,count,selected,start)
            self.assertEqual(updates,[])
            self.assertEqual(len(slots),4*count)
            self.assertEqual({dt.weekday() for _,_,dt in slots},set(selected))
            self.assertTrue(all(start<=dt<=start+timedelta(days=27) for _,_,dt in slots))
            self.assertEqual(len({(week,day) for week,day,_ in slots}),len(slots))
            for week,day,dt in slots[count:]:
                prior = next(x for x in slots if x[0]==week-1 and x[1]==day)
                self.assertEqual((dt-prior[2]).days,7)

    def test_weekdays_are_canonical_and_invalid_values_are_rejected(self):
        self.assertEqual(self.m.validate_weekdays([6,0,3],3),[0,3,6])
        for raw,count in [([True],1),([1.0],1),(['1'],1),([7],1),([-1],1),
                          ([0,0],2),([],1),([0],2),(None,1),('0',1)]:
            with self.subTest(raw=raw,count=count),self.assertRaises(ValueError):
                self.m.validate_weekdays(raw,count)

    def test_legacy_without_weekdays_keeps_existing_dates(self):
        start = date(2026,10,19)
        rows = [(1,1,'A',start,None,False),
                (2,1,'B',start+timedelta(days=6),None,False)]
        updates,slots = self.m.schedule_reconciliation(rows,start,2,None,start)
        self.assertEqual(updates,[])
        self.assertNotIn((1,'B',start+timedelta(days=3)),slots)

    def test_first_adoption_protects_history_today_and_manual_dates(self):
        start = date(2026,10,19)
        today = start+timedelta(days=1)
        rows = [
            (1,1,'A',start,None,False),             # Past.
            (2,1,'B',today,None,False),             # Today and legacy mismatch.
            (3,2,'A',start+timedelta(days=7),None,False),  # Exact baseline.
            (4,2,'B',start+timedelta(days=12),None,False), # Legacy manual move.
            (5,3,'A',start+timedelta(days=14),'auto',True), # Any linked workout.
            (6,3,'B',start+timedelta(days=17),'manual',False),
        ]
        updates,_ = self.m.schedule_reconciliation(rows,start,2,[1,4],today,infer_count=2)
        self.assertEqual(updates,[(3,start+timedelta(days=8),'auto')])

    def test_retirement_survives_time_and_reactivation_only_changes_future(self):
        start = date(2026,10,19)
        rows = [(1,2,'C',start+timedelta(days=11),'auto',False)]
        updates,_ = self.m.schedule_reconciliation(rows,start,2,[0,2],start)
        self.assertEqual(updates,[(1,start+timedelta(days=11),'retired')])
        retired = [(1,2,'C',updates[0][1],'retired',False)]
        later,_ = self.m.schedule_reconciliation(retired,start,2,[0,2],start+timedelta(days=15))
        self.assertEqual(later,[])
        active,_ = self.m.schedule_reconciliation(retired,start,3,[0,2,4],start)
        self.assertEqual(active,[(1,start+timedelta(days=11),'auto')])
        past,_ = self.m.schedule_reconciliation(retired,start,3,[0,2,4],start+timedelta(days=15))
        self.assertEqual(past,[])

    def test_changes_never_create_past_or_today_slots_in_existing_cycle(self):
        start = date(2026,10,19)
        today = start+timedelta(days=10)
        rows = [(1,1,'A',start,'auto',True)]
        _,inserts = self.m.schedule_reconciliation(rows,start,7,list(range(7)),today)
        self.assertTrue(inserts)
        self.assertTrue(all(dt>today for _,_,dt in inserts))

    def test_earlier_new_weekday_retires_future_auto_slot_instead_of_keeping_wrong_day(self):
        start = date(2026,10,19)
        rows = [(1,1,'A',date(2026,10,21),'auto',False),
                (2,1,'B',date(2026,10,23),'auto',False)]
        updates,_ = self.m.schedule_reconciliation(rows,start,2,[0,3],date(2026,10,20))
        self.assertEqual(updates,[(1,date(2026,10,21),'retired'),
                                  (2,date(2026,10,22),'auto')])

    def test_calendar_read_cannot_bypass_timezone_edit_cutoff(self):
        conn = MagicMock()
        p = {'days':'2','weekdays':[0,2]}
        self.m.reconcile_schedule_in(conn,777,8,date(2026,10,19),p,date(2026,10,19))
        conn.execute.assert_not_called()

    def test_stale_dashboard_profile_is_reloaded_after_user_lock(self):
        conn = MagicMock()
        conn.__enter__.return_value = conn
        fresh = {'goal':'general','level':'some','days':'3','equipment':'home',
                 'age_group':'adult','minutes':'40','clearance':'none','weekdays':[0,2,4]}
        def read_profile(c,chat):
            self.assertIn('pg_advisory_xact_lock',conn.execute.call_args.args[0])
            return fresh
        with patch.object(self.m,'db',return_value=conn), \
             patch.object(self.m,'profile_in',side_effect=read_profile), \
             patch.object(self.m,'cycle_status',return_value=(5,1)) as cycle:
            self.assertEqual(self.m.get_cycle(777,{'days':'1'}),(5,1))
        cycle.assert_called_once_with(conn,777,fresh)

    def test_pinned_day_above_reduced_frequency_can_still_start(self):
        limits = {'affected':[],'pain_score':0,'symptom_course':'none',
                  'danger_signs':False,'activity_cleared':False}
        for equipment in ('home','gym'):
            p = {'goal':'general','level':'some','days':'2','equipment':equipment,'minutes':'40'}
            with patch.object(self.m,'get_custom',return_value=None), \
                 patch.object(self.m,'health_profile',return_value=limits):
                for day in 'CDEFG':
                    self.assertTrue(self.m.make_session(p,1,day))
                    self.assertTrue(self.m.user_session(777,p,1,day))

    def test_reconcile_writes_are_scoped_and_never_touch_workout_tables(self):
        conn = MagicMock()
        start = date(2026,10,19)
        conn.execute.return_value.fetchall.return_value = [
            (9,2,'A',start+timedelta(days=7),'auto',False)]
        p = {'days':'2','weekdays':[1,4]}
        self.m.reconcile_schedule_in(conn,777,8,start,p,start,reconcile_existing=True)
        writes = [call.args for call in conn.execute.call_args_list
                  if call.args[0].lstrip().startswith(('UPDATE','INSERT'))]
        self.assertTrue(writes)
        for sql,params in writes:
            self.assertIn('scheduled_sessions',sql)
            self.assertNotIn('DELETE',sql)
            self.assertIn(777,params)
            self.assertIn(8,params)

    def test_old_profile_mutations_cannot_break_saved_weekdays_after_lock(self):
        conn = MagicMock()
        conn.__enter__.return_value = conn
        with patch.object(self.m,'db',return_value=conn), \
             patch.object(self.m,'profile_in',return_value={'days':'2','weekdays':[0,2]}):
            self.assertFalse(self.m.reset_profile(777))
            self.assertFalse(self.m.save_answer(777,'days','7'))
        self.assertTrue(all('pg_advisory_xact_lock' in call.args[0]
                            for call in conn.execute.call_args_list))

    def test_expired_wake_acknowledgement_is_not_an_app_failure(self):
        from types import SimpleNamespace
        error = self.m.telebot.apihelper.ApiTelegramException(
            'answerCallbackQuery', None, {
                'error_code': 400,
                'description': 'Bad Request: query is too old and response timeout expired or query ID is invalid'})
        call = SimpleNamespace(data='wake', id='stale-test',
            from_user=SimpleNamespace(id=777),
            message=SimpleNamespace(chat=SimpleNamespace(id=777, type='private')))
        with patch.object(self.m.BOT, 'answer_callback_query', side_effect=error) as answer, \
             patch.object(self.m.LOG, 'exception') as failed, \
             patch.object(self.m.LOG, 'debug') as ignored:
            self.m.callback(call)
        answer.assert_called_once()
        failed.assert_not_called()
        ignored.assert_called_once()

    def test_unexpected_wake_acknowledgement_error_is_logged(self):
        from types import SimpleNamespace
        error = self.m.telebot.apihelper.ApiTelegramException(
            'answerCallbackQuery', None, {
                'error_code': 403,
                'description': 'Forbidden: bot was blocked by the user'})
        call = SimpleNamespace(data='wake', id='failed-test',
            from_user=SimpleNamespace(id=777),
            message=SimpleNamespace(chat=SimpleNamespace(id=777, type='private')))
        with patch.object(self.m.BOT, 'answer_callback_query', side_effect=error), \
             patch.object(self.m.LOG, 'exception') as failed:
            self.m.callback(call)
        failed.assert_called_once_with('Telegram wake acknowledgement failed')

    def test_old_telegram_questionnaire_buttons_open_current_app(self):
        from types import SimpleNamespace
        for action in ('restart','restart_yes','answer:2:7'):
            call = SimpleNamespace(data=action,id='offline-test',
                from_user=SimpleNamespace(id=777),
                message=SimpleNamespace(message_id=15,
                    chat=SimpleNamespace(id=777,type='private')))
            with patch.object(self.m.BOT,'answer_callback_query'), \
                 patch.object(self.m,'profile',return_value={'weekdays':[0,2]}), \
                 patch.object(self.m,'mini_entry') as entry, \
                 patch.object(self.m,'reset_profile') as reset, \
                 patch.object(self.m,'save_answer') as answer:
                self.m.callback(call)
            entry.assert_called_once_with(777,15)
            reset.assert_not_called()
            answer.assert_not_called()


if __name__=='__main__':
    unittest.main()
