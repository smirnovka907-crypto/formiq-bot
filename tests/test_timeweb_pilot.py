"""Issue #35: synthetic release, credential and WSGI isolation checks."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock

from scripts import timeweb_pilot, timeweb_release

ROOT = Path(__file__).resolve().parents[1]
A, B = "a"*40, "b"*40

class TimewebPilotTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        for sha in (A,B):
            dest = self.root/"releases"/sha
            dest.mkdir(parents=True)
            (dest/".formiq-release-sha").write_text(sha)

    def test_success_and_idempotency(self):
        restart = Mock()
        healthy = Mock(return_value=True)
        self.assertTrue(timeweb_release.switch_release(self.root,A,restart,healthy)["changed"])
        self.assertFalse(timeweb_release.switch_release(self.root,A,restart,healthy)["changed"])
        self.assertEqual(restart.call_count,1)
        timeweb_release.switch_release(self.root,B,restart,healthy)
        self.assertEqual(os.readlink(self.root/"current"),"releases/"+B)

    def test_health_failure_rollback(self):
        timeweb_release.switch_release(self.root,A,lambda:None,lambda _:True)
        checks=[]
        def health(sha):
            checks.append(sha)
            return sha==A
        with self.assertRaisesRegex(RuntimeError,"prior release restored"):
            timeweb_release.switch_release(self.root,B,lambda:None,health)
        self.assertEqual(checks,[B,A])
        self.assertEqual(os.readlink(self.root/"current"),"releases/"+A)

    def test_restart_failure_rollback(self):
        timeweb_release.switch_release(self.root,A,lambda:None,lambda _:True)
        count=iter((True,False))
        def restart():
            if next(count):
                raise OSError("synthetic restart fails")
        with self.assertRaisesRegex(RuntimeError,"prior release restored"):
            timeweb_release.switch_release(self.root,B,restart,lambda _:True)
        self.assertEqual(os.readlink(self.root/"current"),"releases/"+A)

    def test_unhealthy_rollback_not_reported_success(self):
        timeweb_release.switch_release(self.root,A,lambda:None,lambda _:True)
        with self.assertRaisesRegex(RuntimeError,"Rollback failed"):
            timeweb_release.switch_release(self.root,B,lambda:None,lambda _:False)

    def test_first_release_failure(self):
        with self.assertRaisesRegex(RuntimeError,"no previous version"):
            timeweb_release.switch_release(self.root,B,lambda:None,lambda _:False)
        self.assertFalse((self.root/"current").exists())

    def test_invalid_sha_marker_and_links_fail_closed(self):
        for sha in ("", "abc", "../escape", "A"*40):
            with self.subTest(sha=sha), self.assertRaises(ValueError):
                timeweb_release.require_release(self.root,sha)
        (self.root/"releases"/B/".formiq-release-sha").write_text(A)
        with self.assertRaises(ValueError):
            timeweb_release.switch_release(self.root,B,lambda:None,lambda _:True)
        (self.root/"current").symlink_to("/etc")
        with self.assertRaises(ValueError):
            timeweb_release.switch_release(self.root,A,lambda:None,lambda _:True)

    def test_dryrun_rejects_secret_environment(self):
        timeweb_pilot.refuse_runtime_credentials({})
        for key in timeweb_pilot.DENIED:
            with self.subTest(key=key),self.assertRaises(ValueError):
                timeweb_pilot.refuse_runtime_credentials({key:"synthetic"})
        env={k:v for k,v in os.environ.items() if k not in timeweb_release.DENIED}
        env["DATABASE_URL"]="synthetic"
        proc=subprocess.run([sys.executable,str(ROOT/"scripts/timeweb_release.py"),"simulate"],
                            cwd=ROOT,env=env,text=True,capture_output=True)
        self.assertNotEqual(proc.returncode,0)
        self.assertNotIn("synthetic",proc.stderr)

    def test_only_allowlisted_package_files(self):
        timeweb_pilot.inspect_package(["main.py","web/v5-live.js"])
        for item in (".env",".env.local","../x","/etc/passwd","db.sql",
                     "secrets/ssh.key","backup.fiqenc",".git/config"):
            with self.subTest(item=item),self.assertRaises(ValueError):
                timeweb_pilot.inspect_package([item])

    def test_pilot_cannot_use_live_activation(self):
        env={k:v for k,v in os.environ.items()
             if k!="FORMIQ_TIMEWEB_REAL_DEPLOY_ENABLED"}
        proc=subprocess.run([sys.executable,str(ROOT/"scripts/timeweb_release.py"),
                             "activate","--root",str(self.root),"--sha",A,"--live"],
                            cwd=ROOT,env=env,capture_output=True)
        self.assertNotEqual(proc.returncode,0)
        self.assertFalse((self.root/"current").exists())

    def test_wsgi_import_with_disconnected_synthetic_env(self):
        env={k:v for k,v in os.environ.items() if k not in
             timeweb_pilot.DENIED+("FORMIQ_RUNTIME_ROLE","RENDER_EXTERNAL_URL")}
        env.update(TELEGRAM_BOT_TOKEN="000000:offline_dummy",
                   DATABASE_URL="postgresql://test:test@127.0.0.1:5432/offline",
                   FORMIQ_RUNTIME_ROLE="timeweb-web",
                   RENDER_EXTERNAL_URL="https://formiq.test.invalid")
        code = """
