"""Offline tests. Run: python -m unittest discover -s tests -p 'test_integrations.py' -v"""
from datetime import date
from decimal import Decimal
from pathlib import Path
import importlib.util
import unittest

ROOT = Path(__file__).resolve().parents[1]


def module(name):
    path = ROOT / "integrations" / (name + ".py")
    spec = importlib.util.spec_from_file_location("integrations_" + name, path)
    result = importlib.util.module_from_spec(spec)
    import sys
    sys.modules[spec.name] = result
    spec.loader.exec_module(result)
    return result


class IntegrationTests(unittest.TestCase):
    def test_fatsecret_oauth_signature_deterministic(self):
        f = module("fatsecret")
        kwargs = dict(consumer_key="a", consumer_secret="b", token="c", token_secret="d",
                      extra={"format": "json", "date": "19000"}, nonce="known", timestamp=123456789)
        a = f.signed_params("GET", f.FOOD_ENTRIES_URL, **kwargs)
        b = f.signed_params("GET", f.FOOD_ENTRIES_URL, **kwargs)
        self.assertEqual(a["oauth_signature"], b["oauth_signature"])
        self.assertNotIn("oauth_token_secret", a)
        self.assertIn("oauth_signature", a)
        with self.assertRaises(ValueError):
            f.signed_params("POST", "http://insecure.local", "a", "b")

    def test_diary_normalization(self):
        f = module("fatsecret")
        sample = {"food_entries": {"food_entry": [
            {"food_entry_id": "1", "food_entry_name": "Breakfast", "calories": "150",
             "protein": "8.5", "fat": "4", "carbohydrate": "21"},
            {"food_entry_id": "2", "food_entry_name": "Lunch", "calories": "320",
             "protein": "20", "fat": "12", "carbohydrate": "33"},
            {"food_entry_id": "2", "food_entry_name": "Lunch", "calories": "320",
             "protein": "20", "fat": "12", "carbohydrate": "33"}]}}
        normalized = f.normalize_diary(sample)
        self.assertEqual(len(normalized["entries"]), 2)
        self.assertEqual(normalized["calories_kcal"], Decimal("470"))
        self.assertEqual(normalized["protein_g"], Decimal("28.5"))
        self.assertEqual(f.normalize_diary({})["entries"], [])
        with self.assertRaises(ValueError):
            f.normalize_diary({"food_entries": {"food_entry": [
                {"food_entry_id": "4", "calories": "-1"}]}})

    def test_garmin_import_and_idempotency(self):
        g = module("garmin")
        sample = {"dailies": [
            {"userId": "tester", "summaryId": "d1", "calendarDate": "2026-10-22",
             "steps": 7000, "restingHeartRateInBeatsPerMinute": 58},
            {"userId": "tester", "summaryId": "d1", "calendarDate": "2026-10-22",
             "steps": 7000}],
            "activities": [{"userId": "tester", "summaryId": "a1",
                            "durationInSeconds": 1800, "activityType": "running"}]}
        output = g.normalize_garmin_webhook(sample, expected_user_id="tester")
        self.assertEqual(len(output), 2)
        self.assertEqual(output[0]["steps"], 7000)
        self.assertIsNone(output[0]["total_daily_calories_kcal"])
        self.assertIsNone(output[1]["total_daily_calories_kcal"])
        self.assertEqual(output[1]["duration_seconds"], 1800)
        self.assertEqual(len({g.stable_identity(x) for x in output}), 2)
        energy=g.normalize_garmin_webhook({"dailies":[{
            "userId":"tester","summaryId":"energy","calendarDate":"2026-10-22",
            "activeKilocalories":500,"totalKilocalories":2100,
            "bmrKilocalories":1600,"bodyBatteryChargedValue":48}]},
            expected_user_id="tester")[0]
        self.assertEqual(energy["active_calories_kcal"],500)
        self.assertEqual(energy["total_daily_calories_kcal"],2100)
        self.assertEqual(energy["resting_calories_kcal"],1600)
        self.assertEqual(energy["body_battery_charged"],48)
        with self.assertRaises(PermissionError):
            g.normalize_garmin_webhook(sample, expected_user_id="someone-else")
        with self.assertRaises(ValueError):
            g.normalize_garmin_webhook({"dailies": [{"userId": "tester", "steps": -1,
                                                     "summaryId": "bad"}]})

    def test_garmin_rejects_malformed_dates_and_float_overflow(self):
        g=module('garmin')
        with self.assertRaises(ValueError):
            g.normalize_garmin_webhook({'dailies':[{
                'userId':'tester','summaryId':'bad-long-date',
                'calendarDate':'2026-10-25-injected','steps':1000}]},
                expected_user_id='tester')
        with self.assertRaises(ValueError):
            g.normalize_garmin_webhook({'dailies':[{
                'userId':'tester','summaryId':'X'*81,
                'calendarDate':'2026-10-25','steps':1000}]},
                expected_user_id='tester')
        with self.assertRaises(ValueError):
            g.normalize_garmin_webhook({'dailies':[{
                'userId':'X'*81,'summaryId':'test',
                'calendarDate':'2026-10-25','steps':1000}]})

        for date_string in ('2026-02-30','2026/10/18','2026-10-1'):
            with self.assertRaises(ValueError):
                g.normalize_garmin_webhook({'dailies':[{
                    'userId':'tester','summaryId':'bad-date',
                    'calendarDate':date_string,'steps':1000}]},
                    expected_user_id='tester')
        with self.assertRaises(ValueError):
            g.normalize_garmin_webhook({'dailies':[{
                'userId':'tester','summaryId':'huge',
                'calendarDate':'2026-10-25','activeKilocalories':'1e10000'}]},
                expected_user_id='tester')

    def test_catalog_food_search_scales_only_verified_grams(self):
        f=module("fatsecret")
        food={"foods_search":{"food":[{
            "food_id":"1042","food_name":"Овсянка сухая","food_type":"Generic",
            "servings":{"serving":[{"serving_id":"27","serving_description":"100 g",
                "metric_serving_amount":"100","metric_serving_unit":"g",
                "calories":"380","protein":"13","fat":"7","carbohydrate":"67"}]}
        }]}}
        choices=f.normalize_catalog_search(food)
        self.assertEqual(choices[0]["food_id"],"1042")
        self.assertEqual(choices[0]["servings"][0]["per_serving"]["kcal"],380)
        serving=food["foods_search"]["food"][0]["servings"]["serving"][0]
        result=f.scale_verified_serving(serving,70)
        self.assertEqual(result["kcal"],Decimal("266.00"))
        self.assertEqual(result["protein_g"],Decimal("9.10"))
        self.assertIsNone(f.scale_verified_serving({**serving,"metric_serving_unit":"ml"},70))
        self.assertIsNone(f.scale_verified_serving({**serving,"protein":None},70))
        self.assertIsNone(f.scale_verified_serving(serving,-1))
        with self.assertRaises(ValueError):
            f.FatSecretCatalogClient("","").get_token()
        with self.assertRaises(ValueError):
            f.FatSecretCatalogClient("id","secret").search("oats","")

    def test_catalog_requires_manual_food_selection(self):
        f=module("fatsecret")
        p={"foods_search":{"food":[
            {"food_id":"12","food_name":"Овсянка, сырая","servings":{}},
            {"food_id":"13","food_name":"Овсянка, сваренная","servings":{}}
        ]}}
        found=f.normalize_catalog_search(p)
        self.assertEqual(len(found),2)
        self.assertNotEqual(found[0]["food_id"],found[1]["food_id"])
        self.assertEqual(found[0]["servings"],[])
        self.assertEqual(found[1]["servings"],[])
        with self.assertRaises(ValueError):
            f.normalize_catalog_search({"foods_search":{"food":[{"food_name":"без id"}]}})

    def test_import_does_not_require_secrets(self):
        module("fatsecret")
        module("garmin")


if __name__ == "__main__":
    unittest.main()
