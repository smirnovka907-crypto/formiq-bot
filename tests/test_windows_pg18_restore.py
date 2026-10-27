"""End-to-end encrypted pg_dump -> authenticated .fiqenc -> pg_restore on
DISPOSABLE PostgreSQL 18 only. No Render/Telegram credentials or I/O.
Uses the existing CI PostgreSQL 18 docker service and fake connection URLs.
"""
import os
from pathlib import Path
import re
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import uuid

from scripts import formiq_pg_backup as backup
from scripts import formiq_pg_restore_audit as audit


class SyntheticBackupRestorePG18(unittest.TestCase):
    def test_full_encrypted_backup_restore_and_reconciliation(self):
        container = os.getenv("FORMIQ_TEST_PG_DOCKER_CONTAINER", "")
        test_url = os.getenv("FORMIQ_TEST_DATABASE_URL", "")
        if not container or not re.fullmatch(r"[0-9a-f]{12,64}", container):
            self.skipTest("Requires disposable PostgreSQL 18 CI Docker service")
        if not ("@localhost:5432/formiq_schedule_test" in test_url or
                "@127.0.0.1:5432/formiq_schedule_test" in test_url):
            self.skipTest("Refuses anything except the known disposable CI database")
        import psycopg
        from urllib.parse import urlsplit, unquote
        uri = urlsplit(test_url)
        password = unquote(uri.password or "")
        prefix = "fbackup_" + uuid.uuid4().hex[:9]
        source_name = prefix + "_source"
        target_name = prefix + "_restore"
        with psycopg.connect(test_url, autocommit=True) as conn:
            conn.execute('CREATE DATABASE "' + source_name + '"')
            conn.execute('CREATE DATABASE "' + target_name + '"')
        source_uri = test_url.rsplit("/", 1)[0] + "/" + source_name
        target_uri = test_url.rsplit("/", 1)[0] + "/" + target_name
        with psycopg.connect(source_uri, autocommit=True) as conn:
            conn.execute("CREATE TABLE profiles(chat_id BIGINT PRIMARY KEY, goal TEXT)")
            conn.execute("CREATE TABLE workouts(id BIGSERIAL PRIMARY KEY, "
                         "chat_id BIGINT REFERENCES profiles(chat_id), status TEXT)")
            conn.execute("CREATE TABLE workout_items(workout_id BIGINT REFERENCES workouts(id), position INT, PRIMARY KEY(workout_id,position))")
            conn.execute("CREATE TABLE workout_sets(id BIGSERIAL PRIMARY KEY, workout_id BIGINT REFERENCES workouts(id), weight_kg NUMERIC)")
            conn.execute("CREATE TABLE training_cycles(id BIGSERIAL PRIMARY KEY, chat_id BIGINT REFERENCES profiles(chat_id))")
            conn.execute("CREATE TABLE scheduled_sessions(id BIGSERIAL PRIMARY KEY, cycle_id BIGINT REFERENCES training_cycles(id))")
            conn.execute("INSERT INTO profiles VALUES(111, 'offline synthetic')")
            conn.execute("INSERT INTO workouts(chat_id,status) VALUES(111,'finished')")
            conn.execute("INSERT INTO workout_items VALUES(1,1)")
            conn.execute("INSERT INTO workout_sets(workout_id,weight_kg) VALUES(1,25.5)")
            conn.execute("INSERT INTO training_cycles(chat_id) VALUES(111)")
            conn.execute("INSERT INTO scheduled_sessions(cycle_id) VALUES(1)")
        # Real backup/restore functions are exercised, with PG18 commands
        # redirected to the disposable docker service only.
        with tempfile.TemporaryDirectory(prefix="formiq-ci-pg18-") as temp:
            binpath = {}
            for name in ("pg_dump", "pg_restore", "psql"):
                wrapper = Path(temp) / name
                if name == "pg_dump":
                    command = ("exec docker exec -i " + container +
                               " pg_dump -U formiq_test -d " + source_name + ' "$@"')
                elif name == "pg_restore":
                    command = ("exec docker exec -i " + container +
                               ' pg_restore -U formiq_test "$@"')
                else:
                    command = ("db=$PGDATABASE\n" +
                               'if [ "$db" = "formiq_db" ]; then db=' + source_name + '; fi\n' +
                               "exec docker exec -i -e PGDATABASE=$db " + container +
                               ' psql -U formiq_test "$@"')
                wrapper.write_text("#!/bin/sh\nset -eu\n" + command + "\n")
                wrapper.chmod(0o700)
                binpath[name] = str(wrapper)
            secret = "synthetic-test-key-no-user-data-here"
            fake_source = ("postgresql://formiq_test:synthetic@"
                           "fixture.oregon-postgres.render.com/formiq_db")
            local_target = ("postgresql://formiq_test:synthetic@"
                            "127.0.0.1:5432/" + target_name)
            with patch.object(backup,"check_client",side_effect=lambda name:binpath[name]):
                encrypted, digest = backup.create_backup(temp, fake_source, secret)
                self.assertEqual(len(digest),64)
                self.assertEqual(encrypted.suffix,".fiqenc")
                self.assertFalse(list(Path(temp).glob("*.partial")))
                backup.validate_archive(encrypted, secret)
                backup.restore_locally(encrypted, secret, local_target)
                stats = audit.reconcile(fake_source, local_target)
                self.assertEqual(stats["tables"],6)
                self.assertGreaterEqual(stats["relations_checked"],3)
                self.assertGreaterEqual(stats["sequences"],3)
                self.assertGreaterEqual(stats["constraints"],6)
            with psycopg.connect(target_uri) as conn:
                self.assertEqual(conn.execute("SELECT count(*) FROM profiles").fetchone()[0],1)
                self.assertEqual(conn.execute("SELECT count(*) FROM workout_sets").fetchone()[0],1)
                self.assertEqual(str(conn.execute("SELECT weight_kg FROM workout_sets").fetchone()[0]),"25.5")
            # Entire local test environment disappears with the disposable CI PG18.

if __name__ == "__main__":
    unittest.main()
