"""Private local comparison of source PostgreSQL18 with an isolated restore.

Runs exclusively on owner's trusted computer, after a successful encrypted
pg_dump and restore. Never writes to production or prints user data or URLs.
Source comparison is a live approximation: concurrent writes can cause a
mismatch; fail closed rather than claim a validated snapshot.
"""
import getpass
import re
import subprocess
import sys

try:
    from scripts import formiq_pg_backup as backup
except ModuleNotFoundError:
    import formiq_pg_backup as backup


def psql_scalar(env, sql):
    binary = backup.check_client("psql")
    protected = env.copy()
    protected["PGOPTIONS"] = "-c default_transaction_read_only=on -c statement_timeout=45000"
    result = subprocess.run(
        [binary, "-X", "-q", "-A", "-t", "-v", "ON_ERROR_STOP=1",
         "-c", sql], env=protected, stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=70)
    if result.returncode:
        raise backup.BackupError("Read-only PostgreSQL audit query failed")
    try:
        return result.stdout.decode("utf-8").strip()
    except UnicodeDecodeError as exc:
        raise backup.BackupError("Invalid audit output") from None


def quote_ident(text):
    # Identifiers obtained from pg_catalog; never interpolate user input.
    if not isinstance(text, str) or not text or "\x00" in text:
        raise backup.BackupError("Unsafe PostgreSQL identifier")
    return '"' + text.replace('"', '""') + '"'


def take_snapshot(env):
    version = psql_scalar(env, "SELECT current_setting('server_version_num')")
    if not version.isdigit() or int(version) // 10000 != 18:
        raise backup.BackupError("Audit requires PostgreSQL 18")
    table_names = psql_scalar(env,
        "SELECT tablename FROM pg_catalog.pg_tables "
        "WHERE schemaname='public' ORDER BY tablename").splitlines()
    if not table_names:
        raise backup.BackupError("No application tables found: restore is incomplete")
    counts = {}
    for name in table_names:
        answer = psql_scalar(env, "SELECT COUNT(*) FROM public." + quote_ident(name))
        if not answer.isdigit():
            raise backup.BackupError("Invalid PostgreSQL table count")
        counts[name] = int(answer)
    # Including FK/PK/unique/check constraints, not their contents.
    constraints = psql_scalar(env,
        "SELECT conrelid::regclass::text || ':' || contype::text || ':' || conname "
        "FROM pg_catalog.pg_constraint WHERE connamespace='public'::regnamespace "
        "ORDER BY 1").splitlines()
    sequences = psql_scalar(env,
        "SELECT sequencename || '=' || COALESCE(last_value::text,'unavailable') "
        "FROM pg_catalog.pg_sequences WHERE schemaname='public' "
        "ORDER BY sequencename").splitlines()
    return counts, constraints, sequences


def check_orphans(env, tables):
    # These checks supplement restored FK constraints, including legacy tables
    # without an actual declared FK. All queries return only numeric counts.
    checks = (
        (("workout_items", "workouts"),
         "SELECT COUNT(*) FROM public.workout_items i LEFT JOIN public.workouts w "
         "ON w.id=i.workout_id WHERE w.id IS NULL"),
        (("workout_sets", "workouts"),
         "SELECT COUNT(*) FROM public.workout_sets s LEFT JOIN public.workouts w "
         "ON w.id=s.workout_id WHERE w.id IS NULL"),
        (("scheduled_sessions", "training_cycles"),
         "SELECT COUNT(*) FROM public.scheduled_sessions s "
         "LEFT JOIN public.training_cycles c ON c.id=s.cycle_id WHERE c.id IS NULL"),
        (("manual_food_items", "manual_food_meals"),
         "SELECT COUNT(*) FROM public.manual_food_items i "
         "LEFT JOIN public.manual_food_meals m ON m.id=i.meal_id WHERE m.id IS NULL"),
    )
    examined = 0
    for required, query in checks:
        if set(required).issubset(tables):
            amount = psql_scalar(env, query)
            if amount != "0":
                raise backup.BackupError("Broken history relations in restored database")
            examined += 1
    return examined


def reconcile(source_url, local_url):
    # Validation MUST precede *any* connection. Restore never points to Render.
    source = backup.postgres_env(source_url, restore=False)
    local = backup.postgres_env(local_url, restore=True)
    a = take_snapshot(source)
    b = take_snapshot(local)
    if a != b:
        raise backup.BackupError(
            "Backup counts/schema/ID sequences differ from live source; "
            "possible concurrent writes; do not approve cutover")
    checked = check_orphans(local, b[0])
    return {"tables": len(b[0]), "constraints": len(b[1]),
            "sequences": len(b[2]), "relations_checked": checked}


def main():
    try:
        backup.check_client("psql")
        print("AUDIT_IS_READ_ONLY; local restore must already have succeeded.")
        source_url = getpass.getpass("Render EXTERNAL database URL (hidden): ")
        local_url = getpass.getpass("LOCAL *_restore database URL (hidden): ")
        result = reconcile(source_url, local_url)
        print("LOCAL_RESTORE_RECONCILED; counts, constraints and sequences match")
        print("Tables:", result["tables"], "constraints:", result["constraints"],
              "ID sequences:", result["sequences"],
              "history relationships:", result["relations_checked"])
        print("NOTE: this comparison is a live snapshot; obtain a write-frozen "
              "final backup for zero-loss cutover.")
        return 0
    except Exception:
        # No secrets, user-specific data, SQL result bodies or DSNs in errors.
        print("AUDIT_NO_GO: unable to verify full consistency (details withheld).",
              file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
