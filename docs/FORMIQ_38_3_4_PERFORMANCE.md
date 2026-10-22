# FORMIQ 38.3.4 — performance release candidate

Base: main @ 9777e1face10fba113fe2acbd192fd70c9c88b96 (no reset, no force push).

## Root cause from Render logs
- Repeated state requests in the 21–22 second range.
- `valid_exercise(chat, key)` repeated `profile(chat)` and `health_profile(chat)` DB connections for each of approximately 95 exercises.
- Calendar initialization executed 4×training_days independent SQL INSERTs twice per state.

## Changes
- Preload profile, health, metrics and agreements once for state generation, passing them to validation.
- Filter the full exercise library in memory; still apply the same conservative restriction filter, plus declared equipment.
- Pass prefetched custom workouts and health records into `user_session` for pre-rendered plans.
- One conflict-safe SQL upsert statement for each schedule initialization, preserving manually rescheduled dates.
- Test fast query path, security filters, and batch upsert invariants.
- Bump server and Mini App visible version and asset cache keys to 38.3.4.

## Still required
- GitHub Actions pass for final SHA, Render deployment after approval and smoke tests.
- Real Android/iOS network timing; cannot guarantee p95 improvement from static analysis alone.
- Garmin/FatSecret business OAuth activation, comprehensive AI plan generation and 95-image media rights remain unimplemented.
