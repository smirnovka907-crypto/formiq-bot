# Weekday storage and rollback

This PR adds two nullable columns: `profiles.weekdays` (JSONB, Monday=0 through
Sunday=6) and `scheduled_sessions.schedule_state` (`auto`, `manual`, `retired`,
or NULL for legacy rows). Existing JSONB columns hold health or exercise data and
are not reused. No table, workout, set, weight, cardio entry, or user is deleted.

`migrations/20261023_weekday_schedule.sql` is an idempotent, additive preparation
script with bounded lock/statement timeouts. It has not been executed against
production. `init_db()` repeats the same `ADD COLUMN IF NOT EXISTS` statements.
There is no startup backfill or rewrite of existing schedules. Review and verify
the actual backup/restore path before applying a production release.

The new application requires these columns before serving requests. The previous
application tolerates their presence. Apply the additive schema before switching
application code; do not run a new worker against an unprepared old schema.

## Preservation rules

- Missing/null weekdays retain legacy count-based scheduling. An older client
  cannot silently erase a saved weekday choice; incompatible frequency-only edits
  are rejected and require the current form.
- Frequency/weekday-only edits reuse the unexpired cycle and its calendar row
  identities. Other profile changes retain the existing new-cycle behavior.
- Reconciliation runs in the onboarding transaction under the same per-user
  advisory lock as generation, workout start and manual rescheduling. Callers
  reread the profile after acquiring that lock.
- Only rows strictly later than both the old and new timezone's local date may
  change. Any linked workout, regardless of status, protects its calendar row.
  Existing past and today's dates do not move. Calendar reads do not re-run edits.
- On first weekday adoption, a legacy future row is automatic only if its date
  exactly matches the old count-based baseline. Ambiguous rows stay pinned.
  Legacy manual intent that coincides with the old automatic date cannot be
  reconstructed; new manual reschedules explicitly record `manual`, even when
  moving back to the old baseline.
- A reduction marks excess future automatic rows `retired`; it does not delete
  them. Retired rows remain hidden as time advances. A later increase may reuse
  their identities only while they and their target dates remain in the future.
  Manual or ambiguous rows survive, so a transition cycle can contain extra
  explicitly preserved sessions. A target that is already today or in the past
  retires its future automatic slot; it neither pulls it backwards nor leaves a
  workout on a weekday the user no longer selected.
- A transition week can also contain fewer newly selected days: a past, today's,
  or linked slot keeps its identity and is not duplicated on a new weekday. The
  complete new cadence applies to untouched future weeks; no catch-up workouts
  are invented to replace protected sessions.
- Selected weekdays use civil `date` arithmetic. DST does not shift a training
  day by adding elapsed hours. The four-week cycle remains 28 local dates.

## Non-destructive rollback

There is deliberately no `DROP COLUMN`, bulk schedule reset, or reverse migration.
Rolling application code back must leave both columns and all row identities in
place. Code rollback alone does not undo data or restore the previous dates.

The old application does not understand `retired` slots or saved weekdays. Before
rollback, suspend scheduling writes (or use a compatible hotfix that preserves
these fields) and inspect the affected users/cycles. Do not resume an old planner
until that compatibility check is complete: it can otherwise expose retired rows
or create count-based slots. Do not restore an old database backup over current
user data. If restoring is necessary, first restore into an isolated database and
validate a targeted recovery plan separately.

Automated PostgreSQL tests use only the opt-in test database, never production.
Live backup availability, an actual restore rehearsal, and Telegram verification
remain separate release gates; this document does not claim those checks passed.
