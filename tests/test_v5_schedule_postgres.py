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

    def test_fourteen_day_onboarding_trial_not_reset_by_profile_edit(self):
        self.m.save_onboarding(self.chat,self.body())
        with self.connect() as conn:
            begun=conn.execute('SELECT trial_started_at FROM premium_access WHERE chat_id=%s',
                (self.chat,)).fetchone()[0]
        self.assertIsNotNone(begun)
        self.assertEqual(self.m.premium_state(self.chat)[0],'trial')
        self.assertEqual(self.m.tier_for(self.chat),'max')
        self.m.save_onboarding(self.chat,self.body())
        with self.connect() as conn:
            again=conn.execute('SELECT trial_started_at FROM premium_access WHERE chat_id=%s',
                (self.chat,)).fetchone()[0]
        self.assertEqual(again,begun,'Editing onboarding must not restart the trial')
        Clock.instant=begun+timedelta(days=15)
        self.assertEqual(self.m.premium_state(self.chat)[0],'free')
        self.assertEqual(self.m.tier_for(self.chat),'start')
        self.m.select_demo_tier(self.chat,'max')
        self.assertEqual(self.m.tier_for(self.chat),'max','Explicit demo tier still works')

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
        self.assertEqual(len(another['meals']),1,'One breakfast card per day') 
        self.assertEqual(len(another['meals'][0]['items']),3,'New products append to existing breakfast')
        self.m.food_add(self.chat,{'date':'2026-10-17','meal_type':'dinner',
            'items':[{'name':'рис сухой','grams':90}]})
        updated=self.m.food_change(self.chat,{'id':item_id,'name':'овсянка сухая','grams':75})
        self.assertEqual(updated['meals'][0]['items'][0]['name'],'овсянка сухая')
        self.assertEqual(updated['meals'][0]['items'][0]['grams'],75)
        self.assertEqual(self.m.food_history(self.chat+1,{'date':'2026-10-18'})['meals'],[])
        with self.assertRaises(ValueError):
            self.m.food_change(self.chat+1,{'id':item_id,'name':'чужой','grams':12})
        after=self.m.food_change(self.chat,{'id':item_id},delete=True)
        self.assertEqual(len(after['meals'][0]['items']),2)
        self.assertEqual(len(self.m.food_history(self.chat,{'date':'2026-10-17'})['meals']),1)
        with self.assertRaises(ValueError):self.m.food_add(self.chat,{'date':'2026-10-18',
            'meal_type':'breakfast','items':[{'name':'рис','grams':6000}]})

    def test_free_text_accepts_explicit_leading_and_trailing_grams_without_guessing(self):
        result=self.m.food_parse({'text':
            '80 г рис сухой; творог 150 граммов; 65,5 грамма яблоко; 2 яйца'})
        self.assertEqual(result['items'],[
            {'name':'рис сухой','grams':80.0},
            {'name':'творог','grams':150.0},
            {'name':'яблоко','grams':65.5}])
        self.assertEqual(len(result['unparsed']),1)
        self.assertIn('2 яйца',result['unparsed'][0]['text'])
        # No household-unit conversion without a confirmed serving definition.
        only_unknown=self.m.food_parse({'text':'один стакан молока'})
        self.assertEqual(only_unknown['items'],[])
        self.assertEqual(len(only_unknown['unparsed']),1)

    def test_fatsecret_provider_lookup_and_link_are_owner_scoped_and_explicit(self):
        self.m.save_onboarding(self.chat,self.body())
        self.m.save_onboarding(self.chat+1,self.body())
        recorded=self.m.food_add(self.chat,{'date':'2026-10-18','meal_type':'breakfast',
            'items':[{'name':'овсянка сухая','grams':70}]})
        item_id=recorded['meals'][0]['items'][0]['id']
        with self.assertRaisesRegex(ValueError,'не подключён'):
            self.m.food_catalog_lookup(self.chat,{'query':'овсянка'})
        from unittest.mock import Mock
        candidate={'food_id':'42','name':'Овсянка сухая','servings':[{
            'serving_id':'13','description':'100 г','grams':100,
            'per_serving':{'kcal':380,'protein_g':13,'fat_g':7,'carbs_g':67}}]}
        fake=Mock()
        fake.get_token.return_value='TEST_ONLY'
        fake.search.return_value=[candidate]
        fake.food_by_id.return_value=candidate
        with patch.object(self.m,'FATSECRET_CLIENT_ID','fake'), \
             patch.object(self.m,'FATSECRET_CLIENT_SECRET','fake'), \
             patch.object(self.m,'FatSecretCatalogClient',return_value=fake):
            result=self.m.food_catalog_lookup(self.chat,{'query':'овсянка'})
            self.assertEqual(result['candidates'][0]['food_id'],'42')
            with self.assertRaises(ValueError):
                self.m.food_catalog_lookup(self.chat,{'query':'test@example.com'})
            with self.assertRaisesRegex(ValueError,'не найден'):
                self.m.food_catalog_attach(self.chat+1,{'id':item_id,'food_id':'42','serving_id':'13'})
            with self.assertRaisesRegex(ValueError,'подтверждённых'):
                self.m.food_catalog_attach(self.chat,{'id':item_id,'food_id':'42','serving_id':'999'})
            with self.connect() as conn:
                self.assertEqual(conn.execute('''SELECT source_food_id FROM manual_food_items
                    WHERE id=%s''',(item_id,)).fetchone()[0],None)
            response=self.m.food_catalog_attach(self.chat,{'id':item_id,'food_id':'42','serving_id':'13'})
            self.assertEqual(response['nutrients']['kcal'],266.0)
            with self.connect() as conn:
                fid,sid,name,grams=conn.execute('''SELECT source_food_id,source_serving_id,
                    name,grams FROM manual_food_items WHERE id=%s''',(item_id,)).fetchone()
            self.assertEqual((fid,sid),('42','13'))
            self.assertEqual(name,'овсянка сухая')
            self.assertEqual(grams,70)
            self.assertIsNone(self.m.food_history(self.chat,{'date':'2026-10-18'})['meals'][0]['items'][0]['kcal'])
            self.m.food_change(self.chat,{'id':item_id,'name':'творог 5%','grams':70})
            with self.connect() as conn:
                self.assertIsNone(conn.execute('''SELECT source_food_id FROM manual_food_items
                    WHERE id=%s''',(item_id,)).fetchone()[0])
        self.assertEqual(fake.search.call_count,1)
        self.assertEqual(fake.food_by_id.call_count,2)

    def test_food_preparation_prevents_cooked_raw_provider_mismatch(self):
        """Different hydration yields different macros per cooked/raw gram."""
        self.assertEqual(self.m.food_preparation_state('Рис сухой'),'raw')
        self.assertEqual(self.m.food_preparation_state('Рис отварной'),'cooked')
        self.assertEqual(self.m.food_preparation_state('Сырники'),None)
        self.assertIsNone(self.m.food_preparation_state('Рис'))
        self.m.save_onboarding(self.chat,self.body())
        result=self.m.food_add(self.chat,{'date':'2026-10-18','meal_type':'lunch',
            'items':[{'name':'Рис сухой','grams':100},
                     {'name':'Рис вареный','grams':200}]})
        items=result['meals'][0]['items']
        from unittest.mock import Mock
        fake=Mock()
        fake.get_token.return_value='OFFLINE_ONLY'
        servings=[{'serving_id':'13','description':'100 граммов','grams':100,
                   'per_serving':{'kcal':350,'protein_g':7,'fat_g':2,'carbs_g':76}}]
        raw={'food_id':'42','name':'Рис сухой','servings':servings}
        cooked={'food_id':'43','name':'Рис отварной','servings':servings}
        with patch.object(self.m,'FATSECRET_CLIENT_ID','offline'), \
             patch.object(self.m,'FATSECRET_CLIENT_SECRET','offline'), \
             patch.object(self.m,'FatSecretCatalogClient',return_value=fake):
            fake.food_by_id.return_value=cooked
            with self.assertRaisesRegex(ValueError,'Сырой и приготовленный'):
                self.m.food_catalog_attach(self.chat,
                    {'id':items[0]['id'],'food_id':'43','serving_id':'13'})
            fake.food_by_id.return_value=raw
            with self.assertRaisesRegex(ValueError,'Сырой и приготовленный'):
                self.m.food_catalog_attach(self.chat,
                    {'id':items[1]['id'],'food_id':'42','serving_id':'13'})
            with self.connect() as conn:
                linked=conn.execute("""SELECT COUNT(*) FROM manual_food_items
                    WHERE chat_id=%s AND source_food_id IS NOT NULL""",
                    (self.chat,)).fetchone()[0]
                self.assertEqual(linked,0)
            matched=self.m.food_catalog_attach(self.chat,
                {'id':items[0]['id'],'food_id':'42','serving_id':'13'})
            self.assertEqual(matched['nutrients']['kcal'],350.0)

    def test_fatsecret_link_cannot_override_user_edit_while_provider_responds(self):
        from unittest.mock import Mock
        self.m.save_onboarding(self.chat,self.body())
        meal=self.m.food_add(self.chat,{'date':'2026-10-18','meal_type':'breakfast',
            'items':[{'name':'овсянка сухая','grams':70}]})
        iid=meal['meals'][0]['items'][0]['id']
        fake=Mock()
        fake.get_token.return_value='OFFLINE_TOKEN'
        candidate={'food_id':'42','name':'Овсянка','servings':[{
            'serving_id':'13','grams':100,'per_serving':{
                'kcal':380,'protein_g':13,'fat_g':7,'carbs_g':67}}]}
        def rename_before_response(*_):
            self.m.food_change(self.chat,{'id':iid,'name':'творог 5%','grams':70})
            return candidate
        fake.food_by_id.side_effect=rename_before_response
        with patch.object(self.m,'FATSECRET_CLIENT_ID','test'), \
             patch.object(self.m,'FATSECRET_CLIENT_SECRET','test'), \
             patch.object(self.m,'FatSecretCatalogClient',return_value=fake):
            with self.assertRaisesRegex(ValueError,'не найден'):
                self.m.food_catalog_attach(self.chat,{
                    'id':iid,'food_id':'42','serving_id':'13'})
        with self.connect() as conn:
            row=conn.execute('''SELECT name,grams,source_food_id,source_serving_id
                FROM manual_food_items WHERE id=%s''',(iid,)).fetchone()
        self.assertEqual(row,('творог 5%',70,None,None))

    def test_tz3_user_supplied_food_macros_recalculate_without_fatsecret(self):
        self.m.save_onboarding(self.chat,self.body())
        per100={'kcal':57,'protein_g':0.7,'fat_g':0.3,'carbs_g':14.5}
        curd={'kcal':121,'protein_g':17,'fat_g':5,'carbs_g':3}
        with patch.object(self.m,'FATSECRET_CLIENT_ID',''), \\
             patch.object(self.m,'FATSECRET_CLIENT_SECRET',''):
            meal=self.m.food_add(self.chat,{'date':'2026-10-18','meal_type':'breakfast',
                'items':[{'name':'Голубика','grams':70,'nutrition_100g':per100},
                         {'name':'Творог 5%','grams':200,'nutrition_100g':curd}]})
            items=meal['meals'][0]['items']
            self.assertEqual([r['nutrition_source'] for r in items],['manual','manual'])
            self.assertEqual(items[0]['nutrition_100g']['kcal'],57.0)
            day=self.m.food_day_totals(self.chat,{'date':'2026-10-18'})
            self.assertTrue(day['complete'])
            self.assertEqual(day['source'],'manual')
            self.assertEqual(day['totals']['kcal'],281.9)
            self.assertEqual(day['totals']['protein_g'],34.49)
            self.assertEqual(day['totals']['carbs_g'],16.15)
            self.assertEqual(day['items'][0]['source'],'manual')
            iid=items[0]['id']
            changed=self.m.food_change(self.chat,{'id':iid,'name':'Голубика','grams':140})
            self.assertEqual(changed['meals'][0]['items'][0]['nutrition_100g']['kcal'],57.0)
            refreshed=self.m.food_day_totals(self.chat,{'date':'2026-10-18'})
            self.assertEqual(refreshed['totals']['kcal'],321.8)
            with self.assertRaises(ValueError):
                self.m.food_change(self.chat+1,{'id':iid,'name':'Голубика','grams':300,
                    'nutrition_100g':per100})
            with self.assertRaises(ValueError):
                self.m.food_change(self.chat,{'id':iid,'name':'Голубика','grams':140,
                    'nutrition_100g':{'kcal':60}})
            self.assertEqual(self.m.food_day_totals(self.chat,{'date':'2026-10-18'})['totals']['kcal'],321.8)
            renamed=self.m.food_change(self.chat,{'id':iid,'name':'Черника','grams':140})
            self.assertIsNone(renamed['meals'][0]['items'][0]['nutrition_100g'])
            partial=self.m.food_day_totals(self.chat,{'date':'2026-10-18'})
            self.assertFalse(partial['complete'])
            self.assertIsNone(partial['totals'])
            self.assertEqual(partial['known_subtotal']['kcal'],242.0)
            restored=self.m.food_change(self.chat,{'id':iid,'name':'Черника','grams':140,
                'nutrition_100g':per100})
            self.assertEqual(restored['meals'][0]['items'][0]['nutrition_source'],'manual')
            self.assertEqual(self.m.food_day_totals(self.chat,{'date':'2026-10-18'})['totals']['kcal'],321.8)
            # Explicit removal of user-entered macros never invents zero kcal.
            self.m.food_change(self.chat,{'id':iid,'name':'Черника','grams':140,'nutrition_100g':None})
            self.assertIsNone(self.m.food_day_totals(self.chat,{'date':'2026-10-18'})['totals'])

    def test_day_kbju_uses_only_owned_verified_portions_and_never_invents_totals(self):
        from unittest.mock import Mock
        self.m.save_onboarding(self.chat,self.body())
        a=self.m.food_add(self.chat,{'date':'2026-10-18','meal_type':'breakfast',
           'items':[{'name':'овсянка сухая','grams':70},
                    {'name':'овсянка сухая','grams':30}]})
        b=self.m.food_add(self.chat,{'date':'2026-10-18','meal_type':'lunch',
           'items':[{'name':'неизвестный продукт','grams':100}]})
        item_ids=[x['id'] for x in a['meals'][0]['items']]
        missing_id=b['meals'][1]['items'][0]['id']
        with self.connect() as conn:
            conn.execute("""UPDATE manual_food_items SET source_food_id='42',
                source_serving_id='13' WHERE id=ANY(%s)""",(item_ids,))
        sample={'food_id':'42','name':'Овсянка сухая',
          'servings':[{'serving_id':'13','grams':100,
          'per_serving':{'kcal':380,'protein_g':13,'fat_g':7,'carbs_g':67}}]}
        fake=Mock()
        fake.get_token.return_value='token-only-test'
        fake.food_by_id.return_value=sample
        with patch.object(self.m,'FATSECRET_CLIENT_ID','fake'), \
             patch.object(self.m,'FATSECRET_CLIENT_SECRET','fake'), \
             patch.object(self.m,'FatSecretCatalogClient',return_value=fake):
            partial=self.m.food_day_totals(self.chat,{'date':'2026-10-18'})
            self.assertFalse(partial['complete'])
            self.assertTrue(partial['partial'])
            self.assertIsNone(partial['totals'])
            self.assertEqual(partial['total_items'],3)
            self.assertEqual(partial['resolved_items'],2)
            self.assertEqual(partial['known_subtotal']['kcal'],380)
            self.assertEqual(len(partial['meals']),2)
            self.assertEqual(partial['meals'][0]['known_subtotal']['protein_g'],13.0)
            self.assertFalse(partial['meals'][1]['complete'])
            self.assertIsNone(partial['meals'][1]['known_subtotal'])
            self.assertEqual(fake.food_by_id.call_count,1,'Duplicate food ID queried once')
            with self.connect() as conn:
                conn.execute("""UPDATE manual_food_items SET source_food_id='42',
                    source_serving_id='13' WHERE id=%s""",(missing_id,))
            complete=self.m.food_day_totals(self.chat,{'date':'2026-10-18'})
            self.assertTrue(complete['complete'])
            self.assertEqual(complete['resolved_items'],3)
            self.assertEqual(complete['totals']['kcal'],760)
            self.assertEqual(complete['totals']['carbs_g'],134)
            empty=self.m.food_day_totals(self.chat,{'date':'2026-10-17'})
            self.assertFalse(empty['complete'])
            self.assertIsNone(empty['totals'])
            self.assertIsNone(empty['known_subtotal'])
            self.m.save_onboarding(self.chat+1,self.body())
            other=self.m.food_day_totals(self.chat+1,{'date':'2026-10-18'})
            self.assertEqual(other['total_items'],0)
            fake.food_by_id.side_effect=RuntimeError('Provider unavailable')
            failure=self.m.food_day_totals(self.chat,{'date':'2026-10-18'})
            self.assertIsNone(failure['totals'])
            self.assertIsNone(failure['known_subtotal'])
            self.assertEqual(failure['resolved_items'],0)
        with self.connect() as conn:
            nutrients=conn.execute("""SELECT column_name FROM information_schema.columns
              WHERE table_schema=%s AND table_name='manual_food_items'
              AND column_name IN ('kcal','protein','fat','carbs')""",(self.schema,)).fetchall()
        self.assertEqual(nutrients,[],'Provider macro values must not be stored')

    def test_fatsecret_oauth_links_owner_with_one_time_callback_encrypted_tokens(self):
        from cryptography.fernet import Fernet
        from urllib.parse import parse_qs,urlsplit
        from unittest.mock import Mock
        self.m.save_onboarding(self.chat,self.body())
        self.m.save_onboarding(self.chat+1,self.body())
        fake=Mock()
        fake.request_token.return_value=('temp-provider-token','temp-provider-secret')
        fake.authorize_url.return_value=(
          'https://authentication.fatsecret.com/oauth/authorize?oauth_token=temp-provider-token')
        fake.access_token.return_value=('SECRET_LONG_TERM_ACCESS','SECRET_LONG_TERM_SIGNING')
        fake.diary.return_value={'food_entries':{'food_entry':[
          {'food_entry_id':'17','food_entry_name':'Овсянка','meal':'Breakfast',
           'calories':'200','protein':'7','fat':'4','carbohydrate':'32'},
          {'food_entry_id':'18','food_entry_name':'Творог','meal':'Lunch',
           'calories':'170','protein':'25','fat':'5','carbohydrate':'4'}]}}
        key=Fernet.generate_key().decode('ascii')
        with patch.object(self.m,'FORMIQ_INTEGRATION_ENCRYPTION_KEY',key), \
             patch.object(self.m,'FATSECRET_OAUTH_CONSUMER_KEY','test-consumer'), \
             patch.object(self.m,'FATSECRET_OAUTH_CONSUMER_SECRET','test-secret'), \
             patch.object(self.m,'FatSecretClient',return_value=fake):
            self.assertFalse(self.m.fatsecret_user_status(self.chat)['connected'])
            url=self.m.fatsecret_user_start(self.chat)['authorization_url']
            self.assertTrue(url.startswith('https://authentication.fatsecret.com/'))
            callback=fake.request_token.call_args.args[0]
            self.assertIn('/mini/fatsecret/callback',callback)
            state=parse_qs(urlsplit(callback).query)['state'][0]
            with self.connect() as conn:
                temporary=conn.execute("""SELECT request_token_enc,request_secret_enc
                    FROM fatsecret_oauth_pending WHERE chat_id=%s""",(self.chat,)).fetchone()
            self.assertNotIn(b'temp-provider-token',bytes(temporary[0]))
            self.assertNotIn(b'temp-provider-secret',bytes(temporary[1]))
            with self.assertRaises(ValueError):
                self.m.fatsecret_user_finish(state,'foreign-request-token','verifier')
            with self.assertRaises(ValueError):
                self.m.fatsecret_user_finish(state+'tampered','temp-provider-token','verifier')
            self.assertFalse(self.m.fatsecret_user_status(self.chat+1)['connected'])
            self.assertTrue(self.m.fatsecret_user_finish(state,'temp-provider-token','verifier'))
            self.assertTrue(self.m.fatsecret_user_status(self.chat)['connected'])
            with self.assertRaises(ValueError):
                self.m.fatsecret_user_finish(state,'temp-provider-token','verifier')
            with self.connect() as conn:
                stored=conn.execute("""SELECT access_token_enc,access_secret_enc
                    FROM fatsecret_user_connections WHERE chat_id=%s""",(self.chat,)).fetchone()
                self.assertIsNone(conn.execute("""SELECT chat_id FROM fatsecret_oauth_pending
                    WHERE chat_id=%s""",(self.chat,)).fetchone())
            self.assertNotIn(b'SECRET_LONG_TERM_ACCESS',bytes(stored[0]))
            self.assertNotIn(b'SECRET_LONG_TERM_SIGNING',bytes(stored[1]))
            day=self.m.fatsecret_user_diary(self.chat,{'date':'2026-10-18'})
            self.assertEqual(day['source'],'fatsecret')
            self.assertTrue(day['complete'])
            self.assertEqual(day['totals']['calories_kcal'],370)
            self.assertEqual(len(day['entries']),2)
            self.assertIsNotNone(self.m.fatsecret_user_status(self.chat)['last_sync_at'])
            with self.assertRaises(ValueError):
                self.m.fatsecret_user_diary(self.chat+1,{'date':'2026-10-18'})
            with self.connect() as conn:
                self.assertEqual(conn.execute("""SELECT COUNT(*) FROM manual_food_items
                    WHERE chat_id=%s""",(self.chat,)).fetchone()[0],0)
            self.assertFalse(self.m.fatsecret_user_disconnect(self.chat)['connected'])
            with self.assertRaises(ValueError):
                self.m.fatsecret_user_diary(self.chat,{'date':'2026-10-18'})
        self.assertEqual(fake.access_token.call_count,1)
        self.assertEqual(fake.diary.call_count,1)

    def test_fatsecret_live_diary_rechecks_access_after_provider_reply(self):
        """Revocation/reconnect during HTTP must not leak previous user's diary."""
        from cryptography.fernet import Fernet
        from unittest.mock import Mock
        self.m.save_onboarding(self.chat,self.body())
        key=Fernet.generate_key()
        cipher=Fernet(key)
        initial_token=cipher.encrypt(b'old_access')
        initial_secret=cipher.encrypt(b'old_secret')
        payload={'food_entries':{'food_entry':[{
            'food_entry_id':'1','food_entry_name':'Private diary entry',
            'calories':'100','protein':'3','fat':'2','carbohydrate':'15'}]}}
        with self.connect() as conn:
            conn.execute("""INSERT INTO fatsecret_user_connections
                (chat_id,access_token_enc,access_secret_enc,connected_at)
                VALUES(%s,%s,%s,NOW())""",(self.chat,initial_token,initial_secret))
        fake=Mock()
        with patch.object(self.m,'FORMIQ_INTEGRATION_ENCRYPTION_KEY',key.decode()), \
             patch.object(self.m,'FATSECRET_OAUTH_CONSUMER_KEY','test'), \
             patch.object(self.m,'FATSECRET_OAUTH_CONSUMER_SECRET','test'), \
             patch.object(self.m,'fatsecret_user_client',return_value=fake):
            def disconnect_during_request(*args):
                self.m.fatsecret_user_disconnect(self.chat)
                return payload
            fake.diary.side_effect=disconnect_during_request
            with self.assertRaisesRegex(ValueError,'отключён или переподключён'):
                self.m.fatsecret_user_diary(self.chat,{'date':'2026-10-18'})
            self.assertFalse(self.m.fatsecret_user_status(self.chat)['connected'])
            with self.connect() as conn:
                conn.execute("""INSERT INTO fatsecret_user_connections
                   (chat_id,access_token_enc,access_secret_enc,connected_at)
                   VALUES(%s,%s,%s,NOW())""",
                   (self.chat,initial_token,initial_secret))
            def replace_during_request(*args):
                with self.connect() as conn:
                    conn.execute("""UPDATE fatsecret_user_connections
                       SET access_token_enc=%s,access_secret_enc=%s
                       WHERE chat_id=%s""",
                       (cipher.encrypt(b'new_access'),cipher.encrypt(b'new_secret'),self.chat))
                return payload
            fake.diary.side_effect=replace_during_request
            with self.assertRaisesRegex(ValueError,'отключён или переподключён'):
                self.m.fatsecret_user_diary(self.chat,{'date':'2026-10-18'})
            with self.connect() as conn:
                self.assertIsNone(conn.execute("""SELECT last_sync_at
                    FROM fatsecret_user_connections WHERE chat_id=%s""",
                    (self.chat,)).fetchone()[0])

    def test_fatsecret_import_refs_are_owner_scoped_editable_and_idempotent(self):
        from cryptography.fernet import Fernet
        from urllib.parse import urlsplit,parse_qs
        from unittest.mock import Mock
        self.m.save_onboarding(self.chat,self.body())
        self.m.save_onboarding(self.chat+1,self.body())
        original=self.m.food_add(self.chat,{'date':'2026-10-18','meal_type':'breakfast',
            'items':[{'name':'овсянка ручная','grams':75}]})
        item_id=original['meals'][0]['items'][0]['id']
        fake=Mock()
        fake.request_token.return_value=('request-token','request-secret')
        fake.authorize_url.return_value='https://authentication.fatsecret.com/oauth/authorize?oauth_token=request-token'
        fake.access_token.return_value=('secret-access','secret-signing')
        fake.diary.return_value={'food_entries':{'food_entry':[
            {'food_entry_id':'17','food_entry_name':'Овсянка','meal':'Breakfast',
             'calories':'200','protein':'7','fat':'4','carbohydrate':'32'},
            {'food_entry_id':'18','food_entry_name':'Творог','meal':'Lunch',
             'calories':'170','protein':'25','fat':'5','carbohydrate':'4'}]}}
        with patch.object(self.m,'FORMIQ_INTEGRATION_ENCRYPTION_KEY',Fernet.generate_key().decode()), \
             patch.object(self.m,'FATSECRET_OAUTH_CONSUMER_KEY','consumer'), \
             patch.object(self.m,'FATSECRET_OAUTH_CONSUMER_SECRET','shared'), \
             patch.object(self.m,'FatSecretClient',return_value=fake):
            self.m.fatsecret_user_start(self.chat)
            cb=fake.request_token.call_args.args[0]
            state=parse_qs(urlsplit(cb).query)['state'][0]
            self.m.fatsecret_user_finish(state,'request-token','verifier')
            with self.assertRaises(ValueError):
                self.m.fatsecret_user_import(self.chat+1,{'date':'2026-10-18'})
            once=self.m.fatsecret_user_import(self.chat,{'date':'2026-10-18'})
            twice=self.m.fatsecret_user_import(self.chat,{'date':'2026-10-18'})
            self.assertEqual(once['imported_count'],2)
            self.assertEqual(twice['imported_count'],2)
            with self.connect() as conn:
                self.assertEqual(conn.execute("""SELECT COUNT(*) FROM fatsecret_import_refs
                    WHERE chat_id=%s""",(self.chat,)).fetchone()[0],2)
                columns=conn.execute("""SELECT column_name FROM information_schema.columns
                    WHERE table_schema=%s AND table_name='fatsecret_import_refs'""",
                    (self.schema,)).fetchall()
                self.assertFalse(any(n[0] in ('calories','protein','fat',
                    'carbs','food_entry_name') for n in columns))
            with self.assertRaises(ValueError):
                self.m.fatsecret_user_import_edit(self.chat+1,{'date':'2026-10-18',
                    'external_id':'17','name_override':'чужой'})
            edited=self.m.fatsecret_user_import_edit(self.chat,{'date':'2026-10-18',
                'external_id':'17','name_override':'Моя овсянка',
                'meal_override':'snack'})
            self.assertTrue(edited['imported'])
            shown=self.m.fatsecret_user_diary(self.chat,{'date':'2026-10-18'})
            first=next(x for x in shown['entries'] if x['external_id']=='17')
            self.assertEqual(first['name'],'Моя овсянка')
            self.assertEqual(first['meal'],'snack')
            self.assertEqual(first['kcal'],200)
            self.assertTrue(first['imported'])
            self.assertTrue(first['user_edited'])
            self.m.fatsecret_user_import(self.chat,{'date':'2026-10-18'})
            self.assertEqual(self.m.fatsecret_user_diary(self.chat,{'date':'2026-10-18'})['entries'][0]['name'],'Моя овсянка')
            unlinked=self.m.fatsecret_user_import_edit(self.chat,{'date':'2026-10-18',
                'external_id':'17'},delete=True)
            self.assertFalse(unlinked['imported'])
            with self.assertRaisesRegex(ValueError,'не найдена'):
                self.m.fatsecret_user_import_edit(self.chat,{'date':'2026-10-18',
                    'external_id':'17','name_override':'Ошибка'})
            after=self.m.fatsecret_user_diary(self.chat,{'date':'2026-10-18'})
            self.assertFalse(after['entries'][0]['imported'])
            self.assertEqual(after['entries'][0]['name'],'Овсянка')
            manual=self.m.food_history(self.chat,{'date':'2026-10-18'})
            self.assertEqual(manual['meals'][0]['items'][0]['id'],item_id)
            self.assertEqual(manual['meals'][0]['items'][0]['grams'],75)
            self.m.fatsecret_user_disconnect(self.chat)
            with self.assertRaises(ValueError):
                self.m.fatsecret_user_import(self.chat,{'date':'2026-10-18'})
            # Disconnect invalidates credentials without destroying imported refs.
            with self.connect() as conn:
                self.assertEqual(conn.execute("""SELECT COUNT(*) FROM fatsecret_import_refs
                    WHERE chat_id=%s""",(self.chat,)).fetchone()[0],1)
            # A different FatSecret authorization may reuse the same numeric
            # provider entry IDs. Old owner edits MUST NOT attach to that diary.
            self.m.fatsecret_user_start(self.chat)
            callback2=fake.request_token.call_args.args[0]
            state2=parse_qs(urlsplit(callback2).query)['state'][0]
            self.assertNotEqual(state,state2)
            self.m.fatsecret_user_finish(state2,'request-token','verifier')
            fresh=self.m.fatsecret_user_diary(self.chat,{'date':'2026-10-18'})
            self.assertEqual(len(fresh['entries']),2)
            self.assertTrue(all(not e['imported'] for e in fresh['entries']))
            with self.assertRaisesRegex(ValueError,'не найдена'):
                self.m.fatsecret_user_import_edit(self.chat,{'date':'2026-10-18',
                    'external_id':'18','name_override':'Не от старого аккаунта'})
            self.m.fatsecret_user_import(self.chat,{'date':'2026-10-18'})
            with self.connect() as conn:
                refs=conn.execute("""SELECT connection_id,external_id,user_name_override
                    FROM fatsecret_import_refs WHERE chat_id=%s
                    ORDER BY connection_id,external_id""",(self.chat,)).fetchall()
                self.assertEqual(len(refs),3, 'Previous imported references remain preserved')
                self.assertEqual(len({x[0] for x in refs}),2)
                self.assertFalse(any(x[2] for x in refs))
            self.assertEqual(self.m.food_history(self.chat,
                {'date':'2026-10-18'})['meals'][0]['items'][0]['id'],item_id)

    def test_fatsecret_connection_rejects_invalid_encryption_key(self):
        self.m.save_onboarding(self.chat,self.body())
        with patch.object(self.m,'FORMIQ_INTEGRATION_ENCRYPTION_KEY','incorrect-key'), \
             patch.object(self.m,'FATSECRET_OAUTH_CONSUMER_KEY','offline'), \
             patch.object(self.m,'FATSECRET_OAUTH_CONSUMER_SECRET','offline'):
            self.assertFalse(self.m.fatsecret_user_oauth_ready())
            self.assertFalse(self.m.fatsecret_user_status(self.chat)['available'])
            with self.assertRaisesRegex(ValueError,'не настроено'):
                self.m.fatsecret_user_start(self.chat)
        self.assertFalse(self.m.fatsecret_user_status(self.chat)['connected'])

    def test_fatsecret_oauth_callback_error_does_not_link_account(self):
        from cryptography.fernet import Fernet
        from unittest.mock import Mock
        from urllib.parse import urlsplit,parse_qs
        self.m.save_onboarding(self.chat,self.body())
        fake=Mock()
        fake.request_token.return_value=('request-token','request-secret')
        fake.authorize_url.return_value='https://authentication.fatsecret.com/oauth/authorize?oauth_token=request-token'
        fake.access_token.side_effect=RuntimeError('Provider rejected verifier')
        with patch.object(self.m,'FORMIQ_INTEGRATION_ENCRYPTION_KEY',Fernet.generate_key().decode()), \
             patch.object(self.m,'FATSECRET_OAUTH_CONSUMER_KEY','test'), \
             patch.object(self.m,'FATSECRET_OAUTH_CONSUMER_SECRET','test'), \
             patch.object(self.m,'FatSecretClient',return_value=fake):
            self.m.fatsecret_user_start(self.chat)
            callback=fake.request_token.call_args.args[0]
            state=parse_qs(urlsplit(callback).query)['state'][0]
            with self.assertRaises(ValueError):
                self.m.fatsecret_user_finish(state,'request-token','verifier')
            self.assertFalse(self.m.fatsecret_user_status(self.chat)['connected'])
            self.assertFalse(self.m.fatsecret_user_disconnect(self.chat)['connected'])

    def test_offline_garmin_import_requires_consent_mapping_and_is_idempotent(self):
        self.m.save_onboarding(self.chat,self.body())
        snapshot=self.snapshot_history()
        payload={'dailies':[{'userId':'OFFLINE_GARMIN_1','summaryId':'d20261018',
             'calendarDate':'2026-10-18','steps':7000,'activeKilocalories':450,
             'totalKilocalories':2450,'bmrKilocalories':1600}],
          'activities':[{'userId':'OFFLINE_GARMIN_1','summaryId':'a1',
             'startTimeInSeconds':1792300000,'durationInSeconds':1800,
             'activityType':'running','activeKilocalories':310}]}
        with self.assertRaises(PermissionError):
            self.m.ingest_garmin_verified_batch(self.chat,'OFFLINE_GARMIN_1',payload)
        with self.connect() as conn:
            conn.execute("""INSERT INTO garmin_authorized_identities
               (chat_id,provider_user_id,health_consent_at)
               VALUES(%s,%s,NOW())""",(self.chat,'OFFLINE_GARMIN_1'))
        with self.assertRaises(PermissionError):
            self.m.ingest_garmin_verified_batch(self.chat+1,'OFFLINE_GARMIN_1',payload)
        with self.assertRaises(PermissionError):
            self.m.ingest_garmin_verified_batch(self.chat,'OTHER_ACCOUNT',payload)
        first=self.m.ingest_garmin_verified_batch(self.chat,'OFFLINE_GARMIN_1',payload)
        second=self.m.ingest_garmin_verified_batch(self.chat,'OFFLINE_GARMIN_1',payload)
        self.assertEqual(first['processed'],2)
        self.assertEqual(second['processed'],2)
        with self.connect() as conn:
            events=conn.execute("""SELECT category,metrics_json FROM garmin_metric_events
                WHERE chat_id=%s ORDER BY category""",(self.chat,)).fetchall()
            self.assertEqual(len(events),2,'A repeated Garmin delivery is an UPSERT, not a new workout')
            daily=next(m for c,m in events if c=='dailies')
            activity=next(m for c,m in events if c=='activities')
            self.assertEqual(daily['active_calories_kcal'],450)
            self.assertEqual(daily['total_daily_calories_kcal'],2450)
            self.assertNotIn('total_daily_calories_kcal',activity)
            self.assertEqual(activity['duration_seconds'],1800)
            self.assertEqual(conn.execute("""SELECT COUNT(*) FROM garmin_metric_events
              WHERE chat_id=%s""",(self.chat+1,)).fetchone()[0],0)
            self.assertIsNotNone(conn.execute("""SELECT last_sync_at
               FROM garmin_authorized_identities WHERE chat_id=%s""",(self.chat,)).fetchone()[0])
        edited={'dailies':[dict(payload['dailies'][0],steps=8200)]}
        self.m.ingest_garmin_verified_batch(self.chat,'OFFLINE_GARMIN_1',edited)
        with self.connect() as conn:
            self.assertEqual(conn.execute("""SELECT COUNT(*) FROM garmin_metric_events
               WHERE chat_id=%s""",(self.chat,)).fetchone()[0],2)
            self.assertEqual(conn.execute("""SELECT metrics_json->>'steps' FROM garmin_metric_events
               WHERE chat_id=%s AND category='dailies'""",(self.chat,)).fetchone()[0],'8200.0')
            conn.execute("""UPDATE garmin_authorized_identities SET disconnected_at=NOW()
               WHERE chat_id=%s""",(self.chat,))
        with self.assertRaises(PermissionError):
            self.m.ingest_garmin_verified_batch(self.chat,'OFFLINE_GARMIN_1',payload)
        self.assertEqual(snapshot,self.snapshot_history(),'Never touch manual workout history')
        with self.assertRaises(ValueError):
            self.m.ingest_garmin_verified_batch(self.chat,'OFFLINE_GARMIN_1',
                {'dailies':[{'userId':'OFFLINE_GARMIN_1','summaryId':'bad','steps':9}]})

    def test_garmin_read_day_does_not_expose_unconnected_foreign_or_revoked_data(self):
        self.m.save_onboarding(self.chat,self.body())
        self.m.save_onboarding(self.chat+1,self.body())
        day='2026-10-18'
        offline=self.m.garmin_connected_day(self.chat,{'date':day})
        self.assertFalse(offline['connected'])
        self.assertEqual(offline['dailies'],[])
        with self.connect() as conn:
            conn.execute("""INSERT INTO garmin_authorized_identities
                 (chat_id,provider_user_id,health_consent_at)
                 VALUES(%s,'OFFLINE_GARMIN_TEST',NOW())""",(self.chat,))
        supplied={'dailies':[{'userId':'OFFLINE_GARMIN_TEST','summaryId':'day01',
                 'calendarDate':day,'steps':9000,'activeKilocalories':300,
                 'totalKilocalories':2200,'restingHeartRateInBeatsPerMinute':55}],
                 'activities':[{'userId':'OFFLINE_GARMIN_TEST','summaryId':'run01',
                 'startTimeInSeconds':1792300000,'durationInSeconds':2400,
                 'activityType':'running','activeKilocalories':240}]}
        self.m.ingest_garmin_verified_batch(self.chat,'OFFLINE_GARMIN_TEST',supplied)
        reading=self.m.garmin_connected_day(self.chat,{'date':day})
        self.assertTrue(reading['connected'])
        self.assertIsNotNone(reading['last_sync_at'])
        self.assertEqual(reading['dailies'][0]['values']['steps'],9000)
        self.assertEqual(reading['dailies'][0]['values']['active_calories_kcal'],300)
        self.assertEqual(reading['dailies'][0]['values']['total_daily_calories_kcal'],2200)
        self.assertEqual(reading['dailies'][0]['values']['resting_heart_rate_bpm'],55)
        self.assertNotIn('provider_user_id',str(reading))
        self.assertEqual(len(reading['activities']),1)
        self.assertNotIn('total_daily_calories_kcal',reading['activities'][0]['values'])
        other=self.m.garmin_connected_day(self.chat+1,{'date':day})
        self.assertFalse(other['connected'])
        self.assertEqual(other['activities'],[])
        empty=self.m.garmin_connected_day(self.chat,{'date':'2026-10-17'})
        self.assertTrue(empty['connected'])
        self.assertEqual(empty['dailies'],[])
        with self.connect() as conn:
            count_before=conn.execute("""SELECT COUNT(*) FROM garmin_metric_events
                  WHERE chat_id=%s""",(self.chat,)).fetchone()[0]
        self.assertFalse(self.m.garmin_disconnect_owner(self.chat+1)['connected'])
        self.assertFalse(self.m.garmin_disconnect_owner(self.chat)['connected'])
        revoked=self.m.garmin_connected_day(self.chat,{'date':day})
        self.assertFalse(revoked['connected'])
        self.assertEqual(revoked['dailies'],[])
        with self.connect() as conn:
            count_after=conn.execute("""SELECT COUNT(*) FROM garmin_metric_events
                  WHERE chat_id=%s""",(self.chat,)).fetchone()[0]
        self.assertEqual(count_before,count_after,'Disconnect must not erase private history')
        with self.assertRaises(PermissionError):
            self.m.ingest_garmin_verified_batch(self.chat,'OFFLINE_GARMIN_TEST',supplied)
        for bad in ('bad-date','2026-02-30'):
            with self.assertRaises(ValueError):
                self.m.garmin_connected_day(self.chat,{'date':bad})

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


    def test_tz3_optional_health_note_does_not_require_obsolete_questionnaire(self):
        data=self.body()
        data['health_profile']=None
        self.m.save_onboarding(self.chat,data)
        self.assertEqual(self.m.health_profile(self.chat)['affected'],[])
        data['health_profile']={'affected':['shoulder'],'pain_score':0,
            'symptom_course':'none','danger_signs':False,'activity_cleared':False}
        self.m.save_onboarding(self.chat,data)
        stored=self.m.health_profile(self.chat)
        self.assertEqual(stored['affected'],['shoulder'])
        self.assertEqual(stored['symptom_course'],'unspecified')

    def test_tz3_completed_slot_shows_only_real_stored_sets(self):
        profile,cycle,calendar=self.save((0,2,4))
        slot=calendar[0]
        began=Clock.instant
        finished=began+timedelta(minutes=37)
        with self.connect() as conn:
            wid=conn.execute("""INSERT INTO workouts(
                chat_id,cycle_id,week_no,plan_day,status,started_at,
                finished_at,source,difficulty)
                VALUES(%s,%s,%s,%s,'finished',%s,%s,'template','ok')
                RETURNING id""",(self.chat,cycle,slot['week'],slot['day'],began,finished)).fetchone()[0]
            conn.execute("""INSERT INTO workout_items(workout_id,position,exercise,
                target,exercise_key) VALUES(%s,0,'Жим ногами','3 x 10','leg_press')""",(wid,))
            conn.execute("""INSERT INTO workout_sets(workout_id,position,set_no,
                target_min,target_max,unit,actual_value,state,weight_kg,completed_at)
                VALUES(%s,0,1,8,12,'reps',11,'done',42.5,%s)""",(wid,finished))
        history_before=self.snapshot_history()
        preview=self.m.mini_training_preview(self.chat,{'id':slot['id']})['preview']
        self.assertTrue(preview['finished'])
        self.assertFalse(preview['can_start'])
        self.assertEqual(preview['exercises'],[])
        self.assertEqual(preview['actual']['duration_minutes'],37)
        self.assertEqual(preview['actual']['result'],'ok')
        self.assertIn('11 повт.',preview['actual']['items'][0]['result'])
        self.assertIn('/Leg_Press/0.jpg',preview['actual']['items'][0]['image_url'])
        self.assertEqual(preview['actual']['items'][0]['image_license_url'],
                         'https://creativecommons.org/licenses/by-sa/4.0/')
        self.assertRegex(preview['actual']['items'][0]['result'],r'42[.]50? кг')
        self.assertEqual(self.snapshot_history(),history_before)
        with self.assertRaises(ValueError):
            self.m.mini_training_preview(self.chat+1,{'id':slot['id']})

    def test_recent_additional_cardio_reduces_future_volume_explainably(self):
        profile,cycle,calendar=self.save((0,2,4))
        baseline=self.m.make_session(profile,1,'A',adapt='normal',cycle_id=cycle)
        with self.connect() as conn:
            conn.execute("""INSERT INTO cardio_sessions(chat_id,minutes,equipment,intensity)
                VALUES(%s,100,'Бег','vigorous')""",(self.chat,))
        adapt,reason=self.m.adjustment(self.chat,'A')
        self.assertEqual(adapt,'lighter')
        self.assertIn('кардио',reason)
        lighter=self.m.make_session(profile,1,'A',adapt=adapt,cycle_id=cycle)
        self.assertLess(sum(x[1] for x in lighter),sum(x[1] for x in baseline))
        preview=self.m.mini_training_preview(self.chat,{'id':calendar[0]['id']})['preview']
        self.assertIn('восстановиться',preview['recovery_advice'])
        with self.connect() as conn:
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM workouts WHERE chat_id=%s',
                (self.chat,)).fetchone()[0],0,'Preview never starts or completes a workout')

    def test_recent_consent_bound_garmin_activity_reduces_load_no_duplicates(self):
        p,cycle,calendar=self.save((0,2,4))
        self.m.save_onboarding(999,self.body((0,2,4)))
        baseline=self.m.make_session(p,1,'A',adapt='normal',cycle_id=cycle)
        # Unconnected and other-owner data never affect this user's training.
        with self.connect() as conn:
            conn.execute("""INSERT INTO garmin_authorized_identities
                (chat_id,provider_user_id,health_consent_at)
                VALUES(%s,'GARMIN_TEST_999',NOW()),(%s,'GARMIN_TEST_777',NOW())""",
                (999,self.chat))
            conn.execute("""INSERT INTO garmin_metric_events
                (chat_id,provider_user_id,category,external_id,event_at_utc,metrics_json)
                VALUES(%s,'GARMIN_TEST_999','activities','a-1',
                   NOW()-INTERVAL '3 hours','{"duration_seconds":7200}'::jsonb)""",(999,))
        before=self.m.adjustment(self.chat,'A')
        self.assertEqual(before[0],'normal')
        with self.connect() as conn:
            conn.execute("""INSERT INTO garmin_metric_events
                (chat_id,provider_user_id,category,external_id,event_at_utc,metrics_json)
                VALUES(%s,'GARMIN_TEST_777','activities','a-1',
                   NOW()-INTERVAL '3 hours','{"duration_seconds":5400,"activity_type":"cycling"}'::jsonb)""",
                (self.chat,))
        adapt,reason=self.m.adjustment(self.chat,'A')
        self.assertEqual(adapt,'lighter')
        self.assertIn('Garmin',reason)
        reduced=self.m.make_session(p,1,'A',adapt=adapt,cycle_id=cycle)
        self.assertLess(sum(x[1] for x in reduced),sum(x[1] for x in baseline))
        with self.connect() as conn:
            conn.execute("""UPDATE garmin_authorized_identities SET disconnected_at=NOW()
                WHERE chat_id=%s""",(self.chat,))
        self.assertEqual(self.m.adjustment(self.chat,'A')[0],'normal',
            'After revocation, preserved Garmin history cannot affect adaptation')
        with self.connect() as conn:
            self.assertEqual(conn.execute('SELECT count(*) FROM garmin_metric_events WHERE chat_id=%s',
                (self.chat,)).fetchone()[0],1)
            self.assertEqual(conn.execute('SELECT count(*) FROM workouts WHERE chat_id=%s',
                (self.chat,)).fetchone()[0],0)

    def test_manual_weight_does_not_replace_imported_measurements(self):
        self.m.save_onboarding(self.chat,self.body())
        from datetime import datetime,timezone
        existing=datetime(2026,10,20,8,tzinfo=timezone.utc)
        with self.connect() as conn:
            conn.execute("""INSERT INTO body_measurements
                (chat_id,measured_at,source,weight_kg) VALUES(%s,%s,'fitdays',%s)""",
                (self.chat,existing,81))
        self.m.mini_manual_measurement(self.chat,{'date':'2026-10-20','weight_kg':80.5})
        self.m.mini_manual_measurement(self.chat,{'date':'2026-10-20','weight_kg':80.2})
        with self.connect() as conn:
            rows=conn.execute("""SELECT source,weight_kg FROM body_measurements
                WHERE chat_id=%s ORDER BY source""",(self.chat,)).fetchall()
        self.assertEqual(len(rows),2)
        self.assertEqual({source:float(weight) for source,weight in rows},
                         {'fitdays':81,'manual':80.2})
        self.assertEqual(self.m.mini_body_weight_history(self.chat+1),[])

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

    def test_opt_in_yandex_nutrition_uses_only_owners_manual_food_date(self):
        """Never fake macros or export another user's meal to Yandex."""
        import io,json
        data=self.body()
        data['ai_profile_consent']=True
        self.m.save_onboarding(self.chat,data)
        self.m.save_onboarding(999,self.body())
        self.m.food_add(self.chat,{'date':'2026-10-18','meal_type':'lunch',
            'items':[{'name':'рис сухой','grams':85}]})
        self.m.food_add(999,{'date':'2026-10-18','meal_type':'lunch',
            'items':[{'name':'ЧУЖОЙ УЖИН','grams':200}]})
        submitted=[]
        def provider(request,timeout=None):
            body=json.loads(request.data)
            submitted.append(json.loads(body['messages'][-1]['text']))
            return io.BytesIO(json.dumps({'result':{'alternatives':[{
                'message':{'text':'Собери сбалансированный рацион.'}}]}}).encode())
        with patch.object(self.m,'YANDEX_KEY','offline-only'), \
             patch.object(self.m,'FOLDER_ID','offline-only'), \
             patch.object(self.m.urllib.request,'urlopen',side_effect=provider):
            result=self.m.ai_personalized_guidance(self.chat,
                {'purpose':'nutrition','date':'2026-10-18'})
            self.assertTrue(result['used_ai'])
            self.assertEqual(len(submitted),1)
            facts=submitted[-1]
            self.assertEqual(facts['nutrition_day'],'2026-10-18')
            self.assertEqual(len(facts['manual_food_entries']),1)
            self.assertEqual(facts['manual_food_entries'][0]['user_entered_name'],'рис сухой')
            self.assertEqual(facts['manual_food_entries'][0]['grams'],85)
            self.assertIsNone(facts['verified_nutrition_values'])
            self.assertNotIn('ЧУЖОЙ УЖИН',str(facts))
            self.assertNotIn('chat_id',str(facts))
            self.m.set_personalization_consent(self.chat,
                {'field':'profile','enabled':False})
            with self.assertRaisesRegex(ValueError,'Разреши'):
                self.m.ai_personalized_guidance(self.chat,
                    {'purpose':'nutrition','date':'2026-10-18'})
            self.assertEqual(len(submitted),1)

    def test_yandex_nutrition_discards_reply_after_concurrent_diary_edit(self):
        """A second-device edit during provider HTTP must invalidate old advice."""
        import io,json
        profile=self.body()
        profile['ai_profile_consent']=True
        self.m.save_onboarding(self.chat,profile)
        self.m.food_add(self.chat,{'date':'2026-10-18','meal_type':'lunch',
            'items':[{'name':'Рис сухой','grams':80}]})
        calls=[]
        def slow_reply(request,timeout=None):
            calls.append(json.loads(request.data))
            self.m.food_add(self.chat,{'date':'2026-10-18','meal_type':'lunch',
                'items':[{'name':'Творог','grams':150}]})
            return io.BytesIO(json.dumps({'result':{'alternatives':[{
                'message':{'text':'Совет по устаревшим продуктам.'}}]}}).encode())
        with patch.object(self.m,'YANDEX_KEY','offline-only'), \
             patch.object(self.m,'FOLDER_ID','offline-only'), \
             patch.object(self.m.urllib.request,'urlopen',side_effect=slow_reply):
            with self.assertRaisesRegex(ValueError,'изменился во время анализа'):
                self.m.ai_personalized_guidance(self.chat,
                    {'purpose':'nutrition','date':'2026-10-18'})
        self.assertEqual(len(calls),1)
        products=self.m.food_history(self.chat,{'date':'2026-10-18'})
        self.assertEqual([x['name'] for x in products['meals'][0]['items']],
                         ['Рис сухой','Творог'],
                         'Reject stale AI, not the real nutrition history')

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

    def test_confirmed_deletion_removes_only_owner_integration_data(self):
        """Privacy regression in disposable PG18; never use a live database."""
        monitored=('manual_food_meals','manual_food_items','body_measurements',
                   'fatsecret_oauth_pending','fatsecret_user_connections',
                   'fatsecret_import_refs','garmin_authorized_identities',
                   'garmin_metric_events')
        for owner in (self.chat,999):
            self.m.save_onboarding(owner,self.body((0,2)))
            self.m.food_add(owner,{'date':'2026-10-18',
                'meal_type':'breakfast','items':[{'name':'Рис сухой','grams':80}]})
            with self.connect() as conn:
                conn.execute("""INSERT INTO body_measurements
                    (chat_id,measured_at,weight_kg)
                    VALUES(%s,'2026-10-18T09:00:00+00:00',82)""",(owner,))
                conn.execute("""INSERT INTO fatsecret_oauth_pending
                    (chat_id,state_hash,request_token_enc,request_secret_enc,expires_at)
                    VALUES(%s,%s,%s,%s,NOW()+INTERVAL '10 minutes')""",
                    (owner,'state-'+str(owner),b'temporary',b'secret'))
                connection=conn.execute("""INSERT INTO fatsecret_user_connections
                    (chat_id,access_token_enc,access_secret_enc)
                    VALUES(%s,%s,%s) RETURNING connection_id""",
                    (owner,b'token',b'signing')).fetchone()[0]
                conn.execute("""INSERT INTO fatsecret_import_refs
                    (chat_id,connection_id,eaten_on,external_id)
                    VALUES(%s,%s,'2026-10-18','123')""",(owner,connection))
                provider_id='DELETION_TEST_'+str(owner)
                conn.execute("""INSERT INTO garmin_authorized_identities
                    (chat_id,provider_user_id,health_consent_at)
                    VALUES(%s,%s,NOW())""",(owner,provider_id))
                conn.execute("""INSERT INTO garmin_metric_events
                    (chat_id,provider_user_id,category,external_id,
                     local_calendar_date,metrics_json)
                    VALUES(%s,%s,'dailies','day-1','2026-10-18',
                           '{"steps":7000}'::jsonb)""",(owner,provider_id))
        with self.connect() as conn:
            for table in monitored:
                for owner in (self.chat,999):
                    count=conn.execute(sql.SQL('SELECT count(*) FROM {} WHERE chat_id=%s')
                        .format(sql.Identifier(table)),(owner,)).fetchone()[0]
                    self.assertEqual(count,1,(table,owner))
        with patch.object(self.m,'send') as send:
            self.m.delete_all(self.chat)
            send.assert_called_once()
        with self.connect() as conn:
            for table in monitored:
                for owner,expected in ((self.chat,0),(999,1)):
                    count=conn.execute(sql.SQL('SELECT count(*) FROM {} WHERE chat_id=%s')
                        .format(sql.Identifier(table)),(owner,)).fetchone()[0]
                    self.assertEqual(count,expected,(table,owner))
        # The remaining user's account and all manual food must remain intact.
        self.assertEqual(self.m.food_history(999,{'date':'2026-10-18'})
            ['meals'][0]['items'][0]['name'],'Рис сухой')

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
