"""Fail-closed rollback gate tests; no network and no production credentials."""
import unittest
from unittest.mock import patch

from scripts.rollback_readonly_gate import (
    inspect_legacy_rollback, main, validate_target,
)


class CursorResult:
    def __init__(self, row):
        self.row = row

    def fetchone(self):
        return self.row


class FakeReadOnlyConnection:
    def __init__(self, tables=(True, True), columns=(True, True),
                 markers=(False, False)):
        self.responses = [tables, columns, markers]
        self.statements = []

    def execute(self, statement):
        self.statements.append(statement)
        if statement.lstrip().startswith('SELECT'):
            return CursorResult(self.responses.pop(0))
        return CursorResult(None)


class RollbackGateTests(unittest.TestCase):
    def test_clean_schema_only_candidacy_not_approval(self):
        db = FakeReadOnlyConnection()
        result = inspect_legacy_rollback(db)
        self.assertEqual(result['status'], 'candidate')
        self.assertEqual(result['reason'], 'no_v5_schedule_markers')
        self.assertEqual(db.statements[0], 'SET TRANSACTION READ ONLY')
        self.assertTrue(all(s.lstrip().startswith(('SET ', 'SELECT'))
                            for s in db.statements))

    def test_new_states_and_weekdays_fail_closed_without_user_rows(self):
        for markers in ((True, False), (False, True), (True, True)):
            with self.subTest(markers=markers):
                db = FakeReadOnlyConnection(markers=markers)
                result = inspect_legacy_rollback(db)
                self.assertEqual(result['status'], 'blocked')
                self.assertEqual(result['reason'], 'v5_schedule_data_present')
                self.assertEqual(result['weekday_choices_present'], markers[0])
                self.assertEqual(result['schedule_states_present'], markers[1])
                self.assertNotIn('chat_id', str(result))

    def test_missing_and_partial_schema_fail_closed(self):
        for tables, columns, reason in (
                ((False, True), (True, True), 'required_tables_missing'),
                ((True, True), (True, False), 'partial_v5_schema'),
                ((True, True), (False, True), 'partial_v5_schema')):
            with self.subTest(reason=reason):
                result = inspect_legacy_rollback(
                    FakeReadOnlyConnection(tables=tables, columns=columns))
                self.assertEqual(result, {'status': 'blocked', 'reason': reason})

    def test_legacy_schema_report_is_not_marked_v5_ready(self):
        result = inspect_legacy_rollback(
            FakeReadOnlyConnection(columns=(False, False)))
        self.assertEqual(result, {
            'status': 'legacy_schema', 'reason': 'no_v5_columns'})

    def test_only_explicit_isolated_database_names(self):
        self.assertEqual(
            validate_target('postgresql://user:secret@localhost:5432/formiq_schedule_test'),
            'formiq_schedule_test')
        self.assertEqual(
            validate_target('postgresql://u:p@isolated.example/formiq_restore'),
            'formiq_restore')
        for dsn in (
                '', 'postgresql://u:p@localhost/formiq_db',
                'postgresql://u:p@localhost/formiq',
                'postgresql://u:p@localhost/formiq_db_testevil',
                'postgresql://u:p@localhost/',
                'https://u:p@localhost/formiq_schedule_test'):
            with self.subTest(dsn=dsn):
                with self.assertRaises(ValueError):
                    validate_target(dsn)

    def test_cli_rejects_application_dsn_even_if_present(self):
        with patch.dict('os.environ', {'DATABASE_URL':
                       'postgresql://user:secret@localhost/formiq_schedule_test'}):
            self.assertEqual(main(['--dsn-env', 'DATABASE_URL']), 2)

    def test_cli_error_does_not_echo_password(self):
        with patch.dict('os.environ', {'FORMIQ_RESTORE_TEST_DATABASE_URL':
                       'postgresql://user:SECRET_NEVER_PRINT@localhost/formiq_db'}):
            self.assertEqual(main([]), 2)


if __name__ == '__main__':
    unittest.main()
