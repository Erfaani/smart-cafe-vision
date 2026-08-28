# Security review (Phase 10)

A manual review of the authentication, authorization, data-handling and
deployment surface, done as part of production hardening. Not a
penetration test and not a substitute for one before a deployment that
matters — see "What this review did not cover" at the bottom.

---

## What was checked

**Authentication and sessions.** JWT via `djangorestframework-simplejwt`,
30-minute access tokens, 7-day refresh tokens with rotation, Argon2 password
hashing (chosen over PBKDF2's default iteration count specifically because
café servers are often small mini PCs — see `PASSWORD_HASHERS` in
`config/settings/base.py`), a 10-character minimum password length plus
Django's standard validator set, and login throttled to 10/min
(`ScopedRateThrottle`). Tokens live in httpOnly cookies set by the Next.js
server, never in JavaScript-reachable storage — see
docs/architecture.md's "Tokens live in httpOnly cookies" section.

**Authorization.** Every viewset scopes its queryset by
`request.user.cafe_id` unless the caller is a superuser; this is asserted by
a test in every app that has café-scoped data (`test_..._is_scoped_to_the_callers_cafe`,
repeated across `apps/cameras`, `apps/sessions`, `apps/tables`,
`apps/analytics`, `apps/tenants`). The one exception, `apps.cameras.models.Zone`
and `TableZone` having no direct `cafe` field, is a deliberate, documented
choice (see docs/development.md's Tenancy convention), not a scoping gap —
both still resolve to a café through `camera__cafe_id`.

**Injection.** No `shell=True`, `os.system`, `eval`, or `exec` anywhere in
the backend or worker. All database access is through the Django ORM — no
raw SQL. RTSP URLs are parsed with `urllib.parse`, never concatenated into a
shell command. The frontend has no `dangerouslySetInnerHTML` anywhere — React
escapes all rendered content by default, and nothing opts out of that.

**Secrets.** RTSP passwords encrypted at rest with Fernet
(`CREDENTIALS_ENCRYPTION_KEY`); the AI worker's service token compared with
`hmac.compare_digest` (constant-time) rather than `==`; `.env` is
git-ignored and `.env.example` ships only placeholder values;
`RedactSecretsFilter` (`apps/core/logging.py`) scrubs credential-shaped
key/value pairs and RTSP URLs from every log line before it is formatted, on
every handler. `production.py` refuses to boot on the default/placeholder
secret key, and refuses a key short enough to weaken the JWT signature
(RFC 7518 §3.2).

**Transport and headers.** `X-Frame-Options: DENY`,
`X-Content-Type-Options: nosniff`, `Referrer-Policy: same-origin` on every
response. TLS enforcement (`SECURE_SSL_REDIRECT`, HSTS, secure cookies) is
opt-in via `BEHIND_TLS_PROXY`, deliberately not forced on: many installs are
a LAN appliance with no certificate, and forcing secure cookies there would
mean the browser silently drops them over plain HTTP — see
`config/settings/production.py`'s module docstring.

**Containers.** All three images (backend, frontend, AI worker) run as a
dedicated non-root user, confirmed in each `Dockerfile`. The database and
Redis are never published to the host by default (`expose`, not `ports`) —
unreachable from the café's guest wifi even if the compose file is applied
as-is.

**Dependencies.** No known-vulnerable pinned versions found in
`requirements/*.txt` or `frontend/package.json` at time of review. This is a
point-in-time check, not continuous scanning — see "What this review did
not cover."

---

## Findings fixed in this phase

**No size cap on the café logo upload.** `Cafe.logo` accepted an image of
any size — Django's `FILE_UPLOAD_MAX_MEMORY_SIZE` only decides where an
upload is buffered while it streams in, not a hard limit on how large it may
be. Reachable only by an authenticated owner/manager
(`IsOwnerOrManager`), so the realistic risk was an insider filling disk via
repeated large uploads rather than an outside attacker, but a real cap costs
nothing. Fixed with `validate_logo_size` (`apps/tenants/models.py`, 5 MB),
attached as a model field validator — the same pattern `stay_color_stops`
already used for `validate_color_stops` — so it is enforced everywhere the
field is written, not just through one serializer.

**`sentry-sdk` was a declared dependency with no code behind it.**
`requirements/prod.txt` has listed `sentry-sdk` since early in the project,
and `apps/core/logging.py`'s own docstring already anticipated "a handler a
deployment might add later (file, syslog, Sentry)" — but nothing ever
called `sentry_sdk.init()`. A declared-but-unwired capability is exactly the
kind of overclaiming this project avoids everywhere else its documentation
speaks in confident terms about what actually runs. Wired it up in
`config/settings/production.py`, strictly opt-in behind `SENTRY_DSN`
(unset by default — the module is never even imported unless a deployment
sets it, keeping the local-first, no-internet-required guarantee intact for
every install that doesn't opt in), with `include_local_variables=False`.
That last setting matters specifically for this product: a stack frame's
local variables can hold an RTSP URL or a raw request body, and Sentry's own
capture path does not go through `RedactSecretsFilter` — the safer choice
was to never let it collect local variables at all, rather than trying to
re-scrub a second, differently-shaped copy of the same sensitive data headed
to a third party. Verified end to end: settings load cleanly with
`SENTRY_DSN` unset (nothing imported, nothing contacted) and with it set to
a real-shaped DSN (client actually initializes).

**No container resource limits, no log rotation.** Covered under
Production hardening below, not here, since neither is a vulnerability on
its own — but an unbounded log or an unbounded process is exactly the kind
of thing that turns a small problem into an outage, so both are treated with
the same seriousness as the items above.

---

## Reviewed and deliberately left as-is

**Refresh tokens are not blacklisted after rotation
(`BLACKLIST_AFTER_ROTATION = False`, no `token_blacklist` app installed).**
This was already a deliberate, documented decision from an earlier phase,
not an oversight this review is the first to notice —
`apps/accounts/views.py::LogoutView`'s own docstring states the reasoning:
spec §16 requires the café to keep working with no external services, and a
blacklist table would add a database write to every single token refresh
for every logged-in staff member, all day, forever, to defend against a
scenario (a stolen *refresh* token specifically, not a stolen access token)
that is already bounded by a 30-minute access-token lifetime and by tokens
living in httpOnly cookies a browser-side XSS cannot read. This review
confirms rather than overturns that trade-off: it is a reasonable one for a
LAN appliance whose realistic threat model is "an employee's laptop is
stolen," not "a nation-state wants this café's occupancy data," and the
docstring already tells an operator exactly how to enable blacklisting if a
specific deployment's risk tolerance genuinely needs it.

**No Content-Security-Policy header.** `X-Frame-Options`,
`X-Content-Type-Options` and `Referrer-Policy` are set; CSP is not, and
Django has no built-in CSP support (it would need `django-csp` or a hand
-written middleware). Considered and deferred: this product has no
user-generated HTML rendering surface anywhere in the frontend (confirmed
above — no `dangerouslySetInnerHTML`), so CSP's main value here would be
defense-in-depth against a vulnerability class that does not currently
exist in the codebase, at the cost of real risk of breaking the dashboard,
the public display, or the WebSocket connection if the policy is
misconfigured — a risk that would need its own live-verification pass
across every page before it could be trusted. For a LAN appliance rather
than a public-internet service, that trade did not clear the bar this phase
set for itself. Worth revisiting if the frontend ever gains a feature that
renders admin-supplied HTML.

---

## Production hardening (this phase)

Covered in depth in [docs/production.md](production.md); summarized here
because "resource limits" and "log rotation" are availability concerns as
much as security ones — an unbounded log filling a café's disk, or one
runaway container starving every other process on the same small machine,
is a self-inflicted denial of service:

- **Log rotation.** Every long-running container now sets
  `logging: {driver: json-file, options: {max-size: 10m, max-file: 5}}` —
  50 MB per service, capped, never unbounded.
- **Resource limits.** Every container in `docker-compose.yml` now has a
  `deploy.resources.limits` ceiling sized to docs/hardware.md's stated
  minimums, so a leak or a runaway process is contained to its own
  container (and restarted, `restart: unless-stopped`) rather than able to
  starve camera capture or the database. The AI worker's limit
  (`docker-compose.ai.yml`) is the one exception made env-overridable
  (`AI_WORKER_CPU_LIMIT`/`AI_WORKER_MEMORY_LIMIT`) rather than fixed, since
  docs/hardware.md sizes that specific process anywhere from a 4-core mini
  PC to a 12+-core tower depending on camera count.
- **Backups.** `scripts/backup.sh`/`scripts/restore.sh`, live-verified
  against a real PostgreSQL instance (seeded data → backup → mutated data →
  restore → confirmed the original data came back exactly, and confirmed
  restore refuses to run without the operator typing the database name to
  confirm). See docs/production.md for scheduling.
- **systemd units** (`deployment/systemd/`) for a non-Docker install, each
  running as a dedicated non-root user with `NoNewPrivileges`,
  `ProtectSystem=strict` and `ProtectHome=true` — the same non-root, locked
  -down posture the three Docker images already had, expressed in systemd
  terms instead of a container boundary.

---

## What this review did not cover

- **No automated dependency-vulnerability scanning** (e.g. `pip-audit`,
  `npm audit` wired into CI) — there is no CI pipeline in this repository
  yet to wire it into. A point-in-time manual check is not a substitute for
  that running continuously.
- **No penetration test.** This was a code and configuration review by
  someone who already knows the codebase, not an adversarial test by
  someone trying to break it. A venue with a genuinely sensitive threat
  model (not the LAN-appliance default this product targets) should
  commission one before relying on this document alone.
- **No review of the PostgreSQL, Redis, or nginx images themselves** beyond
  confirming they are pinned to specific tags — their own CVE history is
  each project's responsibility to track, not re-audited here.
- **No fuzzing or load testing** of the ingest endpoint or the WebSocket
  paths under adversarial or high-volume input.
