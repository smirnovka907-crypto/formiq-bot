"""TZ4/A offline safety regressions. No live user or provider data."""
import importlib
import os
import unittest
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, MagicMock
from cryptography.fernet import Fernet
from food_allergens import (CATALOG_VERSION, canonical_food,
    normalise_restrictions, evaluate_composition, select_automatic_candidates)


def evidence(ingredients, *, traces=None, complete=True, cross_contact=False,
             source_type='manufacturer', age_days=0):
    return {'composition':{
        'source_type':source_type,'source_id':'manufacturer-test-2026',
        'verified_at':(datetime.now(timezone.utc)-timedelta(days=age_days)).isoformat(),
        'ingredients':ingredients,'may_contain':traces if traces is not None else [],
        'complete':complete,'cross_contact_unknown':cross_contact}}


class AllergenDictionaryTests(unittest.TestCase):
    def setUp(self):
        self.egg=normalise_restrictions([{'name':'Яйца','kind':'allergy'}])
        self.milk=normalise_restrictions([{'name':'Молоко','kind':'intolerance'}])

    def test_dictionary_is_versioned_and_canonical(self):
        self.assertIn('2026',CATALOG_VERSION)
        self.assertEqual(canonical_food('Яйца'),'egg')
        self.assertEqual(canonical_food('Арахис'),'peanut')
        self.assertEqual(canonical_food('Молоко'),'milk')
        self.assertEqual(self.egg[0]['canonical'],'egg')
        self.assertEqual(self.milk[0]['kind'],'intolerance')

    def test_direct_quail_egg_whites_yolk_powder_and_protein_derivatives(self):
        products=[
          ['яйца куриные'],['перепелиные яйца'],['яичный белок'],
          ['желток'],['яичный порошок'],['яичный альбумин'],
          ['овальбумин'],['овомукоид'],['лизоцим E1105'],
          ['egg yolk'],['quail egg'],['ovalbumin'],['lysozyme E1105'],['E1105'],
          ['яичный меланж'],['меланж яичный'],['меланж'],
          ['меланжа'],['сухого меланжа'],
          ['яичная масса'],['желточный порошок'],['сухой желток'],
          ['E-1105'],['лизоцим E-1105'],['egg solids'],['dried egg'],
          ['egg wash'],['whole egg powder'],['egg lecithin']
        ]
        for ingredients in products:
            with self.subTest(ingredients=ingredients):
                result=evaluate_composition(evidence(ingredients),self.egg,
                                            trusted_server_source=True)
                self.assertEqual(result['status'],'excluded')

    def test_inflected_egg_proteins_and_unverified_origin(self):
        for ingredient in ('яичным белком','яичного порошка','овальбумина',
                           'овомукоида','сушёными яичными компонентами',
                           'перепелиных яиц'):
            with self.subTest(ingredient=ingredient):
                self.assertEqual(evaluate_composition(evidence(['рис',ingredient]),
                    self.egg,trusted_server_source=True)['status'],'excluded')
        for ingredient in ('альбумин','лизоцим','ароматизатор',
                           'растительное масло','смесь специй'):
            with self.subTest(ingredient=ingredient):
                self.assertEqual(evaluate_composition(evidence(['вода',ingredient]),
                    self.egg,trusted_server_source=True)['status'],'needs_review')

    def test_detected_conflict_overrides_missing_trace_list_and_unknown_other_allergen(self):
        unknown=normalise_restrictions([{'name':'Редкое неизвестное вещество',
                                        'kind':'allergy'}])
        ingredient=evidence(['яичный порошок'])
        ingredient['composition'].pop('may_contain')
        self.assertEqual(evaluate_composition(ingredient,unknown+self.egg,
            trusted_server_source=True)['status'],'excluded')
        warning=evidence(['вода'],traces=['может содержать яичный белок'])
        warning['composition'].pop('ingredients')
        self.assertEqual(evaluate_composition(warning,unknown+self.egg,
            trusted_server_source=True)['status'],'excluded')

    def test_declared_complete_does_not_certify_unknown_placeholder(self):
        for ingredient in ('неизвестно','прочие компоненты','unknown'):
            with self.subTest(ingredient=ingredient):
                self.assertEqual(evaluate_composition(
                    evidence(['рис',ingredient]),self.egg,
                    trusted_server_source=True)['status'],'needs_review')

    def test_manufacturer_trace_warning_also_excludes(self):
        product=evidence(['вода','рис'],traces=['Может содержать следы яйца'])
        self.assertEqual(evaluate_composition(product,self.egg,
            trusted_server_source=True)['status'],'excluded')
        self.assertEqual(evaluate_composition(
            evidence(['вода','яичный порошок'],complete=False),self.egg,
            trusted_server_source=True)['status'],'excluded')
        self.assertEqual(evaluate_composition(
            evidence(['вода'],traces=['Может содержать яйца'],complete=False),
            self.egg,trusted_server_source=True)['status'],'excluded')

    def test_stale_incomplete_and_unknown_composition_are_not_cleared(self):
        candidates=[
            {'name':'Паста'},evidence(['рис'],age_days=31),
            evidence(['рис'],complete=False),
            evidence(['рис'],cross_contact=True),
            evidence(['рис'],source_type='ai'),
            evidence(['рис'],traces=['']),
            evidence(['рис'],traces=[],cross_contact=False),
        ]
        for c in candidates[:-1]:
            with self.subTest(product=c):
                self.assertEqual(evaluate_composition(c,self.egg,
                    trusted_server_source=True)['status'],'needs_review')
        self.assertEqual(evaluate_composition(candidates[-1],self.egg,
            trusted_server_source=True)['status'],'no_conflicts_detected')

    def test_composite_and_ambiguous_ingredients_need_verification(self):
        for name in ['майонез','паста','макароны','соус','эмульгатор','лецитин','альбумин']:
            with self.subTest(name=name):
                self.assertEqual(evaluate_composition(evidence([name]),self.egg,
                    trusted_server_source=True)['status'],'needs_review')
        # A brand/category name never creates a presumed allergy.
        dish={'name':'майонез','composition':evidence(['масло','вода'])['composition']}
        self.assertEqual(evaluate_composition(dish,self.egg,
            trusted_server_source=True)['status'],'no_conflicts_detected')

    def test_untrusted_ai_or_tampered_client_cannot_certify_composition(self):
        fake=evidence(['вода','рис'])
        fake['source_verified']=True
        fake['composition']['server_verified']=True
        self.assertEqual(evaluate_composition(fake,self.egg)['status'],'needs_review')
        # Clear direct allergy still rejects even untrusted composition.
        self.assertEqual(evaluate_composition(evidence(['egg powder']),self.egg)
                         ['status'],'excluded')

    def test_only_verified_non_conflicting_can_enter_auto_candidates(self):
        good=evidence(['рис','вода'])
        forbidden=evidence(['яичный альбумин'])
        uncertain=evidence(['эмульгатор'])
        allowed=select_automatic_candidates([good,forbidden,uncertain],
                 self.egg,trusted_server_source=True)
        self.assertEqual(allowed,[good])
        self.assertEqual(select_automatic_candidates([good],self.egg),[])

    def test_input_duplicates_invalid_types_and_unknown_are_not_silently_safe(self):
        with self.assertRaises(ValueError):
            normalise_restrictions([{'name':'Яйца','kind':'allergy'},
                                   {'name':'яйца','kind':'intolerance'}])
        with self.assertRaises(ValueError):
            normalise_restrictions([{'name':'Яйца','kind':'severe'}])
        with self.assertRaises(ValueError):
            normalise_restrictions([{'name':'','kind':'allergy'}])
        novel=normalise_restrictions([{'name':'Неизвестный ингредиент','kind':'allergy'}])
        self.assertIsNone(novel[0]['canonical'])
        self.assertEqual(evaluate_composition(evidence(['рис']),novel,
            trusted_server_source=True)['status'],'needs_review')


class FoodAllergyPrivacyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with patch.dict(os.environ,{
            'TELEGRAM_BOT_TOKEN':'123456789:TESTONLY_allergies',
            'DATABASE_URL':'postgresql://unused:unused@example.invalid/never_connect',
            'RENDER_EXTERNAL_URL':'https://example.invalid'
        }):
            cls.m=importlib.import_module('main')
        cls.client=cls.m.APP.test_client()

    def setUp(self):
        self.enabled=patch.object(self.m,'FOOD_ALLERGY_PROCESSING_ENABLED',True)
        self.key=patch.object(self.m,'FORMIQ_HEALTH_ENCRYPTION_KEY',
                              Fernet.generate_key().decode('ascii'))
        self.enabled.start();self.key.start()
        self.addCleanup(self.enabled.stop);self.addCleanup(self.key.stop)

    def payload(self):
        return {'choice':'declared','items':[{'name':'Яйца','kind':'allergy'}],
                'consent':True,'consent_version':self.m.FOOD_ALLERGY_CONSENT_VERSION}

    def test_without_key_or_reviewed_flag_sensitive_storage_fails_closed(self):
        with patch.object(self.m,'FOOD_ALLERGY_PROCESSING_ENABLED',False):
            self.assertFalse(self.m.food_allergy_ready())
            self.assertEqual(self.m.food_allergy_state(777)['choice'],'unknown')
            with self.assertRaises(ValueError):
                self.m.food_allergy_write_in(MagicMock(),777,self.payload())
        with patch.object(self.m,'FORMIQ_HEALTH_ENCRYPTION_KEY','invalid'):
            self.assertFalse(self.m.food_allergy_ready())

    def test_consent_must_be_versioned_and_explicit(self):
        for amendment in [{'consent':False},{'consent_version':'old'},{'choice':'unknown'}]:
            raw={**self.payload(),**amendment}
            with self.assertRaises(ValueError):
                self.m.food_allergy_input(raw)
        self.assertEqual(self.m.food_allergy_input(self.payload())[0],'declared')

    def test_encrypted_columns_expose_no_plaintext(self):
        conn=MagicMock()
        self.m.food_allergy_write_in(conn,777,self.payload())
        args=conn.execute.call_args.args[1]
        self.assertEqual(args[0],777)
        self.assertEqual(args[1],'declared')
        self.assertIsInstance(args[2],bytes)
        self.assertNotIn('Яйца',str(args))
        self.assertIn(b'egg',self.m.food_allergy_cipher().decrypt(args[2]))

    def test_invalid_encryption_key_never_breaks_owner_food_journal(self):
        fake=MagicMock()
        fake.__enter__.return_value=fake
        fake.execute.return_value.fetchone.return_value=(
            'declared',b'bad encrypted bytes',self.m.FOOD_ALLERGY_CONSENT_VERSION,
            datetime.now(timezone.utc))
        with patch.object(self.m,'db',return_value=fake):
            state=self.m.food_allergy_state(777)
        self.assertEqual(state['choice'],'unknown')
        self.assertFalse(state['recommendations_allowed'])
        self.assertIn('не удалось прочитать',state['warning'])
        self.assertNotIn('bad encrypted bytes',str(state))

    def test_api_requires_telegram_authentication(self):
        for action in ('food_allergy_save','food_allergy_revoke',
                       'food_allergy_check'):
            with self.subTest(action=action):
                with patch.object(self.m,'mini_auth',return_value=None):
                    response=self.client.post('/mini/api',json={'action':action})
                self.assertEqual(response.status_code,401)

    def test_not_consented_state_blocks_ai_nutrition_before_model_call(self):
        with patch.object(self.m,'food_allergy_state',return_value={
            'choice':'unknown','recommendations_allowed':False}):
            with self.assertRaisesRegex(ValueError,'ограничения'):
                self.m.food_allergy_recommendation_gate(777)
        with patch.object(self.m,'food_allergy_state',return_value={
            'choice':'declared','recommendations_allowed':True}):
            with self.assertRaisesRegex(ValueError,'проверенного состава'):
                self.m.food_allergy_recommendation_gate(777)

    def test_client_cannot_claim_verified_and_inject_allowed_product(self):
        with patch.object(self.m,'has_agreement',return_value=True), \
             patch.object(self.m,'food_allergy_state',return_value={
                 'choice':'declared','recommendations_allowed':True,
                 'items':normalise_restrictions([{'name':'Яйца','kind':'allergy'}])}):
            result=self.m.food_allergy_check(777,{'candidate':evidence(['рис'])})
        self.assertEqual(result['result']['status'],'needs_review')


if __name__=='__main__':
    unittest.main()