from unittest.mock import patch
import socket, psycopg, telebot
with patch.object(socket.socket,'connect',side_effect=AssertionError('network')), \
     patch.object(psycopg,'connect',side_effect=AssertionError('database')), \
     patch.object(telebot.TeleBot,'set_webhook',side_effect=AssertionError('webhook')), \
     patch.object(telebot.TeleBot,'set_my_description',side_effect=AssertionError('branding')):
    import formiq_wsgi
    assert formiq_wsgi.application.test_client().get('/__timeweb_release_health').status_code==503
print('WSGI import isolated')
"""
        run=subprocess.run([sys.executable,"-c",code],cwd=ROOT,env=env,
                           capture_output=True,text=True,timeout=35)
        self.assertEqual(run.returncode,0,run.stdout+run.stderr)

    def test_wsgi_refuses_old_render_database(self):
        env={k:v for k,v in os.environ.items() if k not in timeweb_pilot.DENIED}
        env.update(TELEGRAM_BOT_TOKEN="000000:offline_dummy",
                   DATABASE_URL="postgresql://fake:fake@legacy-db.render.com:5432/offline",
                   FORMIQ_RUNTIME_ROLE="timeweb-web",
                   RENDER_EXTERNAL_URL="https://formiq.test.invalid")
        run=subprocess.run([sys.executable,"-c","import formiq_wsgi"],
                           env=env,cwd=ROOT,capture_output=True,text=True)
        self.assertNotEqual(run.returncode,0)
        self.assertIn("cannot connect to existing Render",run.stderr)

    def test_real_health_probe_requires_release_and_database(self):
        from unittest.mock import patch
        class Reply:
            status=200
            def __init__(self, body): self.body=body
            def __enter__(self): return self
            def __exit__(self, *_): return False
            def read(self, _): return self.body
        with patch.object(timeweb_release.urllib.request, 'urlopen',
                          side_effect=[Reply((A+'\n').encode()),
                                       Reply(b'DATABASE_READY\n')]) as http:
            self.assertTrue(timeweb_release.live_health(A))
            self.assertEqual(http.call_count, 2)
            self.assertIn('/__timeweb_db_health', http.call_args.args[0])
        with patch.object(timeweb_release.urllib.request, 'urlopen',
                          side_effect=lambda u, **kw:
                              Reply((A+'\n').encode()) if '__timeweb_release_' in u
                              else Reply(b'database unavailable')) as http:
            self.assertFalse(timeweb_release.live_health(A))

    def test_windows_launcher_never_accepts_secret_in_command_arguments(self):
        script=(ROOT/'scripts/FORMIQ_Backup_Windows.ps1').read_text()
        cmd=(ROOT/'scripts/FORMIQ_Backup_Windows.cmd').read_text()
        self.assertIn('Find-Python',script)
        self.assertIn('Find-Postgres18',script)
        self.assertIn('Ensure-No-Stored-Secrets',script)
        self.assertIn('FORMIQ-private-backups',script)
        self.assertIn('formiq_restore',script)
        self.assertIn('formiq_pg_restore_audit.py',script)
        self.assertIn('FORMIQ_Backup_Windows.ps1',cmd)
        self.assertNotIn('set PGPASSWORD=',cmd)
        self.assertNotIn('TELEGRAM_BOT_TOKEN=',cmd)

    def test_workflow_is_readonly_and_offline(self):
        text=(ROOT/".github/workflows/timeweb-pilot.yml").read_text()
        for fragment in ("pull_request:","contents: read","concurrency:",
                         "python scripts/timeweb_pilot.py --check",
                         "python scripts/timeweb_release.py simulate"):
            self.assertIn(fragment,text)
        for forbidden in ("pull_request_target","secrets.","ssh ","scp "):
            self.assertNotIn(forbidden,text)
        self.assertTrue(timeweb_pilot.static_entrypoint_check())

if __name__=="__main__":
    unittest.main()
