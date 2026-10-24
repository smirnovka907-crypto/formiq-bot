"""Start an isolated Android test deployment; never fall back to production.

This entry point intentionally uses only the standard library until all static
environment checks pass. Run it instead of main.py on the separate test service.
"""
import importlib
import logging
import os
from pathlib import Path
import re
import sys
import traceback
from dataclasses import dataclass
from urllib.parse import parse_qsl, quote, unquote, urlsplit


BASELINE_SHA = 'f2f6009a2804c159eb64846575e133966bb3c8d9'
PRODUCTION_HOST = 'formiq-bot.onrender.com'
PRODUCTION_BOT = 'formiqcoachbot'
INTEGRATION_KEYS = (
    'YANDEX_API_KEY', 'YANDEX_FOLDER_ID',
    'FORMIQ_FEEDBACK_SHEETS_WEBHOOK', 'FORMIQ_FEEDBACK_SHEETS_SECRET',
)


class TestLaunchError(RuntimeError):
    """A safe-to-log validation failure, with no credential values."""


@dataclass(frozen=True)
class TestLaunchConfig:
    base_url: str
    service_name: str
    bot_username: str
    bot_id: int
    database_host: str
    database_name: str
    source_sha: str
    port: int

    @property
    def launch_url(self):
        return 'https://t.me/' + self.bot_username + '?start=android_test'


def validate_environment(environment=None):
    env = os.environ if environment is None else environment

    def required(key):
        value = env.get(key, '')
        if not isinstance(value, str) or not value or value != value.strip():
            raise TestLaunchError('Set ' + key + ' explicitly without surrounding whitespace')
        return value

    if required('FORMIQ_ENV') != 'android-test':
        raise TestLaunchError('FORMIQ_ENV must be android-test')
    service = required('RENDER_SERVICE_NAME')
    if not re.fullmatch(r'formiq-android-test(?:-[a-z0-9]+)*', service):
        raise TestLaunchError('RENDER_SERVICE_NAME must use the formiq-android-test prefix')
    base = required('RENDER_EXTERNAL_URL').rstrip('/')
    try:
        public = urlsplit(base)
        public_host = public.hostname
        valid_url = (public.scheme == 'https' and public_host
                     and public_host != PRODUCTION_HOST
                     and public_host.startswith('formiq-android-test')
                     and public_host.endswith('.onrender.com')
                     and public.username is None and public.password is None
                     and public.port in (None, 443) and not public.path
                     and not public.query and not public.fragment)
    except ValueError:
        valid_url = False
    if not valid_url:
        raise TestLaunchError('RENDER_EXTERNAL_URL must be the separate HTTPS Android test service')
    injected_host = env.get('RENDER_EXTERNAL_HOSTNAME')
    if injected_host and injected_host != public_host:
        raise TestLaunchError('RENDER_EXTERNAL_HOSTNAME does not match RENDER_EXTERNAL_URL')

    expected_name = required('FORMIQ_TEST_DB_NAME')
    expected_host = required('FORMIQ_TEST_DB_HOST').lower()
    if not re.fullmatch(r'formiq_android_test(?:_[a-z0-9]+)*', expected_name):
        raise TestLaunchError('FORMIQ_TEST_DB_NAME must use the formiq_android_test prefix')
    dsn = required('DATABASE_URL')
    try:
        database = urlsplit(dsn)
        query = parse_qsl(database.query, keep_blank_values=True, strict_parsing=True)
        valid_database = (database.scheme in ('postgres', 'postgresql')
                          and database.hostname == expected_host
                          and unquote(database.path.lstrip('/')) == expected_name
                          and database.username and database.password
                          and database.port in (None, 5432)
                          and not database.fragment
                          and all(key in ('sslmode', 'connect_timeout') for key, _ in query))
    except ValueError:
        valid_database = False
    if not valid_database:
        raise TestLaunchError('DATABASE_URL must match the independently bound test database host and name')

    username = required('FORMIQ_TEST_BOT_USERNAME').removeprefix('@').lower()
    if not re.fullmatch(r'[a-z][a-z0-9_]{1,28}bot', username) or username == PRODUCTION_BOT:
        raise TestLaunchError('FORMIQ_TEST_BOT_USERNAME must identify a separate test bot')
    token = required('TELEGRAM_BOT_TOKEN')
    token_match = re.fullmatch(r'([1-9][0-9]*):[A-Za-z0-9_-]{12,}', token)
    if not token_match:
        raise TestLaunchError('Set a valid TELEGRAM_BOT_TOKEN for the separate test bot')
    for key in INTEGRATION_KEYS:
        if env.get(key, '').strip():
            raise TestLaunchError('External production integrations must be unset: ' + key)
    if env.get('FORMIQ_ADMIN_ID', '0').strip() not in ('', '0'):
        raise TestLaunchError('FORMIQ_ADMIN_ID must be unset or 0 in the Android test environment')
    if env.get('FORMIQ_PREMIUM_ENFORCED', '0') != '0':
        raise TestLaunchError('FORMIQ_PREMIUM_ENFORCED must be 0 for the Android test')
    source_sha = required('RENDER_GIT_COMMIT').lower()
    if not re.fullmatch(r'[a-f0-9]{40}', source_sha):
        raise TestLaunchError('RENDER_GIT_COMMIT must contain the actual deployed commit SHA')
    try:
        port = int(env.get('PORT', '10000'))
    except (ValueError, TypeError):
        raise TestLaunchError('PORT must be a valid TCP port') from None
    if not 1 <= port <= 65535:
        raise TestLaunchError('PORT must be a valid TCP port')
    return TestLaunchConfig(base, service, username, int(token_match.group(1)),
                            expected_host, expected_name, source_sha, port)


