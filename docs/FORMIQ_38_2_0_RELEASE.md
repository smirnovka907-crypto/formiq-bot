# FORMIQ 38.2.0 — release acceptance log

Source base: main commit b853604a58dc67b06c78616aec590c3bd8c7d82f (38.1.4).

## Implemented in this release candidate
- Manual cardio entries merged into workout history, with owner-scoped detail lookup.
- Natural workout labels: «Ноги и пресс», «Спина и плечи», «Всё тело», «Кардио и подвижность».
- Gym recovery sessions include meaningful cardio plus accessory movements, not a 10-minute machine visit.
- Home equipment text field with opt-in Yandex classification and explicit user review.
- Additive table profile_equipment, without deletion or modification of historical workouts.
- Equipment-aware exercise variants (bodyweight fallback when equipment absent).
- Two DEMO access levels labelled FORMIQ Coach and FORMIQ 360, no payment processing.
- AI coach available in Coach test level; 360 integrations not misrepresented as connected.
- Regression tests and browser asset version 38.2.0.

## Not complete (DO NOT CLAIM otherwise)
- Real Garmin OAuth connection requires approved business developer access.
- FatSecret sync requires app credentials, callback registration and user authorization.
- Full AI-generated, safety-validated multiweek plan pipeline, and comprehensive performance acceptance are not completed.
- Complete 95-exercise licensed photo library and final selected branding require approval.
- No subscription payments are enabled and prices are not final.

## Required before promoting this candidate
- GitHub Actions checks passing on release branch.
- Render production DB schema/data backups before any substantial later migrations.
- Explicit main ref SHA lease / no history rewriting.
- Confirm new Render deployment has status live.
- Mobile end-to-end smoke checks, particularly onboarding form and cardio history, before claiming 9+/10.
