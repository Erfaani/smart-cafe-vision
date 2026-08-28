# Development

## Setup

See [installation.md](installation.md#local-development-installation). In short:

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -r backend/requirements/dev.txt
.venv/Scripts/python -m pip install -e ./shared
cd frontend && npm install
```

On Linux/macOS use `.venv/bin/python`.

## Tests

```bash
make test                      # everything

cd backend    && ../.venv/Scripts/python -m pytest
cd ai_worker  && ../.venv/Scripts/python -m pytest
cd frontend   && npm run typecheck
```

The backend suite runs against PostgreSQL by default and against sqlite with
`DATABASE_URL=sqlite:///test.sqlite3`. Redis is not required: tests use locmem
caches, the in-memory channel layer, and `fakeredis` for the bus.

The suite is fast by design — the backend's 412 tests run in a couple of seconds on
sqlite — so there is no excuse for not running it before a commit. The worker
suite (153 tests) needs no camera, GPU, or model download: real ultralytics
tracker classes and pure Kalman/IoU math run happily against fakes. The
frontend suite (39 tests, `npm test`) covers pure logic only — duration
formatting, zone geometry, stay-time colour, daily-stat aggregation, redirect
safety — there is no component-rendering harness installed, so UI changes
are verified by hand in a browser instead.

**Always run the full backend suite, not just the app you touched.**
`apps/events/tests/test_ingest.py` once registered throwaway test
projections on two `EventType` values it called "safe, currently unused,"
cleaning up with `ingest_module._projections[key].clear()`. Once Phase 9
registered real projections on those same two types, that blind `.clear()`
silently deleted them for the rest of the test session whenever the full
suite ran — visible only as confusing `DoesNotExist` errors in an unrelated
app, and invisible if you only ever ran `apps/tables`'s own tests in
isolation. If a test registers a projection for the purpose of the test,
snapshot the prior list and restore it (`previous = list(...)`; `...[:] =
previous` in `finally`) rather than clearing the registry — a shared
registry's `.clear()` is never the right cleanup, no matter how unused the
key looks at the time.

**Testing `scripts/backup.sh` / `scripts/restore.sh`.** Neither is Python or
TypeScript, so neither has a pytest/vitest suite -- shelling out to
`pg_dump`/`psql` against a real container is what they exist to do, and a
mock of that would just be testing the mock. Verify them for real instead,
against `docker compose up -d postgres`: seed a row, run `backup.sh`,
mutate or delete it, run `restore.sh` (with `--yes` to skip the
confirmation prompt in a non-interactive shell), and confirm the original
row came back exactly. This is also how Phase 10 verified them before
shipping -- see docs/roadmap.md's Phase 10 write-up.

**Testing a Channels consumer** (e.g. `apps/display/tests/test_consumers.py`):
`channels.testing.WebsocketCommunicator`, wrapped in a bare `URLRouter` of
just `config.routing.websocket_urlpatterns` rather than the full ASGI
`application` from `config/asgi.py` — origin validation and JWT auth
middleware are irrelevant to most consumers and would only couple the test to
infrastructure it isn't exercising. Needs `@pytest.mark.asyncio` (this
project does not set `asyncio_mode = auto`) and
`@pytest.mark.django_db(transaction=True)`, since `database_sync_to_async`
runs ORM calls on a separate thread with its own connection.

## Conventions

**Where code goes.** Detection, tracking, event processing, camera management
and business logic each live in their own module. If a file is doing two of
those, it is in the wrong shape.

**Timestamps.** Every duration is computed from `occurred_at`, never from a
frame count and never from ingest time. The event contract rejects naive
timestamps rather than guessing a timezone.

**New event types.** Add to `scv_contracts.EventType`, then register a
projection with `apps.events.ingest.register_projection`. Do not add branches to
`ingest()` — it must stay small enough to reason about while the pipeline is
live.

**Contract changes.** Bump `CONTRACT_VERSION`. A worker and a backend on
different versions then fail loudly at ingest instead of half-understanding each
other.