class SecretRedactor(logging.Filter):
    """Keep runtime request failures from printing Telegram/DB credentials."""
    def __init__(self, environment):
        super().__init__()
        token, dsn = environment.get('TELEGRAM_BOT_TOKEN', ''), environment.get('DATABASE_URL', '')
        password = unquote(urlsplit(dsn).password or '')
        self.secrets = tuple(value for value in (token, quote(token, safe=''), dsn, password) if value)

    def redact(self, value):
        for secret in self.secrets:
            value = value.replace(secret, '[redacted]')
        return value

    def filter(self, record):
        record.msg = self.redact(record.getMessage())
        record.args = ()
        if record.exc_info:
            record.exc_text = self.redact(''.join(traceback.format_exception(*record.exc_info)))
            record.exc_info = None
        elif record.exc_text:
            record.exc_text = self.redact(record.exc_text)
        if record.stack_info:
            record.stack_info = self.redact(record.stack_info)
        return True


def install_secret_redaction(redactor):
    # Records are sanitized before dispatch to any handler, including TeleBot's
    # own handler and handlers installed after application import.
    previous_factory = logging.getLogRecordFactory()

    def redacting_factory(*args, **kwargs):
        record = previous_factory(*args, **kwargs)
        redactor.filter(record)
        return record

    logging.setLogRecordFactory(redacting_factory)


def load_application():
    # Executing scripts/run_android_test.py puts scripts/ on sys.path, not the repo.
    root = str(Path(__file__).resolve().parents[1])
    if root not in sys.path:
        sys.path.insert(0, root)
    return importlib.import_module('main')


def verify_application_settings(application, config, environment):
    if (application.TOKEN != environment['TELEGRAM_BOT_TOKEN']
            or application.DATABASE_URL != environment['DATABASE_URL']
            or application.BASE_URL != config.base_url):
        raise TestLaunchError('Loaded application settings do not match the validated test environment')


def verify_bot_identity(bot, config):
    try:
        identity = bot.get_me()  # Read-only: no webhook or profile change is made yet.
    except Exception:
        raise TestLaunchError('Could not verify the separate test bot using Telegram getMe') from None
    actual_username = (getattr(identity, 'username', None) or '').lower()
    if (actual_username != config.bot_username or actual_username == PRODUCTION_BOT
            or type(getattr(identity, 'id', None)) is not int or identity.id != config.bot_id
            or getattr(identity, 'is_bot', False) is not True):
        raise TestLaunchError('Telegram getMe does not match the independently configured test bot')


def install_test_routes(application, config):
    original_wake = application.APP.view_functions['formiq_wake']

    def test_wake():
        response = application.APP.make_response(original_wake())
        response.set_data(response.get_data(as_text=True).replace(
            'https://t.me/' + PRODUCTION_BOT, config.launch_url))
        response.headers['Cache-Control'] = 'no-store'
        response.headers['Referrer-Policy'] = 'no-referrer'
        return response

    def test_info():
        response = application.jsonify(environment='android-test', service=config.service_name,
            source_sha=config.source_sha, baseline_sha=BASELINE_SHA,
            bot_username=config.bot_username, launch_url=config.launch_url,
            telegram_bot_verified=True)
        response.headers['Cache-Control'] = 'no-store'
        response.headers['Referrer-Policy'] = 'no-referrer'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        return response

    application.APP.view_functions['formiq_wake'] = test_wake
    application.APP.add_url_rule('/android-test-info', 'android_test_info', test_info, methods=['GET'])


def run(environment=None, application_loader=None):
    env = os.environ if environment is None else environment
    config = validate_environment(env)
    install_secret_redaction(SecretRedactor(env))
    application = (application_loader or load_application)()
    verify_application_settings(application, config, env)
    verify_bot_identity(application.BOT, config)
    install_test_routes(application, config)
    # Static database binding and read-only bot identity checks precede mutations.
    application.init_db()
    application.replay_pending()
    application.configure_formiq_bot_profile()
    application.BOT.set_webhook(url=config.base_url + '/telegram-webhook',
        secret_token=application.SECRET, drop_pending_updates=False)
    application.LOG.info('Android test verified: source_sha=%s', config.source_sha)
    application.APP.run(host='0.0.0.0', port=config.port, debug=False)


if __name__ == '__main__':
    try:
        run()
    except Exception as error:
        # Do not print arbitrary request/connection exceptions: they may contain credentials.
        detail = str(error) if isinstance(error, TestLaunchError) else type(error).__name__
        print('FORMIQ Android test stopped: ' + detail, file=sys.stderr)
        raise SystemExit(1) from None
