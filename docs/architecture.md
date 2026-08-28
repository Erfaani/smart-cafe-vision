# Architecture

## The shape of the system

```
IP cameras ──RTSP──► AI worker ──Redis Stream──► event consumer ──► PostgreSQL
                         │                                              │
                         └──heartbeat──► Redis                          │
                                                                        ▼
                                              Django API ◄──── analytics projections
                                                   │
                            ┌──────────────────────┼──────────────────────┐
                            ▼                      ▼                      ▼
                     Next.js dashboard      WebSocket push        public display
                        (staff)              (live updates)          (café TV)
```

Everything in that diagram runs on hardware inside the café. Nothing calls out
to the internet at runtime.

---

## Decisions that shaped it

### The AI worker is a separate process, not a Django thread

Inference is a CPU/GPU-bound loop that must run continuously. Sharing a process
with the web server means a slow frame adds latency to a dashboard request, and
restarting the API to change a setting stops camera capture.

Separating them also means the worker can run on different hardware from the
backend — a GPU box in the back office, the API on a small always-on machine —
with no code change. The only coupling is the event contract.

### The bus is Redis **Streams**, not pub/sub

This is the decision the rest of the design rests on.

Pub/sub delivers to whoever is connected at that instant. Restart the backend to
apply a setting and every event published during those four seconds is gone. If
one of them was a `person_exited`, that customer's session never closes: their
stay time grows forever, the occupancy count is permanently one too high, and
the day's analytics are wrong — silently, with nothing in the logs.

Streams persist entries, support consumer groups with explicit acknowledgement,
and let a restarted consumer resume exactly where it stopped. The costs are a
bounded memory buffer (`EVENT_STREAM_MAXLEN`) and the need to acknowledge, both
of which are cheap next to losing a day of data.

An entry is acknowledged only after its database transaction commits. A crash
between commit and acknowledgement causes redelivery, which the unique
`event_id` turns into a no-op.

### Every duration comes from a timestamp, never a frame count

The worker stamps `occurred_at` when it observed the frame. The backend stores
that, not the ingest time.

Frame counting seems simpler until the GPU is busy and the pipeline drops to 4
fps: every stay time computed from frames is then wrong by a factor that varies
through the day. Timestamps are correct whatever the inference rate does, which
is why the contract rejects a naive (timezone-less) timestamp outright rather
than guessing at a DST boundary.

### The event log is the source of truth; everything else is a projection

`TrackingEvent` is append-only. Customer sessions (Phase 5), daily
analytics rollups (Phase 8), and table occupancy (Phase 9) are all computed
from it. A bug in a projection is fixed by recomputing rather than by
asking a café to re-run a day they cannot repeat — `DailyStat`'s own
recomputation path (`manage.py backfill_daily_stats --force`) is a direct
instance of this rule. That same "everything durable is a projection, not
the raw log itself" property is what makes `apps.events.prune_old_events`
(Phase 10) safe: deleting a `TrackingEvent` row past `EVENT_RETENTION_DAYS`
never removes a figure a café can currently see, only the raw material a
future recomputation of that day's projections would have used.

### One rollup table, not a growing family of them

Phase 8's "scheduled rollups so a year of history does not mean a slow
query" is answered by exactly one table, `DailyStat` — one row per café per
*local* calendar day, computed by `apps/analytics/rollups.py` from raw
`CustomerSession` rows and never written any other way. A year is at most
~366 rows per café: cheap enough to fetch and aggregate client-side for any
range a dashboard would ask for, so "weekly" and "monthly" trends are simply
a wider date range over this same table rather than a second, separately
maintained aggregate at a coarser grain. Two things keep it current without
a dashboard request ever touching raw session rows: a Celery beat task
that recomputes today (always partial) and yesterday (only if not yet
final) every `ANALYTICS_ROLLUP_INTERVAL_SECONDS`, and a one-time management
command, `backfill_daily_stats`, for the history that already existed before
Phase 8 shipped -- the scheduled task deliberately never walks further back
than yesterday, so an upgrade needs this run once by a technician.

