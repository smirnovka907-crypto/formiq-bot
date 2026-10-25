"""Opt-in PostgreSQL regression tests. Never use the application's DATABASE_URL.

Each test owns an isolated schema in an explicitly named local test database.
GitHub Actions supplies a disposable PostgreSQL service for these tests.
"""
import importlib
import os
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from threading import Barrier
from unittest.mock import patch
from urllib.parse import urlparse

import psycopg
from psycopg import sql


TEST_URL = os.environ.get('FORMIQ_TEST_DATABASE_URL')


class Clock(datetime):
    instant = datetime(2026, 10, 19, 12, tzinfo=timezone.utc)

    @classmethod
    def now(cls, tz=None):
        return cls.instant.astimezone(tz) if tz else cls.instant.replace(tzinfo=None)


@unittest.skipUnless(TEST_URL, 'FORMIQ_TEST_DATABASE_URL not supplied')
class SchedulePostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        target = urlparse(TEST_URL)
        if (target.hostname not in ('localhost', '127.0.0.1', 'postgres')
                or not target.path.rstrip('/').endswith('_test')):
            raise RuntimeError('Scheduling regressions require a local *_test database')
        with patch.dict(os.environ, {
            'TELEGRAM_BOT_TOKEN': '123456789:TESTONLY_schedule',
            'DATABASE_URL': 'postgresql://unused:unused@example.invalid/never_connect',
            'RENDER_EXTERNAL_URL': 'https://example.invalid',
        }):
            cls.m = importlib.import_module('main')

    def setUp(self):
        self.schema = 'formiq_schedule_regression_' + uuid.uuid4().hex
        with psycopg.connect(TEST_URL) as conn:
            conn.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(self.schema)))
        self.addCleanup(self.drop_schema)
        self.db_patch = patch.object(self.m, 'db', self.connect)
        self.db_patch.start()
        self.addCleanup(self.db_patch.stop)
        Clock.instant = datetime(2026, 10, 19, 12, tzinfo=timezone.utc)
        self.clock_patch = patch.object(self.m, 'datetime', Clock)
        self.clock_patch.start()
        self.addCleanup(self.clock_patch.stop)
        self.m.init_db()
        self.chat = 777

    def connect(self):
        return psycopg.connect(TEST_URL, options='-c search_path=' + self.schema
                               + ' -c statement_timeout=15000')

    def drop_schema(self):
        with psycopg.connect(TEST_URL) as conn:
            conn.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(self.schema)))

    def body(self, weekdays=(0, 2, 4), *, days=None, zone='Europe/Helsinki'):
        answers = dict(goal='general', level='beginner', days=str(days or len(weekdays)),
                       equipment='gym', age_group='adult', minutes='45')
        if weekdays is not None:
            answers['weekdays'] = list(weekdays)
        return dict(answers=answers, metrics=dict(age=34, height_cm=181, weight_kg=82,
                    resting_hr=60, sex='male'), timezone=zone,
                    health_profile=dict(affected=[], pain_score=0, symptom_course='none',
                    danger_signs=False, activity_cleared=False),
                    equipment_description='', terms=True, privacy=True, health=True)

    def save(self, weekdays=(0, 2, 4), **kwargs):
        self.m.save_onboarding(self.chat, self.body(weekdays, **kwargs))
        profile = self.m.profile(self.chat)
        cycle, _ = self.m.get_cycle(self.chat, profile)
        return profile, cycle, self.m.scheduled_calendar(self.chat, profile, cycle)

    def test_initial_onboarding_persists_four_weeks_before_first_state_read(self):
        # The first save must produce a durable calendar even if the next
        # network request fails; no lazy creation in state/get_cycle required.
        self.m.save_onboarding(self.chat, self.body())
        with self.connect() as conn:
            cycles=conn.execute('''SELECT id,starts_on FROM training_cycles
                WHERE chat_id=%s''',(self.chat,)).fetchall()
            self.assertEqual(len(cycles),1)
            slots=conn.execute('''SELECT week_no,planned_date,schedule_state
                FROM scheduled_sessions WHERE chat_id=%s AND cycle_id=%s''',
                (self.chat,cycles[0][0])).fetchall()
        self.assertEqual(len(slots),12)
        self.assertEqual({week for week,_,_ in slots},{1,2,3,4})
        self.assertTrue(all(status=='auto' for _,_,status in slots))

    def test_health_safety_hold_retains_calendar_but_never_offers_exercises(self):
        body=self.body()
        body['health_profile']=dict(affected=['other'],pain_score=0,
            symptom_course='unspecified',danger_signs=False,activity_cleared=False)
        self.m.save_onboarding(self.chat,body)
        result=self.m.mini_state(self.chat)
        self.assertTrue(result['agreed'])
        self.assertEqual(len(result['calendar']),12)
        self.assertEqual(result['plan'],[])
        self.assertIn('Другое',result['plan_warning'])
        self.assertIsNotNone(result['cycle_start'])

    def test_manual_food_parse_history_edits_and_owner_isolation(self):
        parsed=self.m.food_parse({'text':'овсянка 70 грамм, творог 5% 200 грамм, яблоко'})
        self.assertEqual([(x['name'],x['grams']) for x in parsed['items']],
                         [('овсянка',70),('творог 5%',200)])
        self.assertEqual(len(parsed['unparsed']),1)
        self.m.save_onboarding(self.chat,self.body())
        data=self.m.food_add(self.chat,{'date':'2026-10-18','meal_type':'breakfast',
            'items':parsed['items']})
        self.assertEqual(len(data['meals']),1)
        self.assertEqual(len(data['meals'][0]['items']),2)
        self.assertIsNone(data['meals'][0]['items'][0]['kcal'])
        item_id=data['meals'][0]['items'][0]['id']
        another=self.m.food_add(self.chat,{'date':'2026-10-18','meal_type':'breakfast',
            'items':[{'name':'банан','grams':110}]})
        self.assertEqual(len(another['meals']),2,'Multiple meals of same type on same day')
        self.m.food_add(self.chat,{'date':'2026-10-17','meal_type':'dinner',
            'items':[{'name':'рис сухой','grams':90}]})
        updated=self.m.food_change(self.chat,{'id':item_id,'name':'овсянка сухая','grams':75})
        self.assertEqual(updated['meals'][0]['items'][0]['name'],'овсянка сухая')
        self.assertEqual(updated['meals'][0]['items'][0]['grams'],75)
        self.assertEqual(self.m.food_history(self.chat+1,{'date':'2026-10-18'})['meals'],[])
        with self.assertRaises(ValueError):
            self.m.food_change(self.chat+1,{'id':item_id,'name':'чужой','grams':12})
        after=self.m.food_change(self.chat,{'id':item_id},delete=True)
        self.assertEqual(len(after['meals'][0]['items']),1)
        self.assertEqual(len(self.m.food_history(self.chat,{'date':'2026-10-17'})['meals']),1)
        with self.assertRaises(ValueError):self.m.food_add(self.chat,{'date':'2026-10-18',
            'meal_type':'breakfast','items':[{'name':'рис','grams':6000}]})

    def test_training_preview_is_read_only_and_keeps_preexisting_history(self):
        p,cycle,calendar=self.save((0,2,4))
        slot=calendar[0]
        before=self.snapshot_history()
        preview=self.m.mini_training_preview(self.chat,{'id':slot['id']})['preview']
        self.assertEqual(preview['id'],slot['id'])
        self.assertEqual(preview['week'],slot['week'])
        self.assertTrue(preview['exercises'])
        self.assertIsNone(preview['exercises'][0]['weight_kg'])
        self.assertTrue(preview['can_start'])
        self.assertEqual(self.snapshot_history(),before)
        with self.assertRaises(ValueError):
            self.m.mini_training_preview(self.chat+1,{'id':slot['id']})

    def rows(self, cycle):
        with self.connect() as conn:
            return conn.execute('''SELECT id,week_no,day_code,planned_date,schedule_state
                FROM scheduled_sessions WHERE chat_id=%s AND cycle_id=%s
                ORDER BY week_no,day_code''', (self.chat, cycle)).fetchall()

    def snapshot_history(self):
        with self.connect() as conn:
            return {table: conn.execute(sql.SQL('SELECT * FROM {} ORDER BY 1,2')
                    .format(sql.Identifier(table))).fetchall()
                    for table in ('workouts', 'workout_items', 'workout_sets',
                                  'cardio_sessions', 'pending_inputs', 'rest_timers')}

    def test_active_workout_overview_uses_saved_set_rows(self):
        rows = [(0, 1, 8, 12, 'reps', 'done', 'Жим ногами', 'leg_press'),
                (0, 2, 8, 12, 'reps', 'pending', 'Жим ногами', 'leg_press'),
                (1, 1, 10, 10, 'reps', 'skipped', 'Тяга блока', 'lat_pull'),
                (1, 2, 10, 10, 'reps', 'pending', 'Тяга блока', 'lat_pull')]
        result = self.m.mini_workout_exercises(rows)
        self.assertEqual([(x['done'],x['skipped'],x['total']) for x in result],
                         [(1,0,2),(0,1,2)])
        self.assertEqual(result[0]['name'],'Жим ногами')

    def test_onboarding_api_reopen_and_four_weeks_for_all_counts(self):
        client = self.m.APP.test_client()
        for count in range(1, 8):
            self.chat = 700 + count
            weekdays = list(range(count))
            # Exercise the real API and PostgreSQL writes; only Telegram identity is mocked.
            with patch.object(self.m, 'mini_auth', return_value=self.chat):
                response = client.post('/mini/api', json={'action': 'onboarding',
                                                          **self.body(weekdays)})
            self.assertEqual(response.status_code, 200, response.get_json())
            self.assertTrue(response.get_json()['ok'], response.get_json())
            restored = self.m.profile(self.chat)
            self.assertEqual(restored['weekdays'], weekdays)
            cycle, _ = self.m.get_cycle(self.chat, restored)
            calendar = self.m.scheduled_calendar(self.chat, restored, cycle)
            self.assertEqual(len(calendar), 4 * count)
            for week in range(1, 5):
                entries = [x for x in calendar if x['week'] == week]
                self.assertEqual(len(entries), count)
                self.assertEqual({date.fromisoformat(x['date']).weekday() for x in entries},
                                 set(weekdays))
            self.assertTrue(all(date(2026, 10, 19) <= date.fromisoformat(x['date'])
                                < date(2026, 11, 16) for x in calendar))

    def test_v7_personalization_consents_are_optional_owner_scoped_and_revocable(self):
        body=self.body()
        self.m.save_onboarding(self.chat,body)
        self.assertEqual(self.m.personalization_consent(self.chat),
                         {'profile':False,'health':False,'cycle':False})
        existing=self.snapshot_history()
        body['ai_profile_consent']=True
        body['ai_health_consent']=False
        self.m.save_onboarding(self.chat,body)
        self.assertEqual(self.m.personalization_consent(self.chat)['profile'],True)
        self.assertFalse(self.m.personalization_consent(self.chat)['health'])
        # Each other user starts with independent default-off consent.
        self.assertFalse(self.m.personalization_consent(778)['profile'])
        result=self.m.set_personalization_consent(self.chat,
                                {'field':'health','enabled':True})
        self.assertTrue(result['health'])
        self.assertFalse(result['cycle'])
        with self.assertRaises(ValueError):
            self.m.set_personalization_consent(self.chat,{'field':'cycle','enabled':True})
        with self.assertRaises(ValueError):
            self.m.set_personalization_consent(self.chat,{'field':'profile','enabled':'true'})
        self.m.set_personalization_consent(self.chat,{'field':'profile','enabled':False})
        self.assertFalse(self.m.personalization_consent(self.chat)['profile'])
        self.assertEqual(self.snapshot_history(),existing)

    def test_v7_female_cycle_consent_never_erases_dates_and_is_private(self):
        body=self.body()
        body['metrics']['sex']='female'
        self.m.save_onboarding(self.chat,body)
        self.m.period_save(self.chat,{'start':'2026-10-01','end':'2026-10-04'})
        with self.connect() as conn:
            before=conn.execute('SELECT starts_on,ends_on FROM menstrual_periods WHERE chat_id=%s',
                                (self.chat,)).fetchall()
        enabled=self.m.set_personalization_consent(self.chat,{'field':'cycle','enabled':True})
        self.assertTrue(enabled['cycle'])
        self.assertFalse(self.m.personalization_consent(778)['cycle'])
        self.m.set_personalization_consent(self.chat,{'field':'cycle','enabled':False})
        with self.connect() as conn:
            after=conn.execute('SELECT starts_on,ends_on FROM menstrual_periods WHERE chat_id=%s',
                               (self.chat,)).fetchall()
        self.assertEqual(before,after)
        self.assertFalse(self.m.personalization_consent(self.chat)['cycle'])

    def test_v7_yandex_guidance_exports_no_identifiers_and_requires_cycle_consent(self):
        import io,json
        body=self.body()
        body['metrics']['sex']='female'
        body['ai_profile_consent']=True
        self.m.save_onboarding(self.chat,body)
        self.m.period_save(self.chat,{'start':'2026-10-10','end':'2026-10-13'})
        outbound=[]
        class Reply:
            def __enter__(self):return self
            def __exit__(self,*unused):return False
            def read(self,*unused):return b''
        def fake_urlopen(req,timeout=None):
            data=json.loads(req.data)
            outbound.append(data['messages'][-1]['text'])
            class Response(Reply):
                def __iter__(self):return iter([])
            return io.BytesIO(json.dumps({
                'result':{'alternatives':[{'message':{'text':'План по самочувствию.'}}]}
                }).encode())
        with patch.object(self.m,'YANDEX_KEY','unit-test-secret'),\
             patch.object(self.m,'FOLDER_ID','unit-test-folder'),\
             patch.object(self.m.urllib.request,'urlopen',side_effect=fake_urlopen):
            answer=self.m.ai_personalized_guidance(self.chat,
                {'purpose':'training','mood':'normal'})
            self.assertTrue(answer['used_ai'])
            self.assertFalse(answer['used_cycle'])
            self.assertNotIn('observed_cycle',outbound[-1])
            self.m.set_personalization_consent(self.chat,{'field':'cycle','enabled':True})
            answer=self.m.ai_personalized_guidance(self.chat,
                {'purpose':'training','mood':'discomfort'})
            self.assertTrue(answer['used_cycle'])
            self.assertIn('observed_cycle',outbound[-1])
            self.assertNotIn('chat_id',outbound[-1])
            self.assertNotIn('Telegram',outbound[-1])
            self.assertNotIn('2026-10-10',outbound[-1])
            self.m.set_personalization_consent(self.chat,{'field':'cycle','enabled':False})
            self.m.ai_personalized_guidance(self.chat,
                {'purpose':'training','mood':'normal'})
            self.assertNotIn('observed_cycle',outbound[-1])
            self.m.set_personalization_consent(self.chat,{'field':'profile','enabled':False})
            before=len(outbound)
            with self.assertRaises(ValueError):
                self.m.ai_personalized_guidance(self.chat,
                    {'purpose':'training','mood':'normal'})
            self.assertEqual(before,len(outbound))
            severe=self.m.ai_personalized_guidance(self.chat,
                {'purpose':'training','mood':'severe'})
            self.assertFalse(severe['used_ai'])
            self.assertEqual(before,len(outbound))

    def test_change_preserves_history_active_workout_manual_move_and_cycle(self):
        profile, cycle, _ = self.save()
        by_key = {(r[1], r[2]): r for r in self.rows(cycle)}
        manual = by_key[(3, 'C')]
        self.m.mini_aux(self.chat, 'reschedule', {'id': manual[0], 'date': '2026-11-05'})
        with self.connect() as conn:
            for week, day, status in ((1, 'A', 'finished'), (2, 'B', 'active')):
                wid = conn.execute('''INSERT INTO workouts(chat_id,cycle_id,week_no,plan_day,
                    status,started_at,finished_at,source) VALUES(%s,%s,%s,%s,%s,%s,%s,'template')
                    RETURNING id''', (self.chat, cycle, week, day, status,
                    Clock.instant, Clock.instant if status == 'finished' else None)).fetchone()[0]
                conn.execute('''INSERT INTO workout_items(workout_id,position,exercise,target,
                    exercise_key) VALUES(%s,0,'Жим ногами','3 × 10','leg_press')''', (wid,))
                conn.execute('''INSERT INTO workout_sets(workout_id,position,set_no,target_min,
                    target_max,unit,actual_value,state,weight_kg,completed_at)
                    VALUES(%s,0,1,10,12,'reps',12,'done',60,%s)''', (wid, Clock.instant))
            conn.execute('''INSERT INTO cardio_sessions(chat_id,minutes,avg_hr,equipment)
                VALUES(%s,45,120,'cycling')''', (self.chat,))
        history = self.snapshot_history()
        Clock.instant = datetime(2026, 10, 20, 12, tzinfo=timezone.utc)
        updated, new_cycle, _ = self.save((1, 3))
        self.assertEqual(new_cycle, cycle, 'Schedule edits must retain current cycle identity')
        self.assertEqual(self.snapshot_history(), history, 'History and working weights are immutable')
        after = {(r[1], r[2]): r for r in self.rows(cycle)}
        for key in ((1, 'A'), (2, 'B')):
            self.assertEqual(after[key][3], by_key[key][3], 'Past/linked slot date changed')
        self.assertEqual(after[(3, 'C')][3], date(2026, 11, 5))
        self.assertEqual(after[(3, 'C')][4], 'manual')
        self.assertTrue(any(r[4] == 'retired' for r in after.values()))
        for row in after.values():
            if row[4] == 'auto' and row[3] > date(2026, 10, 20) and (row[1], row[2]) != (2, 'B'):
                self.assertIn(row[3].weekday(), (1, 3))
        self.assertEqual(updated['weekdays'], [1, 3])
        # Saving the same questionnaire again is idempotent.
        previous = self.rows(cycle)
        self.save((1, 3))
        self.assertEqual(self.rows(cycle), previous)
        self.assertEqual(self.snapshot_history(), history)
        # A manually retained C slot must still produce a valid workout at frequency 2.
        self.assertTrue(self.m.make_session(updated, 3, 'C'))

    def test_retired_slots_do_not_reappear_as_time_passes(self):
        _, cycle, _ = self.save(tuple(range(7)))
        Clock.instant = datetime(2026, 10, 20, 12, tzinfo=timezone.utc)
        profile, new_cycle, _ = self.save((0,))
        self.assertEqual(cycle, new_cycle)
        retired = {r[0] for r in self.rows(cycle) if r[4] == 'retired'}
        self.assertTrue(retired)
        Clock.instant = datetime(2026, 10, 29, 12, tzinfo=timezone.utc)
        calendar = self.m.scheduled_calendar(self.chat, profile, cycle)
        self.assertFalse(retired & {x['id'] for x in calendar})
        self.assertTrue(retired <= {r[0] for r in self.rows(cycle) if r[4] == 'retired'})

    def test_legacy_migration_is_additive_and_keeps_manual_dates(self):
        # Simulate a database created by the previous release, only in this test schema.
        with self.connect() as conn:
            conn.execute('ALTER TABLE profiles DROP COLUMN weekdays')
            conn.execute('ALTER TABLE scheduled_sessions DROP COLUMN schedule_state')
            conn.execute('''INSERT INTO profiles(chat_id,goal,level,days,equipment,
                age_group,minutes,clearance) VALUES(%s,'general','beginner','3','gym',
                'adult','45','none')''', (self.chat,))
            conn.execute('''INSERT INTO profile_metrics(chat_id,timezone)
                VALUES(%s,'Europe/Helsinki')''', (self.chat,))
            cycle = conn.execute('''INSERT INTO training_cycles(chat_id,starts_on,
                profile_fingerprint) VALUES(%s,%s,%s) RETURNING id''', (self.chat,
                date(2026, 10, 19), self.m.fingerprint(dict(goal='general', level='beginner',
                days='3', equipment='gym', age_group='adult', minutes='45',
                clearance='none')))).fetchone()[0]
            for week in range(1, 5):
                for day, offset in zip('ABC', (0, 2, 4)):
                    planned = date(2026, 10, 19) + timedelta(days=7 * (week - 1) + offset)
                    if (week, day) == (3, 'C'):
                        planned = date(2026, 11, 5)
                    conn.execute('''INSERT INTO scheduled_sessions(chat_id,cycle_id,week_no,
                        day_code,planned_date) VALUES(%s,%s,%s,%s,%s)''',
                        (self.chat, cycle, week, day, planned))
        self.m.init_db()
        self.m.init_db()  # Migration is idempotent.
        legacy = self.m.profile(self.chat)
        self.assertIsNone(legacy.get('weekdays'))
        before = self.rows(cycle)
        self.m.scheduled_calendar(self.chat, legacy, cycle)
        self.assertEqual(self.rows(cycle), before, 'Opening old profiles must not rewrite dates')
        Clock.instant = datetime(2026, 10, 20, 12, tzinfo=timezone.utc)
        _, new_cycle, _ = self.save((1, 3, 5))
        self.assertEqual(new_cycle, cycle)
        manual = next(r for r in self.rows(cycle) if (r[1], r[2]) == (3, 'C'))
        self.assertEqual(manual[3], date(2026, 11, 5))
        self.assertIn(manual[4], (None, 'manual'))

    def test_checked_in_migration_preserves_legacy_data_and_is_idempotent(self):
        # The exact production preparation file is executed against this
        # isolated schema, never against the Render database.
        from pathlib import Path
        migration = (Path(__file__).resolve().parents[1] /
                     'migrations/20261023_weekday_schedule.sql').read_text()
        sql_without_comments = '\n'.join(
            line for line in migration.splitlines()
            if not line.lstrip().startswith('--'))
        statements = [piece.strip() for piece in sql_without_comments.split(';')
                      if piece.strip()]
        self.assertEqual(statements[0].splitlines()[-1], 'BEGIN')
        self.assertEqual(statements[-1], 'COMMIT')
        with self.connect() as conn:
            conn.execute('ALTER TABLE profiles DROP COLUMN weekdays')
            conn.execute('ALTER TABLE scheduled_sessions DROP COLUMN schedule_state')
            conn.execute("""INSERT INTO profiles(chat_id,goal,level,days,equipment,
                age_group,minutes,clearance) VALUES(%s,'general','beginner','2',
                'gym','adult','45','none')""", (self.chat,))
            conn.execute("""INSERT INTO scheduled_sessions(chat_id,cycle_id,week_no,
                day_code,planned_date) VALUES(%s,1,2,'B',%s)""",
                         (self.chat, date(2026, 11, 5)))
            conn.execute("""INSERT INTO cardio_sessions(chat_id,minutes,equipment)
                VALUES(%s,45,'cycling')""", (self.chat,))
        with self.connect() as conn:
            profile_before = conn.execute(
                'SELECT chat_id,goal,days,equipment FROM profiles').fetchall()
            schedule_before = conn.execute(
                'SELECT chat_id,cycle_id,week_no,day_code,planned_date '
                'FROM scheduled_sessions').fetchall()
            cardio_before = conn.execute(
                'SELECT chat_id,minutes,equipment FROM cardio_sessions').fetchall()
        # Run BEGIN/COMMIT from the file with autocommit, so the script
        # transaction mirrors the real migration instead of nesting BEGIN.
        for _ in range(2):
            with self.connect() as conn:
                conn.autocommit = True
                for statement in statements:
                    conn.execute(statement)
            with self.connect() as conn:
                self.assertEqual(conn.execute(
                    'SELECT chat_id,goal,days,equipment FROM profiles').fetchall(),
                    profile_before)
                self.assertEqual(conn.execute(
                    'SELECT chat_id,cycle_id,week_no,day_code,planned_date '
                    'FROM scheduled_sessions').fetchall(), schedule_before)
                self.assertEqual(conn.execute(
                    'SELECT chat_id,minutes,equipment FROM cardio_sessions').fetchall(),
                    cardio_before)
                self.assertEqual(conn.execute(
                    'SELECT weekdays FROM profiles').fetchone()[0], None)
                self.assertEqual(conn.execute(
                    'SELECT schedule_state FROM scheduled_sessions').fetchone()[0], None)
        with self.connect() as conn:
            with self.assertRaises(psycopg.errors.CheckViolation):
                conn.execute("""UPDATE scheduled_sessions SET schedule_state='deleted'
                    WHERE chat_id=%s""", (self.chat,))

    def test_progress_weights_are_real_bounded_owner_scoped_and_read_only(self):
        # All inserts are in this UUID test schema, never in production.
        with self.connect() as conn:
            conn.execute("""INSERT INTO profile_metrics(chat_id,timezone)
                VALUES(%s,'Europe/Helsinki')""", (self.chat,))
            for chat, stamp, kg, status, set_state in (
                    (self.chat, '2026-10-19T10:00:00Z', 55, 'finished', 'done'),
                    (self.chat, '2026-10-19T12:00:00Z', 60, 'finished', 'done'),
                    (self.chat, '2026-10-21T10:00:00Z', 65, 'finished', 'done'),
                    (self.chat, '2026-10-22T10:00:00Z', 80, 'active', 'done'),
                    (self.chat, '2026-10-23T10:00:00Z', 95, 'finished', 'pending'),
                    (self.chat + 1, '2026-10-24T10:00:00Z', 500, 'finished', 'done')):
                wid = conn.execute("""INSERT INTO workouts(chat_id,plan_day,status,
                    started_at,finished_at) VALUES(%s,'A',%s,%s,%s) RETURNING id""",
                    (chat,status,stamp,stamp if status == 'finished' else None)).fetchone()[0]
                conn.execute("""INSERT INTO workout_items(workout_id,position,exercise,
                    target,exercise_key) VALUES(%s,0,'Жим ногами','3 x 10','leg_press')""",
                    (wid,))
                conn.execute("""INSERT INTO workout_sets(workout_id,position,set_no,
                    target_min,target_max,unit,actual_value,state,weight_kg)
                    VALUES(%s,0,1,10,12,'reps',12,%s,%s)""",
                    (wid,set_state,kg))
        before = self.snapshot_history()
        client = self.m.APP.test_client()
        with patch.object(self.m, 'mini_auth', return_value=self.chat):
            result = client.post('/mini/api',json={'action':'progress_series'})
        self.assertEqual(result.status_code,200,result.get_json())
        self.assertEqual(result.get_json()['exercises'][0]['points'],[
            {'date':'2026-10-19','weight':60.0},
            {'date':'2026-10-21','weight':65.0},
        ])
        self.assertEqual(self.snapshot_history(),before)
        with patch.object(self.m,'mini_auth',return_value=self.chat+1):
            other=client.post('/mini/api',json={'action':'progress_series'})
        self.assertEqual(other.get_json()['exercises'][0]['points'][0]['weight'],500.0)
        with patch.object(self.m,'mini_auth',return_value=None):
            denied=client.post('/mini/api',json={'action':'progress_series'})
        self.assertEqual(denied.status_code,401)

    def test_invalid_weekdays_do_not_write_profile_or_calendar(self):
        _, cycle, _ = self.save()
        before = self.rows(cycle)
        old_profile = self.m.profile(self.chat)
        for weekdays in ([0, 0, 2], [True, 2, 4], [-1, 2, 4],
                         [0, 2, 7], ['0', 2, 4]):
            payload = self.body((0, 2, 4))
            payload['answers']['weekdays'] = weekdays
            with self.subTest(weekdays=weekdays), self.assertRaises(ValueError):
                self.m.save_onboarding(self.chat, payload)
            self.assertEqual(self.rows(cycle), before)
            self.assertEqual(self.m.profile(self.chat), old_profile)

    def test_local_weekdays_across_dst_and_utc_date_boundary(self):
        for index, (instant, zone, start) in enumerate((
                (datetime(2026, 10, 24, 21, 30, tzinfo=timezone.utc),
                 'Europe/Helsinki', date(2026, 10, 25)),
                (datetime(2026, 3, 28, 22, 30, tzinfo=timezone.utc),
                 'Europe/Helsinki', date(2026, 3, 29)),
                (datetime(2026, 10, 24, 12, 30, tzinfo=timezone.utc),
                 'Pacific/Kiritimati', date(2026, 10, 25)))):
            with self.subTest(zone=zone, instant=instant):
                self.chat = 900 + index
                Clock.instant = instant
                profile, cycle, calendar = self.save((6,), zone=zone)
                expected = [(start + timedelta(days=7 * week)).isoformat()
                            for week in range(4)]
                self.assertEqual([row['date'] for row in calendar], expected)
                Clock.instant = instant + timedelta(days=8)
                self.assertEqual([row['date'] for row in self.m.scheduled_calendar(
                    self.chat, profile, cycle)], expected)

    def test_schedule_failure_rolls_back_profile_health_metrics_and_dates(self):
        _, cycle, _ = self.save()
        def snapshot():
            with self.connect() as conn:
                return {table: conn.execute(sql.SQL('SELECT * FROM {} ORDER BY 1')
                        .format(sql.Identifier(table))).fetchall()
                        for table in ('profiles', 'profile_metrics', 'health_limits',
                                      'profile_equipment', 'training_cycles',
                                      'scheduled_sessions', 'user_agreements')}
        before = snapshot()
        payload = self.body((1, 3, 5))
        payload['metrics']['weight_kg'] = 85
        with patch.object(self.m, 'reconcile_schedule_in', side_effect=RuntimeError('test rollback')):
            with self.assertRaisesRegex(RuntimeError, 'test rollback'):
                self.m.save_onboarding(self.chat, payload)
        self.assertEqual(snapshot(), before)
        self.assertEqual(self.m.get_cycle(self.chat, self.m.profile(self.chat))[0], cycle)

    def test_concurrent_save_and_manual_reschedule_preserves_one_safe_state(self):
        stale_profile, cycle, _ = self.save()
        Clock.instant = datetime(2026, 10, 20, 12, tzinfo=timezone.utc)
        sid = next(r[0] for r in self.rows(cycle) if (r[1], r[2]) == (3, 'C'))
        barrier = Barrier(2)
        def save_schedule():
            barrier.wait(timeout=10)
            self.m.save_onboarding(self.chat, self.body((1, 3)))
        def move_manually():
            barrier.wait(timeout=10)
            try:
                self.m.mini_aux(self.chat, 'reschedule',
                                {'id': sid, 'date': '2026-11-05'})
            except ValueError as exc:
                if str(exc) != 'Дата не найдена':
                    raise
                return 'retired_before_move'
            return 'manual_before_retirement'
        with ThreadPoolExecutor(max_workers=2) as pool:
            scheduled = pool.submit(save_schedule)
            moved_task = pool.submit(move_manually)
            scheduled.result(timeout=30)
            result = moved_task.result(timeout=30)
        moved = next(r for r in self.rows(cycle) if r[0] == sid)
        if result == 'manual_before_retirement':
            # A manual move wins the lock and cannot be retired afterwards.
            self.assertEqual(moved[3:], (date(2026, 11, 5), 'manual'))
        else:
            # A new preference wins first; stale client must never revive retired.
            self.assertEqual(result, 'retired_before_move')
            self.assertEqual(moved[4], 'retired')
        # A previously loaded dashboard must never regenerate old preferences.
        self.assertEqual(self.m.get_cycle(self.chat, stale_profile)[0], cycle)
        before = self.rows(cycle)
        self.m.scheduled_calendar(self.chat, stale_profile, cycle)
        self.assertEqual(self.rows(cycle), before)

    def test_isolated_pg_dump_restore_preserves_history_and_retired_slots(self):
        # Real backup/restore rehearsal in the disposable *_test database only.
        # setUpClass validates the loopback host and database name; each test
        # owns a unique temporary schema, never the production schema.
        import shutil
        import subprocess
        import tempfile
        from pathlib import Path

        docker_container = os.getenv('FORMIQ_TEST_PG_DOCKER_CONTAINER')
        if docker_container:
            # Never accept user-supplied host names or container references:
            # GitHub Actions supplies the exact ephemeral postgres service ID.
            self.assertRegex(docker_container, r'^[0-9a-f]{64}$')
            self.assertIsNotNone(shutil.which('docker'))
        else:
            for program in ('pg_dump', 'pg_restore'):
                self.assertIsNotNone(shutil.which(program),
                                     program + ' is required for an actual restore test')
        _, cycle, _ = self.save(tuple(range(7)))
        Clock.instant = datetime(2026, 10, 20, 12, tzinfo=timezone.utc)
        _, unchanged_cycle, _ = self.save((0,))
        self.assertEqual(cycle, unchanged_cycle)
        with self.connect() as conn:
            wid = conn.execute("""INSERT INTO workouts(chat_id,cycle_id,week_no,
                plan_day,status,started_at,finished_at,source)
                VALUES(%s,%s,1,'A','finished',%s,%s,'template') RETURNING id""",
                (self.chat, cycle, Clock.instant, Clock.instant)).fetchone()[0]
            conn.execute("""INSERT INTO workout_items(workout_id,position,exercise,target,
                exercise_key) VALUES(%s,0,'Жим ногами','3 × 10','leg_press')""", (wid,))
            conn.execute("""INSERT INTO workout_sets(workout_id,position,set_no,
                target_min,target_max,unit,actual_value,state,weight_kg,completed_at)
                VALUES(%s,0,1,10,12,'reps',12,'done',60,%s)""",
                (wid, Clock.instant))
            conn.execute("""INSERT INTO cardio_sessions(chat_id,minutes,avg_hr,equipment)
                VALUES(%s,45,120,'cycling')""", (self.chat,))
        before_history = self.snapshot_history()
        before_profile = self.m.profile(self.chat)
        before_calendar = self.rows(cycle)
        self.assertTrue(any(row[4] == 'retired' for row in before_calendar))
        self.assertTrue(self.schema.startswith('formiq_schedule_regression_'))
        with tempfile.TemporaryDirectory(prefix='formiq-restore-') as directory:
            archive = str(Path(directory) / 'sample.backup')
            if docker_container:
                # Executing in the disposable PG18 service avoids depending on
                # the host runner's possibly older pg_dump binary.
                archive = '/tmp/formiq-test-' + uuid.uuid4().hex + '.backup'
                dump = ['docker', 'exec', docker_container, 'pg_dump',
                        '--username', 'formiq_test', '--dbname', 'formiq_schedule_test',
                        '--format=custom', '--schema', self.schema, '--file', archive]
                restore = ['docker', 'exec', docker_container, 'pg_restore',
                           '--username', 'formiq_test', '--dbname', 'formiq_schedule_test',
                           '--no-owner', '--no-acl', '--exit-on-error', archive]
            else:
                dump = ['pg_dump', '--dbname', TEST_URL, '--format=custom',
                        '--schema', self.schema, '--file', archive]
                restore = ['pg_restore', '--dbname', TEST_URL, '--no-owner',
                           '--no-acl', '--exit-on-error', archive]
            try:
                subprocess.run(dump, check=True, capture_output=True, timeout=60)
                if docker_container:
                    subprocess.run(['docker', 'exec', docker_container, 'test',
                                    '-s', archive],
                                   check=True, capture_output=True, timeout=20)
                else:
                    self.assertGreater(Path(archive).stat().st_size, 0)
                # Destructive part is confined to this disposable test schema.
                with psycopg.connect(TEST_URL) as conn:
                    conn.execute(sql.SQL('DROP SCHEMA {} CASCADE')
                                 .format(sql.Identifier(self.schema)))
                subprocess.run(restore, check=True, capture_output=True, timeout=60)
            finally:
                if docker_container:
                    subprocess.run(['docker', 'exec', docker_container, 'rm',
                                    '-f', archive], capture_output=True, timeout=20)
        self.assertEqual(self.snapshot_history(), before_history)
        self.assertEqual(self.rows(cycle), before_calendar)
        self.assertEqual(self.m.profile(self.chat), before_profile)

    def test_timezone_change_keeps_cycle_manual_move_and_protected_boundary(self):
        Clock.instant = datetime(2026, 10, 19, 23, 30, tzinfo=timezone.utc)
        _, cycle, _ = self.save((1, 3), zone='Asia/Tokyo')  # Locally October 20.
        sid = next(r[0] for r in self.rows(cycle) if (r[1], r[2]) == (3, 'B'))
        self.m.mini_aux(self.chat, 'reschedule', {'id': sid, 'date': '2026-11-04'})
        profile, changed_cycle, calendar = self.save((0, 2), zone='America/Los_Angeles')
        self.assertEqual(changed_cycle, cycle, 'Changing timezone must not replace the cycle')
        self.assertEqual(next(r for r in self.rows(cycle) if r[0] == sid)[3], date(2026, 11, 4))
        self.assertIn(sid, {r['id'] for r in calendar})
        # A count increase must not insert a slot on the old timezone's protected today,
        # even if a later read regards it as tomorrow in the newly selected timezone.
        self.chat = 778
        Clock.instant = datetime(2026, 10, 18, 12, tzinfo=timezone.utc)
        _, other_cycle, _ = self.save((6,), zone='Asia/Tokyo')
        Clock.instant = datetime(2026, 10, 19, 23, 30, tzinfo=timezone.utc)
        profile, same_cycle, calendar = self.save((0, 1), zone='America/Los_Angeles')
        self.assertEqual(same_cycle, other_cycle)
        before = self.rows(other_cycle)
        for _ in range(2):
            calendar = self.m.scheduled_calendar(self.chat, profile, other_cycle)
        self.assertEqual(self.rows(other_cycle), before)
        self.assertFalse(any(r['date'] == '2026-10-20' and r['day'] == 'B' for r in calendar))


    def test_readonly_rollback_gate_on_real_pg18_isolated_schema(self):
        """Check real SQL + SELECT-only assessment without changing any records."""
        from scripts.rollback_readonly_gate import inspect_legacy_rollback

        with self.connect() as conn:
            clean = inspect_legacy_rollback(conn)
        self.assertEqual(clean['status'], 'candidate')

        self.save((0, 2, 4))
        before_rows = self.rows(self.m.get_cycle(self.chat, self.m.profile(self.chat))[0])
        before_profile = self.m.profile(self.chat)
        before_history = self.snapshot_history()
        with self.connect() as conn:
            report = inspect_legacy_rollback(conn)
            with self.assertRaises(psycopg.errors.ReadOnlySqlTransaction):
                conn.execute('UPDATE profiles SET days=days')
            conn.rollback()
        self.assertEqual(report['status'], 'blocked')
        self.assertTrue(report['weekday_choices_present'])
        self.assertTrue(report['schedule_states_present'])
        self.assertEqual(before_rows, self.rows(self.m.get_cycle(
            self.chat, self.m.profile(self.chat))[0]))
        self.assertEqual(before_profile, self.m.profile(self.chat))
        self.assertEqual(before_history, self.snapshot_history())

        # A broken one-column migration must never be called safe.
        with self.connect() as conn:
            conn.execute('ALTER TABLE scheduled_sessions DROP COLUMN schedule_state')
        with self.connect() as conn:
            damaged = inspect_legacy_rollback(conn)
        self.assertEqual(damaged['reason'], 'partial_v5_schema')


    def test_emergency_v5_fallback_freezes_schedule_but_keeps_history(self):
        """A V5-compatible fallback must never recreate retired slots or cycles."""
        profile, cycle, _ = self.save((0, 2, 4))
        by_key = {(r[1], r[2]): r for r in self.rows(cycle)}
        manual = by_key[(3, 'C')]
        self.m.mini_aux(self.chat, 'reschedule', {
            'id': manual[0], 'date': '2026-11-06'})
        profile, current_cycle, _ = self.save((1, 3))
        self.assertEqual(current_cycle, cycle)
        original_slots = self.rows(cycle)
        self.assertTrue(any(row[4] == 'retired' for row in original_slots))
        self.assertTrue(any(row[4] == 'manual' for row in original_slots))
        retired_id = next(row[0] for row in original_slots if row[4] == 'retired')
        # A stale client must never be able to resurrect this retired identity.
        with self.assertRaisesRegex(ValueError, 'Дата не найдена'):
            self.m.mini_aux(self.chat, 'reschedule', {
                'id': retired_id, 'date': '2026-11-07'})
        self.assertEqual(self.rows(cycle), original_slots)
        original_history = self.snapshot_history()
        with self.connect() as conn:
            before_cycles = conn.execute(
                'SELECT id,starts_on,profile_fingerprint FROM training_cycles '
                'WHERE chat_id=%s ORDER BY id', (self.chat,)).fetchall()
        with patch.dict(os.environ, {'FORMIQ_SCHEDULE_SAFE_MODE': '1'}):
            self.assertTrue(self.m.schedule_emergency_readonly())
            # A user's existing plan is browsable, including manual slots.
            self.assertEqual(self.m.get_cycle(self.chat, profile)[0], cycle)
            shown = self.m.scheduled_calendar(self.chat, profile, cycle)
            self.assertTrue(any(x['id'] == manual[0] for x in shown))
            retired_ids = {row[0] for row in original_slots if row[4] == 'retired'}
            self.assertFalse(any(x['id'] in retired_ids for x in shown))
            self.m.next_day_in_readonly(self.chat, cycle, 2)
            self.assertEqual(self.rows(cycle), original_slots)
            # Profile edit and manual reschedule are blocked without side effects.
            with self.assertRaisesRegex(ValueError, 'временно защищено'):
                self.m.save_onboarding(self.chat, self.body((0, 2, 4)))
            with self.assertRaisesRegex(ValueError, 'временно защищено'):
                self.m.mini_aux(self.chat, 'reschedule', {
                    'id': manual[0], 'date': '2026-11-05'})
            self.assertEqual(self.m.profile(self.chat), profile)
            self.assertEqual(self.rows(cycle), original_slots)
            # Even after 28 days: do not mint a fresh cycle while frozen.
            Clock.instant = datetime(2026, 12, 2, 12, tzinfo=timezone.utc)
            with self.assertRaisesRegex(ValueError, 'временно защищено'):
                self.m.get_cycle(self.chat, profile)
        with self.connect() as conn:
            after_cycles = conn.execute(
                'SELECT id,starts_on,profile_fingerprint FROM training_cycles '
                'WHERE chat_id=%s ORDER BY id', (self.chat,)).fetchall()
        self.assertEqual(before_cycles, after_cycles)
        self.assertEqual(self.rows(cycle), original_slots)
        self.assertEqual(self.snapshot_history(), original_history)


    def test_extended_120_minute_gym_session_is_not_clamped_to_90(self):
        profile=dict(goal='general',level='experienced',days='3',
                     equipment='gym',minutes='90')
        standard=self.m.make_session(profile,1,'A',cycle_id=1)
        extended=self.m.make_session({**profile,'minutes':'120'},1,'A',cycle_id=1)
        self.assertLessEqual(len(standard),6)
        self.assertGreaterEqual(len(extended),len(standard))
        self.assertEqual(len(extended),7)

    def test_new_onboarding_uses_weekday_count_and_postgres_roundtrip(self):
        """Actual authenticated API (identity mocked) -> database -> state/reopen."""
        data=self.body((0, 2, 4), days=2)
        data['answers']['minutes']='120'
        data['answers']['equipment']='home'
        data['metrics']['sex']='female'
        data['equipment_description']='гантели, коврик, резинки'
        data['health_description']=''
        data['health_storage_consent']=False
        with patch.object(self.m,'mini_auth',return_value=self.chat):
            response=self.m.APP.test_client().post('/mini/api',
                          json={'action':'onboarding',**data})
        self.assertEqual(response.status_code,200,response.get_json())
        state=response.get_json()['data']
        self.assertEqual(state['metrics']['sex'],'female')
        self.assertEqual(state['profile_raw']['days'],'3')
        self.assertEqual(state['profile_raw']['weekdays'],[0,2,4])
        self.assertEqual(state['profile_raw']['minutes'],'120')
        self.assertEqual(state['profile_raw']['equipment'],'homegear')
        self.assertEqual(state['equipment_description'],'гантели, коврик, резинки')
        self.assertTrue(state['agreed'])
        self.assertIsNone(state['error'])
        self.assertEqual(len(state['calendar']),12)
        # Reopen without creating a duplicate cycle or losing the profile.
        with patch.object(self.m,'mini_auth',return_value=self.chat):
            reloaded=self.m.APP.test_client().post('/mini/api',json={'action':'state'})
        self.assertEqual(reloaded.status_code,200,reloaded.get_json())
        self.assertEqual(reloaded.json['data']['profile_raw']['weekdays'],[0,2,4])
        self.assertEqual(reloaded.json['data']['metrics']['sex'],'female')
        with self.connect() as conn:
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM training_cycles WHERE chat_id=%s',
                                          (self.chat,)).fetchone()[0],1)

    def test_v6_additive_migration_from_existing_v5_rows_is_idempotent(self):
        """Model a populated V5 schema in disposable PG18, not production."""
        _, cycle, _ = self.save((0,2,4))
        tables=('profiles','profile_metrics','health_limits','profile_equipment',
                'user_agreements','training_cycles','scheduled_sessions')
        def snapshot():
            with self.connect() as conn:
                return {name: conn.execute(sql.SQL('SELECT * FROM {} ORDER BY 1')
                                     .format(sql.Identifier(name))).fetchall()
                        for name in tables}
        before=snapshot()
        self.assertTrue(before['profiles'])
        self.assertTrue(before['training_cycles'])
        self.assertTrue(before['scheduled_sessions'])
        # V5 production predates these two V6-only tables. Drop them only
        # inside this test's uniquely named ephemeral schema.
        self.assertTrue(self.schema.startswith('formiq_schedule_regression_'))
        with self.connect() as conn:
            conn.execute('DROP TABLE profile_health_notes')
            conn.execute('DROP TABLE menstrual_periods')
        self.m.init_db()
        self.m.init_db()
        self.assertEqual(snapshot(),before)
        with self.connect() as conn:
            for table in ('profile_health_notes','menstrual_periods'):
                self.assertIsNotNone(conn.execute(
                    'SELECT to_regclass(%s)',(table,)).fetchone()[0])
        self.assertEqual(self.m.get_cycle(self.chat,self.m.profile(self.chat))[0],cycle)

    def test_v6_profile_edit_preserves_legacy_resting_heart_rate(self):
        """V6 no longer asks for resting HR; an edit must not erase old data."""
        original=self.body((0,2))
        self.m.save_onboarding(self.chat,original)
        with self.connect() as conn:
            before=conn.execute('SELECT resting_hr FROM profile_metrics WHERE chat_id=%s',
                                (self.chat,)).fetchone()[0]
        self.assertEqual(before,60)
        updated=self.body((0,2,4))
        updated['metrics'].pop('resting_hr')
        updated['metrics']['sex']='female'
        updated['answers']['minutes']='120'
        with patch.object(self.m,'mini_auth',return_value=self.chat):
            response=self.m.APP.test_client().post('/mini/api',
                json={'action':'onboarding',**updated})
        self.assertEqual(response.status_code,200,response.get_json())
        self.assertEqual(response.json['data']['metrics']['resting_hr'],60)
        self.assertEqual(response.json['data']['metrics']['sex'],'female')
        self.assertEqual(response.json['data']['profile_raw']['weekdays'],[0,2,4])
        with self.connect() as conn:
            persisted=conn.execute('SELECT resting_hr FROM profile_metrics WHERE chat_id=%s',
                                   (self.chat,)).fetchone()[0]
        self.assertEqual(persisted,60)

    def test_weekday_selection_ignores_invalid_or_missing_legacy_frequency(self):
        """Only selected weekdays are authoritative in V6, even if days is stale."""
        client=self.m.APP.test_client()
        saved=self.body((0,2,4))
        saved['answers']['days']='99'  # old UI value must NOT block V6.
        saved['metrics']['sex']='female'
        with patch.object(self.m,'mini_auth',return_value=self.chat):
            first=client.post('/mini/api',json={'action':'onboarding',**saved})
        self.assertEqual(first.status_code,200,first.get_json())
        self.assertEqual(first.json['data']['profile_raw']['days'],'3')
        self.assertEqual(first.json['data']['profile_raw']['weekdays'],[0,2,4])
        first_cycle=self.m.get_cycle(self.chat,self.m.profile(self.chat))[0]
        # V6 is allowed to omit days entirely; the server derives it.
        saved['answers'].pop('days')
        saved['answers']['weekdays']=[1,3]
        with patch.object(self.m,'mini_auth',return_value=self.chat):
            second=client.post('/mini/api',json={'action':'onboarding',**saved})
        self.assertEqual(second.status_code,200,second.get_json())
        self.assertEqual(second.json['data']['profile_raw']['days'],'2')
        self.assertEqual(second.json['data']['profile_raw']['weekdays'],[1,3])
        self.assertEqual(self.m.get_cycle(self.chat,self.m.profile(self.chat))[0],first_cycle)
        bad=self.body((0,2))
        bad['answers']['weekdays']=[1,1]
        with patch.object(self.m,'mini_auth',return_value=self.chat):
            duplicate=client.post('/mini/api',json={'action':'onboarding',**bad})
        self.assertEqual(duplicate.status_code,400)
        self.assertEqual(self.m.profile(self.chat)['weekdays'],[1,3])

    def test_health_description_needs_explicit_storage_consent(self):
        data=self.body((0,2))
        data['health_description']='Есть травма колена, пока не знаю нагрузку'
        data['health_storage_consent']=False
        with self.assertRaisesRegex(ValueError,'Подтверди сохранение'):
            self.m.save_onboarding(self.chat,data)
        with self.connect() as conn:
            self.assertEqual(conn.execute('SELECT count(*) FROM profiles').fetchone()[0],0)
            self.assertEqual(conn.execute('SELECT count(*) FROM profile_health_notes').fetchone()[0],0)
        data['health_storage_consent']=True
        self.m.save_onboarding(self.chat,data)
        self.assertEqual(self.m.mini_state(self.chat)['health_description'],data['health_description'])
        data['health_description']=''
        self.m.save_onboarding(self.chat,data)
        # Editing an unrelated answer must not erase stored sensitive notes.
        self.assertEqual(self.m.mini_state(self.chat)['health_description'],
                         'Есть травма колена, пока не знаю нагрузку')

    def test_v6_confirmed_account_deletion_erases_private_records_only_for_owner(self):
        """Delete user-owned sensitive V6 rows in disposable PG18, not production."""
        for owner in (self.chat, 999):
            data=self.body((0,2))
            data['metrics']['sex']='female'
            data['answers']['equipment']='home'
            data['equipment_description']='коврик и резинки'
            data['health_description']='Индивидуальное ограничение нагрузки'
            data['health_storage_consent']=True
            self.m.save_onboarding(owner,data)
            self.m.period_save(owner,{'start':'2026-10-01','end':'2026-10-05'})
        with patch.object(self.m,'send') as send:
            self.m.delete_all(self.chat)
            send.assert_called_once()
        with self.connect() as conn:
            for table in ('profile_health_notes','menstrual_periods',
                          'profile_equipment','profile_metrics','profiles'):
                self.assertEqual(conn.execute(sql.SQL('SELECT count(*) FROM {} WHERE chat_id=%s')
                    .format(sql.Identifier(table)),(self.chat,)).fetchone()[0],0,table)
                self.assertEqual(conn.execute(sql.SQL('SELECT count(*) FROM {} WHERE chat_id=%s')
                    .format(sql.Identifier(table)),(999,)).fetchone()[0],1,table)

    def test_private_female_period_dates_prediction_and_edit(self):
        # A historical 3-cycle series can estimate a *future* date but must
        # not continue showing it as "next" after that date has passed.
        Clock.instant=datetime(2026,8,31,12,tzinfo=timezone.utc)
        data=self.body((0,2))
        data['metrics']['sex']='female'
        self.m.save_onboarding(self.chat,data)
        client=self.m.APP.test_client()
        with patch.object(self.m,'mini_auth',return_value=self.chat):
            self.assertEqual(client.post('/mini/api',json={'action':'period_list'}).json['periods'],[])
            saved=[]
            for day in ('2026-07-01','2026-07-29','2026-08-26'):
                start=date.fromisoformat(day)
                end=(start+timedelta(days=4)).isoformat()
                response=client.post('/mini/api',
                          json={'action':'period_save','start':day,'end':end})
                self.assertEqual(response.status_code,200,response.get_json())
                saved.append(response.json['periods'][0])
            self.assertEqual(response.json['next_period']['date'],'2026-09-23')
            Clock.instant=datetime(2026,10,19,12,tzinfo=timezone.utc)
            expired=client.post('/mini/api',json={'action':'period_list'})
            self.assertIsNone(expired.json['next_period'],
                'A past estimate cannot be presented as the next period')
            ident=saved[1]['id']
            revised=client.post('/mini/api',json={'action':'period_save','id':ident,
                           'start':'2026-07-30','end':'2026-08-02'})
            self.assertEqual(revised.status_code,200,revised.get_json())
            self.assertTrue(any(x['start']=='2026-07-30' for x in revised.json['periods']))
            invalid=client.post('/mini/api',json={'action':'period_save',
                    'start':'2026-10-01','end':'2026-09-30'})
            self.assertEqual(invalid.status_code,400)
            # A mistaken overlapping date must not alter real private history.
            before=client.post('/mini/api',json={'action':'period_list'}).json['periods']
            collision=client.post('/mini/api',json={'action':'period_save',
                    'start':'2026-07-02','end':'2026-07-04'})
            self.assertEqual(collision.status_code,400)
            self.assertIn('пересекаются',collision.json['error'])
            bad_edit=client.post('/mini/api',json={'action':'period_save',
                    'id':ident,'start':'2026-07-04','end':'2026-07-07'})
            self.assertEqual(bad_edit.status_code,400)
            future=client.post('/mini/api',json={'action':'period_save',
                    'start':'2099-05-10','end':'2099-05-13'})
            self.assertEqual(future.status_code,400)
            self.assertEqual(client.post('/mini/api',
                             json={'action':'period_list'}).json['periods'],before)
        # Switching to the male Aluminium profile hides private female data,
        # but must NOT delete it or allow further calendar writes.
        data['metrics']['sex']='male'
        self.m.save_onboarding(self.chat,data)
        with patch.object(self.m,'mini_auth',return_value=self.chat):
            self.assertEqual(client.post('/mini/api',json={'action':'period_list'}).status_code,400)
            denied=client.post('/mini/api',json={'action':'period_save',
                'start':'2026-10-04','end':'2026-10-07'})
            self.assertEqual(denied.status_code,400)
        with self.connect() as conn:
            self.assertEqual(conn.execute(
                'SELECT count(*) FROM menstrual_periods WHERE chat_id=%s',
                (self.chat,)).fetchone()[0],3)
        data['metrics']['sex']='female'
        self.m.save_onboarding(self.chat,data)
        with patch.object(self.m,'mini_auth',return_value=self.chat):
            restored=client.post('/mini/api',json={'action':'period_list'})
            self.assertEqual(restored.status_code,200)
            self.assertEqual(restored.json['periods'],before)
        # Different Telegram identity cannot read or update another person's entries.
        self.chat=999
        other=self.body((0,2));other['metrics']['sex']='female'
        self.m.save_onboarding(self.chat,other)
        with patch.object(self.m,'mini_auth',return_value=999):
            listing=client.post('/mini/api',json={'action':'period_list'})
            self.assertEqual(listing.status_code,200)
            self.assertEqual(listing.json['periods'],[])
            stolen=client.post('/mini/api',json={'action':'period_save',
                'id':ident,'start':'2026-07-01','end':'2026-07-05'})
            self.assertEqual(stolen.status_code,400)
        with patch.object(self.m,'mini_auth',return_value=None):
            self.assertEqual(client.post('/mini/api',json={'action':'period_list'}).status_code,401)

    def test_v6_onboarding_frontend_contract(self):
        from pathlib import Path
        root=Path(__file__).resolve().parents[1]
        js=(root/'web'/'v5-live.js').read_text('utf-8')
        html=(root/'web'/'v5-live.html').read_text('utf-8')
        self.assertIn("String(count),weekdays:",js)
        self.assertIn("onboardChoices.minutes",js)
        self.assertIn("function femaleCalendar()",js)
        self.assertIn("period_list",js)
        self.assertIn("body?.classList?.toggle('theme-female'",js)
        self.assertIn("data-onboard-pick",js)
        self.assertNotIn("onboardChoice('days'",js)
        self.assertNotIn('type="range" min="20" max="90"',js)
        self.assertNotIn("['Не указывать','']",js)
        self.assertNotIn("window.location.assign('/mini/legacy'",js)
        self.assertIn("body.theme-female .app",html)


if __name__ == '__main__':
    unittest.main()
