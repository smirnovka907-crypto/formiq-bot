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
        self.assertEqual(output[1]["duration_seconds"], 1800)
        self.assertEqual(len({g.stable_identity(x) for x in output}), 2)
        with self.assertRaises(PermissionError):
            g.normalize_garmin_webhook(sample, expected_user_id="someone-else")
        with self.assertRaises(ValueError):
            g.normalize_garmin_webhook({"dailies": [{"userId": "tester", "steps": -1,
                                                     "summaryId": "bad"}]})

    def test_import_does_not_require_secrets(self):
        module("fatsecret")
        module("garmin")


if __name__ == "__main__":
    unittest.main()