**Payloads.** Anything that could identify a person is rejected by the contract.
If you need a new payload key, check it is not in `FORBIDDEN_PAYLOAD_KEYS` and
think about why before adding it there.

**Tenancy.** New domain models inherit `CafeScopedModel`. New viewsets filter by
`request.user.cafe_id` unless the user is a superuser, and there should be a
test asserting the scoping. The one legitimate exception is a model that only
ever exists in the context of a single parent row it cannot outlive on its own
— `apps.cameras.models.Zone` has no `cafe` field at all, scoped instead
through `camera__cafe_id`, because denormalising a café onto it would need to
stay in sync with a camera reassignment that is not even a supported
operation today. Reach for `CafeScopedModel` by default; drop to `BaseModel`
plus a parent FK only when you can name why the denormalised café would never
be useful.

**Logging.** Structured key=value, through the `smartcafe.*` loggers. Never log a
credential — `RedactSecretsFilter` catches the common shapes, but it is a safety
net, not permission to be careless.

**Errors.** Raise `ServiceError` (or a subclass) for domain failures. The
handler turns everything into one envelope so the frontend needs one error path.

**Logic duplicated across the Python/TypeScript boundary.** Some computations
(the zone-crossing direction test, the stay-time colour) must produce
identical output in the AI worker or backend and in the browser, but cannot
be one shared module across two languages and processes. When you have to
duplicate one, don't trust "they look equivalent" — write a shared list of
hand-computed input/output vectors and paste it, verbatim, into both test
suites (see `ai_worker/tests/test_zones.py` / `frontend/src/lib/__tests__/
zone-geometry.test.ts`, and `backend/apps/core/tests/test_color.py` /
`frontend/src/lib/__tests__/stay-color.test.ts`). Doing this by hand has
already surfaced a real pitfall before it shipped: Python's `round()` and
JavaScript's `Math.round()` disagree at exact `.5` boundaries
(banker's-rounding vs. always-round-up) — worth knowing before you reach for
either one in code that has to match its counterpart in the other language.

## Lint

```bash
make lint      # ruff over Python, eslint over the frontend
```

## Migrations

```bash
cd backend && ../.venv/Scripts/python manage.py makemigrations
../.venv/Scripts/python manage.py makemigrations --check --dry-run   # CI drift check
```

## Background tasks (Celery)

```bash
cd backend && ../.venv/Scripts/python -m celery -A config worker --loglevel=info
../.venv/Scripts/python -m celery -A config beat --loglevel=info   # separate process
```

`CELERY_TASK_ALWAYS_EAGER=True` in test settings, so a test that calls a task
function directly (e.g. `apps.sessions.tasks.close_stale_sessions()`) runs it
synchronously with no broker needed — that is how this project's task tests
work, rather than mocking Celery. `CELERY_BEAT_SCHEDULE` in
`config/settings/base.py` is the one place periodic tasks are registered; the
worker and the beat scheduler are separate processes (`docker-compose.yml`'s
`celery` and `celery-beat` services) so a slow task can never make the
schedule itself run late.

**A scheduled task only ever moves forward, never backfills.**
`apps.analytics.tasks.refresh_daily_stats` recomputes today and (if not yet
final) yesterday, on a timer — it will never walk back further than that on
its own. A café upgrading onto a phase that adds a rollup table needs its
pre-existing history computed once: `manage.py backfill_daily_stats
[--cafe=<slug>] [--force]`. Reach for the same shape (a small idempotent
management command, `--force` to recompute rows that already look final)
if a future rollup needs the same one-time backfill on upgrade.

## Adding a page to the dashboard

Pages live in `frontend/src/app/dashboard/`. The navigation in
`dashboard/layout.tsx` has an `available` flag per item — flip it when the page
actually works. A link that leads nowhere is how staff stop trusting the tool.

## Debugging the event pipeline

```bash
python manage.py emit_test_event --type worker_heartbeat
python manage.py consume_events --once
```

`--once` drains what is pending and exits, which is also how the consumer is
tested. `/api/v1/events/bus-stats/` reports stream depth and unacknowledged
count.
