"""Validate the isolated test Blueprint; never contact Render resource APIs."""
import argparse
import json
from pathlib import Path
import urllib.request

import yaml

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_URL = 'https://render.com/schema/render.yaml.json'
BRANCH = 'fix/v5-native-onboarding-fullscreen-20261023'


def require(condition, message):
    if not condition:
        raise ValueError(message)


def check_isolation(config, profile='free'):
    require(isinstance(config, dict), 'Blueprint must be an object')
    require(set(config) == {'previews', 'databases', 'services'}, 'Unexpected top-level resources')
    require(config['previews'] == {'generation': 'off'}, 'Automatic previews must be disabled')
    require(len(config['services']) == len(config['databases']) == 1,
            'Exactly one new test service and database are required')
    service, database = config['services'][0], config['databases'][0]
    require(service['name'].startswith('formiq-android-test-'), 'Expected a test service name')
    require(database['name'].startswith('formiq-android-test-db-'), 'Expected a test database name')
    require(database['databaseName'].startswith('formiq_android_test_'), 'Expected a test database')
    require(database['user'].startswith('formiq_android_test'), 'Expected a dedicated database user')
    require(service['branch'] == BRANCH, 'Test service must use the existing PR branch')
    require(service['repo'] == 'https://github.com/smirnovka907-crypto/formiq-bot',
            'Unexpected source repository')
    require(service['type'] == 'web' and service['runtime'] == 'python', 'Expected a Python web service')
    require(profile in ('free', 'kirill'), 'Unknown test Blueprint profile')
    expected_web, expected_db = ('free', 'free') if profile == 'free' else ('0.5c-512mb', '0.1c-256mb')
    require((service['plan'], database['plan']) == (expected_web, expected_db),
            'Unexpected compute plans for the selected test profile')
    if profile == 'kirill':
        require(database.get('diskSizeGB') == 1, 'Use the reviewed 1 GB test database size')
        require(database.get('storageAutoscalingEnabled') is False, 'Disable automatic test database storage growth')
    require(service['region'] == database['region'], 'Test app and database must share a region')
    require(database['postgresMajorVersion'] == '16', 'Use the PostgreSQL version covered by CI')
    require(database['ipAllowList'] == [], 'Test PostgreSQL must have external access disabled')
    require(service['autoDeployTrigger'] == 'off', 'Automatic deployment must be disabled')
    require(service['startCommand'] == 'python scripts/run_android_test.py', 'Use the guarded test launcher')
    require(service['healthCheckPath'] == '/android-test-info', 'Use test readiness metadata')
    require(not service.get('domains'), 'Do not attach production/custom domains')
    entries = service['envVars']
    require(all('key' in entry and 'fromGroup' not in entry for entry in entries),
            'Do not import existing environment groups')
    env = {entry['key']: entry for entry in entries}
    require(len(env) == len(entries), 'Duplicate environment variables')
    require(not any(key.startswith('RENDER_') for key in env), 'Do not override platform identity variables')
    for key in ('TELEGRAM_BOT_TOKEN', 'FORMIQ_TEST_BOT_USERNAME'):
        require(env.get(key) == {'key': key, 'sync': False}, 'Provide test bot settings only in Render')
    for key, prop in (('DATABASE_URL', 'connectionString'), ('FORMIQ_TEST_DB_HOST', 'host')):
        require(env.get(key) == {'key': key, 'fromDatabase': {'name': database['name'], 'property': prop}},
                'Database settings must reference only the newly declared test database')
    for key, expected in (
            ('FORMIQ_ENV', 'android-test'), ('FORMIQ_TEST_DB_NAME', database['databaseName']),
            ('PYTHON_VERSION', '3.12.15'), ('FORMIQ_ADMIN_ID', '0'), ('FORMIQ_PREMIUM_ENFORCED', '0'),
            ('YANDEX_API_KEY', ''), ('YANDEX_FOLDER_ID', ''),
            ('FORMIQ_FEEDBACK_SHEETS_WEBHOOK', ''), ('FORMIQ_FEEDBACK_SHEETS_SECRET', '')):
        require(env.get(key) == {'key': key, 'value': expected}, 'Unsafe or missing test configuration: ' + key)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--offline', action='store_true', help='Check isolation only; skip online Render schema validation')
    parser.add_argument('--profile', choices=('free', 'kirill'), default='free',
                        help='Validate a prepared profile only; does not approve costs or create resources')
    args = parser.parse_args()
    filename = 'render.android-test.yaml' if args.profile == 'free' else 'render.android-test.kirill.yaml'
    config = yaml.safe_load((ROOT / filename).read_text())
    check_isolation(config, args.profile)
    if args.offline:
        print('PASS test Blueprint isolation; Render schema validation NOT run (offline)')
        return
    import jsonschema
    with urllib.request.urlopen(SCHEMA_URL, timeout=20) as response:
        schema = json.load(response)
    validator_type = jsonschema.validators.validator_for(schema)
    validator_type.check_schema(schema)
    errors = list(validator_type(schema).iter_errors(config))
    if errors:
        path = '/'.join(map(str, errors[0].absolute_path)) or '(root)'
        raise ValueError('Render schema rejected field path: ' + path)
    print('PASS test Blueprint isolation and current Render JSON Schema')


if __name__ == '__main__':
    main()
