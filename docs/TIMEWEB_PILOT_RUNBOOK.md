# FORMIQ / Issue #35 — Timeweb VPS + GitHub Actions OFFLINE pilot

Status: **design and disposable CI simulation only**. Existing Telegram bot,
Render Live, PostgreSQL production and GitHub main are NOT changed.
Owner authorized only this Draft PR; NO purchase, merge, SSH or deployment.

## What the pilot actually does

- Existing Render startup stays \`python main.py\`: schema initialization,
  pending update replay, branding and webhook setup still happen only there.
- A separate \`formiq_wsgi:application\` import provides Flask WSGI without
  invoking any of the above. It requires role \`timeweb-web\`, an explicit
  non-Render HTTPS URL, and runtime credentials **only on a future VPS**.
  It does NOT register a Telegram webhook. Running WSGI alone does not
  initialize or migrate database schema, nor replay queued Telegram updates.
- \`timeweb-pilot.yml\` is **read-only, PR/manual-only**. It runs no SSH,
  remote commands, production tokens, Docker pushes, artifact uploads,
  database migrations or deployments. It tests Python, JS, systemd syntax,
  credential refusal, offline archive generation and an atomic SHA switch
  with rollback on a temporary directory. It does not run on pushes to main.
- \`scripts/timeweb-pilot.sh\` generates an immutable allowlisted source
  package plus a Git SHA marker **inside a disposable CI runner**. No
  user data or private secrets enter the archive. SHA256 is printed for a
  synthetic package only; the archive is not uploaded or deployed.
- \`scripts/timeweb_release.py simulate\` demonstrates
  \`releases/<sha> -> current\` using an atomic symlink swap. On a failed
  exact-SHA healthcheck, it restores the previous link, restarts and
  checks the restored version; an unsuccessful rollback fails loudly.
  OS file lock prevents concurrent publication. No real unit is touched.

## Planned future deployment, NOT part of this authorization

A subsequent authorized PR (and separate explicit owner-approved release) must
wire a protected GitHub Environment. Public-repository environments support
required reviewers, but these controls are **not currently configured**.
Never put SSH keys, app credentials or PostgreSQL DSNs in this public repo
or its logs/artifacts. Do not use \`pull_request_target\` with untrusted code.

Future process:
1. Obtain written price, payment and *specific segment* 152-FZ legal
   confirmation for Timeweb VPS and separate **private PostgreSQL 18** in the
   same Russian private network; define operator responsibilities, special
   health-data consents, agreements and independent encrypted offsite backup.
2. Before purchasing/migration obtain an authenticated **real** production
   PostgreSQL encrypted dump, checksum and successful **isolated** restore;
   reconcile table counts, history, owner isolation and sequences. Current
   Render Free PG expires on **2026-11-19 at 22:50 MSK**.
3. After explicit purchase consent an administrator sets up Linux,
   updates, firewall (public 443 and optionally 80 for ACME, SSH only from
   approved source addresses), a deploy-only user with a pinned public SSH
   key, \`formiq\` service user and restricted sudoers allowing only
   \`systemctl restart formiq-web.service\`. No unrestricted root SSH.
   Store \`/etc/formiq/web.env\` readable only by service account; don't
   check it into Git. VPS binds gunicorn to 127.0.0.1:8080, nginx HTTPS
   reverse-proxies traffic; private PG never requires a public address.
4. Install pinned compatible Python environment per release, verifying a
   specific immutable commit SHA and checksum of an authenticated artifact.
   Separately approve/rehearse SQL migrations on restored PG first. Startup,
   merge and systemd restart **never** run implicit schema creation.
5. The **future** deployment workflow (not present now) must depend on
   exact SHA CI, approved protected environment and a one-time owner
   merge+release authorization. Concurrency serializes deployments.
   Use dedicated restricted SSH; stage to \`/srv/formiq/releases/<sha>\`,
   check marker and dependency install, then run the guarded
   \`timeweb_release.py activate --root /srv/formiq --sha <sha> --live\`.
   This invokes only restricted \`systemctl restart formiq-web.service\`,
   probes \`http://127.0.0.1:8080/__timeweb_release_health\` for the exact
   SHA and automatically restores the prior symlink and rechecks it
   if the new version fails. Never use the pilot's temporary archive as
   an authenticated production release without checksum/signature policy.
6. Only after a fresh verified cutover backup/restore and separate explicit
   authorization switch exactly one Telegram webhook and Mini App URL.
   Keep old Render write path fenced to prevent dual processing. Actual
   rollback **after new writes** must restore data consistency before
   reverting traffic; an application symlink rollback alone does not
   reverse database migrations or cross-host writes. Keep Render unchanged
   until the transition is accepted.
7. Add monitoring: TLS expiry, HTTP 5xx/p95, running WSGI SHA, DB
   availability/connections, disk limits, backups/restore drills, login
   audit and recovery contacts. No health records/tokens in logs.

## Current NO-GO and limitations

- No Timeweb subscription, VPS, private PG, real SSH credentials, managed
  database, DNS, TLS or instance exist as part of this pilot.
- No production encrypted backup or real restore is confirmed.
- No legal confirmation of the actual 152-FZ configuration or medical data
  processing agreement is available; ordinary VPS is NOT proof.
- GitHub Environment required-reviewer configuration is a future manual
  repository setting, not implemented here. GitHub public repos support it,
  subject to plan and repository settings:
  https://docs.github.com/en/actions/how-tos/deploy/configure-and-manage-deployments/manage-environments
- Import and rollback tests are *synthetic*. Without a real VPS and
  private PG, actual firewall, HTTPS, service restart, restore, provider
  access, performance and automatic update cannot be verified in practice.
- Do not infer authorization for production from a green CI or Draft PR.

## Initial owner setup checklist (only after a separate decision)

Approve vendor and itemized total; confirm legal 152-FZ/health-data scope;
pay for resources if explicitly authorized; configure DNS/HTTPS; set up
Linux accounts/firewall; provision private PG and separate backup storage;
put runtime credentials in protected host environment; create restricted SSH
access and GitHub Environment required reviewer settings; conduct real
restore/reconciliation; approve the specific merge, deploy and Telegram cutover.

**Rollback plan for pilot:** delete the isolated feature branch if rejected.
Published main, Render, Telegram and production PostgreSQL remain untouched.
