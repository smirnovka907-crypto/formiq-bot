-- Additive preparation only. Run against the intended database after backup
-- verification and schema review; this file has NOT been run in production.
BEGIN;
SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '30s';
ALTER TABLE profiles ADD COLUMN IF NOT EXISTS weekdays JSONB;
ALTER TABLE scheduled_sessions ADD COLUMN IF NOT EXISTS schedule_state
    TEXT CHECK (schedule_state IN ('auto','manual','retired'));
COMMIT;
