"""Android test launcher isolation checks; no network, credentials or real DB."""
import importlib.util
import io
import json
import logging
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from scripts import run_android_test as launch


def test_environment():
    return {
        'FORMIQ_ENV': 'android-test',
        'RENDER_SERVICE_NAME': 'formiq-android-test-pr15',
        'RENDER_EXTERNAL_URL': 'https://formiq-android-test-pr15.onrender.com',
        'RENDER_EXTERNAL_HOSTNAME': 'formiq-android-test-pr15.onrender.com',
        'RENDER_GIT_COMMIT': 'a' * 40,
        'FORMIQ_TEST_DB_HOST': 'dpg-isolated-test-a',
        'FORMIQ_TEST_DB_NAME': 'formiq_android_test_pr15',
        'DATABASE_URL': 'postgresql://test_user:TESTONLY_password@dpg-isolated-test-a/formiq_android_test_pr15',
        'FORMIQ_TEST_BOT_USERNAME': '@formiq_android_test_bot',
        'TELEGRAM_BOT_TOKEN': '111222333:TESTONLY_abcdefghijklmnopqrst',
        'PORT': '10000',
    }


class Response:
    def __init__(self, body):
        self.body = body
        self.headers = {}

    def get_data(self, as_text=False):
        return self.body if as_text else self.body.encode()

    def set_data(self, value):
        self.body = value


def fake_application(environment, events, identity=None):
    config = launch.validate_environment(environment)
    identity = identity or SimpleNamespace(id=config.bot_id, username=config.bot_username, is_bot=True)
    bot = Mock()
    bot.get_me.side_effect = lambda: (events.append('get_me'), identity)[1]
    bot.set_webhook.side_effect = lambda **kwargs: events.append('set_webhook')
    app = Mock()
    app.view_functions = {'formiq_wake': lambda: Response(
        '<a href="https://t.me/formiqcoachbot">Вернуться в FORMIQ</a>')}
    app.make_response.side_effect = lambda response: response
    app.add_url_rule.side_effect = lambda path, endpoint, view, **kw: app.view_functions.update({endpoint: view})
    app.run.side_effect = lambda **kwargs: events.append('run')
    return SimpleNamespace(TOKEN=environment['TELEGRAM_BOT_TOKEN'],
        DATABASE_URL=environment['DATABASE_URL'], BASE_URL=config.base_url, SECRET='TESTONLY_webhook_secret',
        BOT=bot, APP=app, LOG=Mock(), jsonify=lambda **kwargs: Response(json.dumps(kwargs)),
        init_db=Mock(side_effect=lambda: events.append('init_db')),
        replay_pending=Mock(side_effect=lambda: events.append('replay_pending')),
        configure_formiq_bot_profile=Mock(side_effect=lambda: events.append('configure_bot')))


