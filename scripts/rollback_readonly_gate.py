"""Fail-closed, read-only rollback compatibility audit on a restored TEST database.

This is deliberately NOT a rollback implementation and NOT proof that a
production backup exists. No production connection option is provided.
"""
import argparse
import json
import os
import sys
from urllib.parse import urlsplit


def inspect_legacy_rollback(conn):
    """Assess whether old main's scheduler would encounter V5 data.

    Calls SELECT only after making the current transaction READ ONLY.
    Never returns individual user IDs, rows, or counts.
    """
    conn.execute("SET TRANSACTION READ ONLY")
    conn.execute("SET LOCAL lock_timeout = '2s'")
    conn.execute("SET LOCAL statement_timeout = '10s'")

    tables = conn.execute(
        "SELECT to_regclass('profiles') IS NOT NULL, "
        "to_regclass('scheduled_sessions') IS NOT NULL"
    ).fetchone()
    if tables != (True, True):
        return {'status': 'blocked', 'reason': 'required_tables_missing'}

    columns = conn.execute("""
        SELECT
            EXISTS (
                SELECT 1 FROM pg_attribute
                WHERE attrelid = to_regclass('profiles')
                  AND attname = 'weekdays' AND NOT attisdropped
            ),
            EXISTS (
                SELECT 1 FROM pg_attribute
                WHERE attrelid = to_regclass('scheduled_sessions')
                  AND attname = 'schedule_state' AND NOT attisdropped
            )
    """).fetchone()
    if columns == (False, False):
        return {'status': 'legacy_schema', 'reason': 'no_v5_columns'}
    if columns != (True, True):
        return {'status': 'blocked', 'reason': 'partial_v5_schema'}

    flags = conn.execute("""
        SELECT EXISTS (SELECT 1 FROM profiles WHERE weekdays IS NOT NULL),
               EXISTS (SELECT 1 FROM scheduled_sessions
                      WHERE schedule_state IS NOT NULL)
    """).fetchone()
    if flags[0] or flags[1]:
        return {'status': 'blocked', 'reason': 'v5_schedule_data_present',
                'weekday_choices_present': bool(flags[0]),
                'schedule_states_present': bool(flags[1])}
    return {'status': 'candidate', 'reason': 'no_v5_schedule_markers'}


def validate_target(dsn):
    """Only isolated, deliberately named databases are eligible.

    The name check supplements (not replaces) infrastructure isolation and
    an operator review of the target. Production is called formiq_db.
    """
    if not dsn or not isinstance(dsn, str):
        raise ValueError('Missing isolated restore database URL')
    parsed = urlsplit(dsn)
    db_name = parsed.path.lstrip('/').split('?')[0]
    if (parsed.scheme not in ('postgres', 'postgresql')
            or not parsed.hostname
            or not db_name.endswith(('_test', '_restore'))
            or db_name == 'formiq_db'):
        raise ValueError('Only isolated *_test or *_restore databases are permitted')
    return db_name


def main(argv=None):
    parser = argparse.ArgumentParser(description='Read-only V5 rollback gate (restored copy only)')
    parser.add_argument('--dsn-env', default='FORMIQ_RESTORE_TEST_DATABASE_URL',
                        help='Name of environment variable containing ISOLATED DB URL')
    args = parser.parse_args(argv)
    if args.dsn_env in ('DATABASE_URL', 'FORMIQ_TEST_PRODUCTION_DATABASE_URL'):
        print('BLOCKED: application/production DSN cannot be used', file=sys.stderr)
        return 2
    dsn = os.environ.get(args.dsn_env, '')
    try:
        validate_target(dsn)
        import psycopg
        with psycopg.connect(
            dsn, connect_timeout=5,
            options='-c default_transaction_read_only=on -c statement_timeout=10000 '
                    '-c lock_timeout=2000'
        ) as conn:
            result = inspect_legacy_rollback(conn)
        print(json.dumps(result, sort_keys=True, ensure_ascii=False))
        # candidate does not imply a safe production rollback: it only means
        # no V5 markers were observed on this isolated snapshot.
        return 0 if result['status'] in ('candidate', 'legacy_schema') else 2
    except Exception:
        # Driver errors often embed DSNs. Never print the exception.
        print('BLOCKED: isolated database audit failed; no rollback approval', file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
