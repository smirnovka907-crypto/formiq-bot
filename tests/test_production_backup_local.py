"""Offline security regressions for the LOCAL encrypted PostgreSQL backup utility.

Uses dummy archive bytes and no production database or credentials.
"""
from io import BytesIO
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from cryptography.exceptions import InvalidTag
from scripts import formiq_pg_backup as backup


PASS = 'a-long-private-passphrase-for-offline-backup-tests'


class FakeDump:
    def __init__(self, *args, **kwargs):
        self.argv = args[0]
        self.env = kwargs['env']
        self.stdout = BytesIO(b'PGDMP\x01 TEST-only fake contents not user records' * 10)
        self.returncode = 0

    def wait(self, timeout=None):
        return self.returncode

    def poll(self):
        return self.returncode


class BackupSafetyTests(unittest.TestCase):
    def test_no_secret_credentials_in_pg_dump_argv(self):
        url = 'postgresql://formiq_db_user:SECRET_TEST@something.oregon-postgres.render.com/formiq_db?sslmode=require'
        env = backup.postgres_env(url)
        self.assertEqual(env['PGDATABASE'], 'formiq_db')
        self.assertEqual(env['PGSSLMODE'], 'require')
        self.assertIn('read_only=on', env['PGOPTIONS'])
        self.assertEqual(env['PGPASSWORD'], 'SECRET_TEST')
        self.assertNotIn('DATABASE_URL', env)
        self.assertNotIn('TELEGRAM_BOT_TOKEN', env)

    def test_reject_unrelated_source_and_any_remote_restore(self):
        rejected = (
            'postgresql://user:pw@example.com/formiq_db',
            'postgresql://user:pw@render.com/formiq_other',
            'http://user:pw@something.render.com/formiq_db',
        )
        for uri in rejected:
            with self.subTest(uri=uri):
                with self.assertRaises(backup.BackupError):
                    backup.postgres_env(uri)
        for uri in (
            'postgresql://user:pw@something.render.com/formiq_restore',
            'postgresql://user:pw@localhost/formiq_db',
            'postgresql://user:pw@localhost/formiq_data',
        ):
            with self.subTest(uri=uri):
                with self.assertRaises(backup.BackupError):
                    backup.postgres_env(uri, restore=True)
        env = backup.postgres_env(
            'postgresql://user:pw@127.0.0.1:5432/formiq_restore', restore=True)
        self.assertEqual(env['PGSSLMODE'], 'disable')
        self.assertNotIn('read_only=on', env['PGOPTIONS'])

    def test_encryption_roundtrip_and_tamper_detection(self):
        original = b'SYNTHETIC_PRIVATE_DATA_DO_NOT_LOG' * 300
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'archive.fiqenc'
            with path.open('wb') as out:
                amount = backup.encrypt_stream(BytesIO(original), out, PASS)
            self.assertEqual(amount, len(original))
            ciphertext = path.read_bytes()
            self.assertTrue(ciphertext.startswith(backup.MAGIC))
            self.assertNotIn(original[:25], ciphertext)
            out = BytesIO()
            backup.decrypt_stream(path, out, PASS)
            self.assertEqual(out.getvalue(), original)
            with self.assertRaises(InvalidTag):
                backup.decrypt_stream(path, BytesIO(), PASS + 'mistake')
            tampered = bytearray(ciphertext)
            tampered[-19] ^= 0x04
            path.write_bytes(tampered)
            with self.assertRaises(InvalidTag):
                backup.decrypt_stream(path, BytesIO(), PASS)

    def test_do_not_backup_into_source_tree(self):
        with self.assertRaises(backup.BackupError):
            backup.private_directory(backup.ROOT / 'backups')

    def test_dummy_pg_dump_encrypted_and_verified_without_private_data_logs(self):
        uri = ('postgresql://formiq_db_user:SECRET_TEST@'
               'something.oregon-postgres.render.com/formiq_db')
        fake = FakeDump()
        with tempfile.TemporaryDirectory() as folder:
            with patch.object(backup, 'check_client', side_effect=lambda cmd: cmd):
                with patch.object(backup.subprocess, 'Popen', return_value=fake):
                    with patch.object(backup, 'validate_archive') as validated:
                        filename, checksum = backup.create_backup(folder, uri, PASS)
                self.assertTrue(filename.exists())
                self.assertTrue(filename.name.endswith('.fiqenc'))
                self.assertEqual(len(checksum), 64)
                self.assertEqual(len(list(Path(folder).glob('*.partial'))), 0)
                self.assertEqual(fake.argv,
                    ['pg_dump', '--format=custom', '--no-owner', '--no-acl'])
                self.assertNotIn('SECRET_TEST', str(fake.argv))
                self.assertNotIn('SECRET_TEST', filename.name)
                self.assertEqual(fake.env['PGPASSWORD'], 'SECRET_TEST')
                validated.assert_called_once()
                recovered = BytesIO()
                backup.decrypt_stream(filename, recovered, PASS)
                self.assertTrue(recovered.getvalue().startswith(b'PGDMP'))

    def test_backup_failure_removes_partial_file(self):
        uri = 'postgresql://user:secret@somewhere.render.com/formiq_db'
        fake = FakeDump()
        fake.returncode = 1
        with tempfile.TemporaryDirectory() as folder:
            with patch.object(backup, 'check_client', side_effect=lambda cmd: cmd):
                with patch.object(backup.subprocess, 'Popen', return_value=fake):
                    with self.assertRaises(backup.BackupError):
                        backup.create_backup(folder, uri, PASS)
            self.assertEqual(list(Path(folder).iterdir()), [])

    def test_short_or_wrong_header_is_not_accepted(self):
        with tempfile.TemporaryDirectory() as folder:
            filename = Path(folder) / 'broken.fiqenc'
            filename.write_bytes(b'not a backup')
            with self.assertRaises(backup.BackupError):
                backup.decrypt_stream(filename, BytesIO(), PASS)
            filename.write_bytes(b'X' * 200)
            with self.assertRaises(backup.BackupError):
                backup.decrypt_stream(filename, BytesIO(), PASS)


if __name__ == '__main__':
    unittest.main()