class AndroidTestLaunchTests(unittest.TestCase):
    def setUp(self):
        self.env = test_environment()
        self.addCleanup(logging.setLogRecordFactory, logging.getLogRecordFactory())

    def assert_rejected_before_import(self, environment):
        loader = Mock()
        with self.assertRaises(launch.TestLaunchError) as error:
            launch.run(environment, application_loader=loader)
        loader.assert_not_called()
        self.assertNotIn(environment.get('TELEGRAM_BOT_TOKEN', 'missing-token'), str(error.exception))
        return str(error.exception)

    def test_valid_environment_is_explicit_and_credential_free(self):
        config = launch.validate_environment(self.env)
        self.assertEqual(config.bot_username, 'formiq_android_test_bot')
        self.assertEqual(config.database_name, 'formiq_android_test_pr15')
        self.assertEqual(config.source_sha, 'a' * 40)
        self.assertEqual(config.launch_url, 'https://t.me/formiq_android_test_bot?start=android_test')
        self.assertNotIn(self.env['TELEGRAM_BOT_TOKEN'], repr(config))
        self.assertNotIn('TESTONLY_password', repr(config))

    def test_wrong_environment_or_existing_service_is_rejected_before_import(self):
        for key, value in [('FORMIQ_ENV', 'production'), ('FORMIQ_ENV', ''),
                           ('RENDER_SERVICE_NAME', 'formiq-bot')]:
            with self.subTest(key=key, value=value):
                self.assert_rejected_before_import({**self.env, key: value})

    def test_production_or_untrusted_public_url_is_rejected_before_import(self):
        for value in ('https://formiq-bot.onrender.com',
                      'http://formiq-android-test-pr15.onrender.com',
                      'https://formiq-android-test.example.com',
                      'https://formiq-android-test-pr15.onrender.com/mini',
                      'https://user:password@formiq-android-test-pr15.onrender.com',
                      'https://formiq-android-test-pr15.onrender.com?next=production'):
            with self.subTest(url=value):
                self.assert_rejected_before_import({**self.env, 'RENDER_EXTERNAL_URL': value})
        self.assert_rejected_before_import({**self.env, 'RENDER_EXTERNAL_HOSTNAME': 'formiq-bot.onrender.com'})

    def test_wrong_database_host_name_and_query_override_are_rejected_before_import(self):
        for dsn in ('postgresql://u:password@dpg-production-a/formiq_android_test_pr15',
                    'postgresql://u:password@dpg-isolated-test-a/formiq_production',
                    self.env['DATABASE_URL'] + '?host=dpg-production-a',
                    self.env['DATABASE_URL'] + '?dbname=formiq_production',
                    self.env['DATABASE_URL'] + '?service=production',
                    'host=dpg-isolated-test-a dbname=formiq_android_test_pr15'):
            with self.subTest(dsn_kind=dsn.split('?')[-1] if '?' in dsn else 'uri'):
                self.assert_rejected_before_import({**self.env, 'DATABASE_URL': dsn})
        self.assert_rejected_before_import({**self.env, 'FORMIQ_TEST_DB_NAME': 'formiq_production'})

    def test_optional_tls_query_does_not_override_database_identity(self):
        config = launch.validate_environment({**self.env,
            'DATABASE_URL': self.env['DATABASE_URL'] + '?sslmode=require&connect_timeout=10'})
        self.assertEqual(config.database_host, 'dpg-isolated-test-a')

    def test_production_integrations_and_admin_are_rejected_before_import(self):
        for key in launch.INTEGRATION_KEYS:
            with self.subTest(key=key):
                error = self.assert_rejected_before_import({**self.env, key: 'TESTONLY_private_value'})
                self.assertNotIn('TESTONLY_private_value', error)
        self.assert_rejected_before_import({**self.env, 'FORMIQ_ADMIN_ID': '777'})
        self.assert_rejected_before_import({**self.env, 'FORMIQ_PREMIUM_ENFORCED': '1'})

    def test_missing_credentials_source_or_bot_identity_are_rejected_before_import(self):
        for key in ('TELEGRAM_BOT_TOKEN', 'DATABASE_URL', 'FORMIQ_TEST_DB_HOST',
                    'FORMIQ_TEST_DB_NAME', 'FORMIQ_TEST_BOT_USERNAME', 'RENDER_GIT_COMMIT'):
            with self.subTest(key=key):
                broken = dict(self.env)
                broken.pop(key)
                self.assert_rejected_before_import(broken)
        self.assert_rejected_before_import({**self.env, 'FORMIQ_TEST_BOT_USERNAME': 'formiqcoachbot'})
        self.assert_rejected_before_import({**self.env, 'RENDER_GIT_COMMIT': 'not-a-real-sha'})

    def test_wrong_or_production_token_identity_never_mutates_db_or_bot(self):
        for identity in (SimpleNamespace(id=111222333, username='formiqcoachbot', is_bot=True),
                         SimpleNamespace(id=111222333, username='other_test_bot', is_bot=True),
                         SimpleNamespace(id=999999999, username='formiq_android_test_bot', is_bot=True),
                         SimpleNamespace(id=111222333, username='formiq_android_test_bot', is_bot=False)):
            with self.subTest(username=identity.username, bot_id=identity.id):
                events = []
                module = fake_application(self.env, events, identity)
                with self.assertRaises(launch.TestLaunchError):
                    launch.run(self.env, application_loader=lambda: module)
                self.assertEqual(events, ['get_me'])
                module.init_db.assert_not_called()
                module.replay_pending.assert_not_called()
                module.configure_formiq_bot_profile.assert_not_called()
                module.BOT.set_webhook.assert_not_called()
                module.APP.run.assert_not_called()

    def test_bot_verification_failure_does_not_leak_secret_request_url(self):
        events = []
        module = fake_application(self.env, events)
        module.BOT.get_me.side_effect = RuntimeError('https://api.telegram.org/bot' +
            self.env['TELEGRAM_BOT_TOKEN'] + '/getMe')
        with self.assertRaises(launch.TestLaunchError) as error:
            launch.run(self.env, application_loader=lambda: module)
        self.assertNotIn(self.env['TELEGRAM_BOT_TOKEN'], str(error.exception))
        self.assertTrue(error.exception.__suppress_context__)
        module.init_db.assert_not_called()
        module.BOT.set_webhook.assert_not_called()

    def test_stale_loaded_module_is_rejected_before_remote_calls(self):
        for key in ('TOKEN', 'DATABASE_URL', 'BASE_URL'):
            with self.subTest(key=key):
                events = []
                module = fake_application(self.env, events)
                setattr(module, key, 'TESTONLY_wrong_loaded_setting')
                with self.assertRaises(launch.TestLaunchError):
                    launch.run(self.env, application_loader=lambda: module)
                self.assertEqual(events, [])

    def test_bot_identity_is_verified_before_all_mutations(self):
        events = []
        module = fake_application(self.env, events)
        launch.run(self.env, application_loader=lambda: module)
        self.assertEqual(events, ['get_me', 'init_db', 'replay_pending',
                                  'configure_bot', 'set_webhook', 'run'])
        module.BOT.set_webhook.assert_called_once_with(
            url=self.env['RENDER_EXTERNAL_URL'] + '/telegram-webhook',
            secret_token='TESTONLY_webhook_secret', drop_pending_updates=False)
        module.APP.run.assert_called_once_with(host='0.0.0.0', port=10000, debug=False)

    def test_metadata_and_wake_link_contain_only_verified_test_identity(self):
        events = []
        module = fake_application(self.env, events)
        launch.run(self.env, application_loader=lambda: module)
        info_response = module.APP.view_functions['android_test_info']()
        info = json.loads(info_response.body)
        self.assertEqual(info['environment'], 'android-test')
        self.assertEqual(info['baseline_sha'], launch.BASELINE_SHA)
        self.assertEqual(info['source_sha'], self.env['RENDER_GIT_COMMIT'])
        self.assertTrue(info['telegram_bot_verified'])
        self.assertEqual(info_response.headers['Cache-Control'], 'no-store')
        for value in (self.env['TELEGRAM_BOT_TOKEN'], self.env['DATABASE_URL'], 'TESTONLY_password'):
            self.assertNotIn(value, info_response.body)
        wake = module.APP.view_functions['formiq_wake']()
        self.assertIn(info['launch_url'], wake.body)
        self.assertNotIn('formiqcoachbot', wake.body)

    def test_log_redactor_covers_request_url_and_exception_text(self):
        buffer = io.StringIO()
        handler = logging.StreamHandler(buffer)
        handler.addFilter(launch.SecretRedactor(self.env))
        logger = logging.getLogger('formiq_android_test_redaction')
        logger.handlers = [handler]
        logger.propagate = False
        logger.setLevel(logging.ERROR)
        self.addCleanup(lambda: setattr(logger, 'handlers', []))
        try:
            raise RuntimeError('connection failed: ' + self.env['DATABASE_URL'])
        except RuntimeError:
            logger.exception('request https://api.telegram.org/bot%s/getMe', self.env['TELEGRAM_BOT_TOKEN'])
        output = buffer.getvalue()
        self.assertIn('[redacted]', output)
        self.assertNotIn(self.env['TELEGRAM_BOT_TOKEN'], output)
        self.assertNotIn('TESTONLY_password', output)

    def test_launch_redacts_own_and_future_handlers_before_application_import(self):
        events = []
        module = fake_application(self.env, events)
        buffer = io.StringIO()
        logger = logging.getLogger('formiq_android_test_future_handler')
        original = (list(logger.handlers), logger.propagate, logger.level)
        self.addCleanup(lambda: (setattr(logger, 'handlers', original[0]),
            setattr(logger, 'propagate', original[1]), logger.setLevel(original[2])))
        previous_factory = logging.getLogRecordFactory()

        def existing_factory(*args, **kwargs):
            record = previous_factory(*args, **kwargs)
            record.stack_info = 'Stack with password=TESTONLY_password'
            if not record.exc_info:
                record.exc_text = 'Cached request failure: ' + self.env['TELEGRAM_BOT_TOKEN']
            return record

        logging.setLogRecordFactory(existing_factory)

        def import_application():
            # Model TeleBot creating its own non-propagating handler on import.
            logger.handlers = [logging.StreamHandler(buffer)]
            logger.propagate = False
            logger.setLevel(logging.ERROR)
            try:
                raise RuntimeError('DSN=' + self.env['DATABASE_URL'])
            except RuntimeError:
                logger.exception('request https://api.telegram.org/bot%s/getMe',
                                 self.env['TELEGRAM_BOT_TOKEN'])
            return module

        launch.run(self.env, application_loader=import_application)
        # A second handler created after startup must receive sanitized records too.
        later_buffer = io.StringIO()
        logger.handlers = [logging.StreamHandler(later_buffer)]
        try:
            raise RuntimeError('password=' + 'TESTONLY_password')
        except RuntimeError:
            logger.exception('token=%s', self.env['TELEGRAM_BOT_TOKEN'])
        logger.error('cached exception token=%s', self.env['TELEGRAM_BOT_TOKEN'])
        for output in (buffer.getvalue(), later_buffer.getvalue()):
            self.assertIn('[redacted]', output)
            self.assertIn('Traceback', output)
            self.assertNotIn(self.env['TELEGRAM_BOT_TOKEN'], output)
            self.assertNotIn(self.env['DATABASE_URL'], output)
            self.assertNotIn('TESTONLY_password', output)


@unittest.skipUnless(importlib.util.find_spec('flask'), 'Flask is installed by the complete CI runtime')
class AndroidTestRouteIntegrationTests(unittest.TestCase):
    def test_real_wsgi_metadata_and_wake_never_redirect_to_production(self):
        from flask import Flask, jsonify, make_response
        app = Flask(__name__)
        app.add_url_rule('/wake', 'formiq_wake', lambda: make_response(
            '<a href="https://t.me/formiqcoachbot">FORMIQ</a>'))
        module = SimpleNamespace(APP=app, jsonify=jsonify)
        launch.install_test_routes(module, launch.validate_environment(test_environment()))
        client = app.test_client()
        info = client.get('/android-test-info')
        self.assertEqual(info.status_code, 200)
        self.assertEqual(info.json['environment'], 'android-test')
        self.assertEqual(info.headers['Cache-Control'], 'no-store')
        wake = client.get('/wake')
        self.assertEqual(wake.status_code, 200)
        self.assertNotIn(b'formiqcoachbot', wake.data)
        self.assertIn(b't.me/formiq_android_test_bot?start=android_test', wake.data)


if __name__ == '__main__':
    unittest.main()
