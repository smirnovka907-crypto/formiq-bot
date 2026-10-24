"""Regression guards against accidental production wiring in the test Blueprint."""
import copy
from pathlib import Path
import unittest

import yaml
from scripts.validate_android_test_blueprint import check_isolation


class AndroidTestBlueprintTests(unittest.TestCase):
    def setUp(self):
        self.config = yaml.safe_load((Path(__file__).resolve().parents[1]
                                     / 'render.android-test.yaml').read_text())

    def test_checked_in_blueprint_is_isolated(self):
        check_isolation(self.config)

    def test_paid_kirill_variant_is_explicit_and_cannot_be_confused_with_free(self):
        paid = yaml.safe_load((Path(__file__).resolve().parents[1]
                               / 'render.android-test.kirill.yaml').read_text())
        check_isolation(paid, profile='kirill')
        with self.assertRaises(ValueError):
            check_isolation(paid)
        with self.assertRaises(ValueError):
            check_isolation(self.config, profile='kirill')

    def test_production_branch_or_direct_main_start_is_rejected(self):
        for key, value in (('branch', 'main'), ('startCommand', 'python main.py'),
                           ('autoDeployTrigger', 'commit'), ('plan', 'starter')):
            config = copy.deepcopy(self.config)
            config['services'][0][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                check_isolation(config)

    def test_database_reference_cannot_point_to_existing_production(self):
        for key in ('DATABASE_URL', 'FORMIQ_TEST_DB_HOST'):
            config = copy.deepcopy(self.config)
            entry = next(e for e in config['services'][0]['envVars'] if e['key'] == key)
            entry['fromDatabase']['name'] = 'production-database'
            with self.subTest(key=key), self.assertRaises(ValueError):
                check_isolation(config)

    def test_secrets_must_not_be_embedded_in_yaml(self):
        for key in ('TELEGRAM_BOT_TOKEN', 'FORMIQ_TEST_BOT_USERNAME'):
            config = copy.deepcopy(self.config)
            entry = next(e for e in config['services'][0]['envVars'] if e['key'] == key)
            entry['value'] = 'must-not-be-committed'
            with self.subTest(key=key), self.assertRaises(ValueError):
                check_isolation(config)

    def test_shared_environment_or_platform_identity_override_is_rejected(self):
        for entry in ({'fromGroup': 'production-secrets'},
                      {'key': 'RENDER_EXTERNAL_URL', 'value': 'https://formiq-bot.onrender.com'}):
            config = copy.deepcopy(self.config)
            config['services'][0]['envVars'].append(entry)
            with self.subTest(entry=entry), self.assertRaises(ValueError):
                check_isolation(config)


if __name__ == '__main__':
    unittest.main()