The rollup deliberately answers "peak hours" and "peak occupancy" as two
different numbers, not one. `hourly_entries` is a simple entry-count
histogram by local hour of arrival; `peak_occupancy` is a true
concurrent-occupancy peak from a sweep over every session's `[entry_at,
exit_at)` interval. They can genuinely disagree — a short, sharp morning
rush can win on raw arrivals while a handful of long-staying customers
overlapping in the afternoon produces a higher actual peak headcount — and
collapsing them into one number would silently answer only one of the two
questions "peak hours and days" was actually asking.

### A person the tracker loses looks identical to a worker restart — so one mechanism handles both

Neither ever produces a `person_exited` event: a lost track has no exit
crossing to report, and a restarted worker's tracker starts its track-id
counter over from zero, so no future event can match the old session at all.
From the database's side both are the same symptom — a `CustomerSession`
whose `last_seen_at` has stopped advancing — so rather than build two
detectors for two causes, `camera_stats` heartbeats carry an
`active_track_ids` roster that keeps `last_seen_at` current for anyone still
genuinely in frame, and one Celery task (`close_stale_sessions`) closes
whatever has gone quiet past a grace period, regardless of which of the two
actually happened. This is also what "session recovery after a worker
restart" means in practice: there is nothing to recover, because the old
session was never holding a resource the new worker needs — it simply ages
out on its own.

Phase 9 reuses this exact mechanism for tables rather than inventing a
second one: `camera_stats` also carries an `occupied_table_ids` roster
alongside `active_track_ids`, and `close_stale_table_sessions` is
`close_stale_sessions`'s reasoning applied to `TableSession` instead of
`CustomerSession` — a table left occupied by a worker that crashed mid-visit
ages out the same way a lost customer track does.

### A table is an area to cover, not a threshold to cross

`TableZone` is an axis-aligned rectangle, not a polygon — the same "resolve
to the simplest shape the spec's examples actually need" reasoning `Zone`
applied to a line in Phase 5, restated for area instead of a boundary.
Detecting occupancy could not reuse `Zone`'s reference-point technique for
the same reason a table is not a doorway: a seated person's detected box
mostly shows upper body, since furniture occludes the rest, so there is no
single trustworthy point to test against the table. `TableOccupancyDetector`
(`ai_worker/worker/tables.py`) instead measures *coverage* — the union area
of every tracked box clipped to the table's rectangle, computed exactly via
coordinate compression so two people jointly covering one table are never
double-counted where their boxes overlap each other, divided by the table's
own area and compared against a threshold, debounced by a few consecutive
ticks in each direction to absorb single-frame noise.

That heuristic's confidence depends on camera placement in a way the
product does not try to paper over: reliable from directly overhead, only an
approximate signal from the side, where a person standing at a table can
register the same as one seated at it. `Camera.mount_type` makes that
distinction an explicit, admin-set fact rather than a silent assumption, and
the table editor shows an honest caveat for anything not `overhead` —
including the unset default, so a café is never shown a confident-looking
UI for a camera nobody has actually characterized yet.

### One colour computation, deliberately implemented twice

A customer's box on the public display (Phase 7) and their row on the
dashboard's Customers page (Phase 5) must show the *same* colour for the
*same* stay duration. That computation runs in two different languages in
two different processes — the backend for an initial render and any
one-shot API consumer, the browser for a live, per-second tick that must not
mean polling the API once a second — so it cannot be one shared module.
`apps/core/color.py` and `frontend/src/lib/stay-color.ts` are independent,
hand-mirrored implementations of the identical algorithm (piecewise-linear
RGB interpolation across admin-configured `{seconds, color}` stops), and
agreement between them is enforced the same way Phase 5 enforced agreement
between the worker's zone-crossing sign convention and the editor's arrow: a
shared list of hand-computed input/output vectors, pasted verbatim into both
test suites, so a change that breaks agreement fails on both sides
independently rather than only surfacing as a customer noticing their box and
their dashboard row disagree. Writing those vectors by hand is also what
surfaced a real cross-language rounding pitfall before it ever shipped — see
docs/roadmap.md's Phase 6 write-up.

### The public display shows geometry, never video

Phase 7's live tracking overlay could have been actual camera footage with
coloured boxes drawn on it, served to an unauthenticated `/display/<slug>`
route. It is not: every tracked person becomes a synthetic dot at their real
position, coloured by stay time, on a stylised background rather than the
camera's own pixels. The public HTTP and WebSocket surface (`apps/display/`)
never carries a frame, a crop, or anything that could be mistaken for one —
only a track id, an (x, y), and a colour, the same anonymous shape the event
bus has enforced since Phase 1. Actual video stays where it already was: the
authenticated staff preview (`/api/v1/cameras/{id}/stream.mjpg/`), gated by a
JWT. Streaming raw footage to a route reachable by anyone on the café's
network without logging in — the guest wifi, not just the room the TV sits
in — would have been a materially larger exposure than anything else this
system accepts, for a feature (the box overlay) that a coloured dot serves
just as well.

The same reasoning extends to the display's leaderboard and its messages:
the leaderboard shows durations only, ranked, never a track id or a camera
name, and messages are always generic rather than composed to reference a
specific person's stay — see apps/display/models.py and
apps/display/live.py's docstrings. A public screen showing "camera 2, track
47 has been here 2 hours" would let the room single someone out from data
that was anonymous the instant before it was displayed; "longest visit
today: 2h 04m" cannot.

### The display's WebSocket polls per-connection; there is no broadcaster

`ws/display/<slug>/` (`apps/display/consumers.py`) is the socket
`SystemStatusConsumer` explicitly left as a placeholder in Phase 1 ("live
tracking frames are added in Phase 7"). Each connection independently reads
Redis and the database on its own timer and pushes straight to itself,
rather than one process reading once and fanning out to every connected
client through a Channels group. That would be the wrong trade for a service
running at internet scale; a café's public display is one physical TV, not a
multi-viewer product, so there are only ever a handful of connections per
café and a shared broadcaster would add real complexity (group membership,
a canonical publisher, coordinating its own polling loop) to buy nothing a
café install would ever notice. The café itself is re-fetched on every tick
rather than cached for the connection's lifetime, precisely so a
`stay_color_stops` edit on the Café settings page reaches an already-open
kiosk within about a second rather than only on its next reconnect.

### Tenancy exists from the first migration

v1 installs one café per server. But `CafeScopedModel` puts a café foreign key
on every domain table from commit one, because retro-fitting a tenant key onto
tables that already hold production data is a migration that takes a venue
offline.

### Tokens live in httpOnly cookies, written by the Next.js server

The browser never receives an access token in JavaScript. The dashboard calls
its own Next.js routes, which attach the token server-side.

This matters more here than in a typical web app: the same software serves a
public display on a TV that anyone in the room can walk up to. Browser-readable
admin tokens would be one XSS away from someone standing in the café.

### ASGI from the start

Channels and uvicorn are in place from Phase 1 even though the only socket is a
system-status channel. The live display in Phase 7 is a core requirement, and
retrofitting ASGI later means replacing the server layer under a running system.

### One shared detector, one tracker per camera — not symmetric on purpose

Every camera's capture thread calls into the *same* `PersonDetector` instance:
loading N copies of the same model weights for N cameras would be pure waste,
and inference calls are simply serialised behind a lock. Tracking cannot use
that pattern. Reading ultralytics' source (not just its public API) showed why:
its tracker state lives on the shared model's `predictor.trackers`, a list
indexed by video-stream position — routing independent cameras' tracking
through that shared, positionally-indexed list would conflate their tracks the
moment two cameras' detection ticks interleave, which they always do. So
detection is shared and tracking is not: each camera owns one independent
`PersonTracker`, fed through a small duck-typed shim rather than ultralytics'
own `Model.track()` convenience API. See `worker/tracker.py`'s module
docstring for the full reasoning, including a second subtler hazard the same
source-reading turned up: constructing a tracker resets a process-global
track-id counter, which would otherwise corrupt id uniqueness for every camera
already running every time a new one starts.

### Two deployment paths, one hardening posture

Phase 10 added `deployment/systemd/` as a full non-Docker alternative to
`docker-compose.yml` -- not a stripped-down fallback, but every long-running
process (backend, event consumer, Celery worker, Celery beat, frontend, AI
worker) with a real systemd unit. The reason to build it in parallel rather
than "Docker first, systemd as an afterthought" is that a café's mini PC is
frequently not a machine its owner wants running a container runtime at all,
and a hardening measure that only exists on one path is not a hardening
measure, it is a caveat. Both paths land on the same posture from different
mechanisms: the Docker images each run as a dedicated non-root user (`USER
appuser` / `nextjs` / `worker`) with the database and Redis never published
to the host; the systemd units run as a dedicated non-root user with
`NoNewPrivileges`, `ProtectSystem=strict` and `ProtectHome=true`. Same
guarantee, expressed in whichever mechanism the deployment actually uses.

### A resource limit that must scale is an env var, not a constant

Every container in `docker-compose.yml` (postgres, redis, backend, the
event consumer, Celery, Celery beat, frontend, nginx) got a fixed
`deploy.resources.limits` ceiling in Phase 10, sized once from
docs/hardware.md's stated minimums, because none of those processes' actual
resource needs move with how many cameras a café has plugged in -- a
database serving four cameras' worth of sessions looks almost identical to
one serving one camera's worth. The AI worker is the deliberate exception:
docs/hardware.md sizes that one process anywhere from a 4-core mini PC (1
camera) to a 12+-core tower splitting 16 cameras across two worker
processes, so baking a fixed number into `docker-compose.ai.yml` would have
meant either starving a large install or wasting headroom on a small one.
`AI_WORKER_CPU_LIMIT`/`AI_WORKER_MEMORY_LIMIT` make it a one-line `.env`
change instead of a compose-file edit -- the same reasoning `AI_TARGET_FPS`
and the other per-install AI worker knobs already established.

---

## Component reference

### `backend/`

| Module | Responsibility |
|---|---|
| `config/` | Settings (base/development/test/production), URLs, ASGI, Celery |
| `apps/core/` | Base models, health checks, logging filters, crypto, permissions, error envelope, the shared stay-colour computation |
| `apps/tenants/` | The `Cafe` model (branding, `stay_color_stops`), public branding endpoint, `bootstrap` command |
| `apps/accounts/` | User model, JWT auth, roles, staff management |
| `apps/events/` | Event bus client, ingest, `TrackingEvent`, consumer command, the `prune_old_events` retention task |
| `apps/cameras/` | `Camera` (including `mount_type`), `Zone`, and `TableZone` models, RTSP connection testing, capture/detection/tracking projections, live preview and detection/tracking cache readers |
| `apps/sessions/` | `CustomerSession` model, entry/exit and heartbeat projections, the `close_stale_sessions` Celery task |
| `apps/display/` | `DisplayMessage` model, the public display's live/stats/messages composition (`live.py`), the public HTTP views, `ws/display/<slug>/` |
| `apps/analytics/` | `DailyStat` rollup model, the computation itself (`rollups.py`), the `refresh_daily_stats` Celery task, `backfill_daily_stats` management command |
| `apps/tables/` | `TableSession` model, `table_occupied`/`table_released`/`camera_stats` projections, on-demand utilisation stats (`stats.py`), the `close_stale_table_sessions` Celery task |

### `ai_worker/`

| Module | Responsibility |
|---|---|
| `worker/config.py` | Environment configuration |
| `worker/publisher.py` | Event publishing with local buffering during a Redis outage |
| `worker/runner.py` | Process lifecycle, heartbeat, capability reporting |
| `worker/manager.py` | Reconciles the backend's camera list against running capture workers; builds the shared detector and per-camera trackers |
| `worker/capture.py` | Per-camera RTSP capture loop: connect, read, reconnect with backoff; ticks detection and tracking |
| `worker/rtsp_client.py` | The one module that imports OpenCV directly, behind a `Protocol` so capture.py stays testable without it |
| `worker/detector.py` | YOLO model loading (CPU/CUDA), person detection, graceful capture-only fallback if the model can't load |
| `worker/tracker.py` | Anonymous multi-object tracking (ByteTrack/BoT-SORT) — one instance per camera, never shared; see its module docstring for why |
| `worker/zones.py` | Entrance/exit line-crossing geometry — pure math, no model weights; one `ZoneCrossingDetector` per camera |
| `worker/tables.py` | Table occupancy via box-overlap coverage — exact union-area geometry, no model weights; one `TableOccupancyDetector` per camera |

### `shared/scv_contracts/`

The event schema, installed into both the backend and the worker. It enforces
three rules at construction time: a timezone-aware timestamp, a camera id on
camera-scoped events, and no personally identifying keys in any payload. The
last one is a guard rail with a test behind it, so the privacy promise is
checked by CI rather than by memory.

### `deployment/` and `scripts/`

| Path | Responsibility |
|---|---|
| `deployment/nginx/` | The optional reverse-proxy config (Phase 1) |
| `deployment/systemd/` | Non-Docker unit files for every long-running process, one-to-one with `docker-compose.yml`'s services (Phase 10) |
| `scripts/generate_keys.py` | Fills in `.env`'s generated secrets on first install; idempotent |
| `scripts/backup.sh` / `scripts/restore.sh` | Database backup/restore, live-verified against a real PostgreSQL round-trip (Phase 10); see docs/production.md |

---

## Failure behaviour

| Failure | What happens |
|---|---|
| Redis restarts | Worker buffers up to 5000 events in memory, flushes on reconnect; consumer reconnects with capped exponential backoff |
| Backend restarts | Events accumulate in the stream; the consumer resumes from its last acknowledgement |
| Consumer crashes mid-batch | Unacknowledged entries are redelivered to the same consumer name on restart |
| Duplicate delivery | Unique `event_id` makes the second insert a no-op |
| Malformed event on the bus | Logged, acknowledged, skipped — one bad entry cannot wedge the pipeline |
| Event for an unknown café | Rejected and logged, not stored |
| PostgreSQL unreachable | `/readyz/` returns 503 with the failing component named; `/healthz/` still returns 200 so the container is not killed |
| No AI worker running | Health reports *degraded*, not *down* — the dashboard still works |
| Redis unreachable while the public display is live | `get_public_live_tracks` catches the error per camera and degrades to an empty overlay for it, logging a warning — the display (HTTP and WebSocket both) stays up instead of 500ing or killing the tracks loop |
| Tracker loses a person, or the AI worker restarts mid-visit | Neither produces a `person_exited` event; the `CustomerSession` sits ACTIVE until `close_stale_sessions` (Celery beat, every `SESSION_STALE_CHECK_INTERVAL_SECONDS`) closes it as `track_lost` once `last_seen_at` has gone quiet for `SESSION_STALE_GRACE_SECONDS` |
| A table's occupancy is never cleanly released (worker crash or restart mid-visit) | Same mechanism as the row above, applied to tables: the `TableSession` sits ACTIVE until `close_stale_table_sessions` closes it as `stale` once its `occupied_table_ids` roster heartbeat has gone quiet for `TABLE_STALE_GRACE_SECONDS` |

The distinction in that last row is deliberate. Liveness (`/healthz/`) does no
I/O, so a busy database never causes a restart loop. Readiness (`/readyz/`)
reports the whole picture and returns 503 only when something critical is down.
