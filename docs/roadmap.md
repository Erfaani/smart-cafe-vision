# Roadmap

Eleven phases. Each one ends with working, tested software — not a stub that a
later phase is expected to rescue.

| # | Phase | Status |
|---|---|---|
| 1 | Architecture and foundation | **complete** |
| 2 | RTSP camera integration | **complete** |
| 3 | YOLO person detection | **complete** |
| 4 | Multi-object tracking | **complete** |
| 5 | Entry/exit detection and stay time | **complete** |
| 6 | Dynamic colour system | **complete** |
| 7 | Public interactive display | **complete** |
| 8 | Analytics dashboard | **complete** |
| 9 | Table analytics | **complete** |
| 10 | Production hardening | **complete** |
| 11 | Final QA and productisation | **complete** |

Phases 1–7 constitute the MVP: after Phase 7 a café has a working installation
with a live public display. Phases 8–9 add depth, 10–11 add polish and
robustness. All eleven phases are complete.

---

## Phase 1 — Architecture and foundation ✅

Repository structure, Django + DRF + Channels backend, Next.js frontend,
PostgreSQL, Redis, Docker Compose, JWT authentication with roles, the café
tenant model, the event contract and bus, health monitoring, and documentation.

122 automated tests across the backend and the worker. No camera code, and no simulated detections.

## Phase 2 — RTSP camera integration ✅

`Camera` model with encrypted credentials; a protocol-level RTSP connection
tester (OPTIONS/DESCRIBE, Digest and Basic auth, no OpenCV needed in the
backend) that reports specific failures — camera offline, authentication
failed, stream not found, stream timeout — rather than a generic error; a
capture loop with exponential-backoff reconnection; a camera management UI;
a live MJPEG preview proxied through the backend so the browser never talks to
the AI worker directly; per-camera health surfaced via the same event
projection mechanism the event log was built for in Phase 1.

The hard part was not connecting — it was reconnecting for six months without
leaking a file descriptor or wedging on a camera that answers TCP but never
sends a frame. That failure mode is handled by two layers: OpenCV's own
open/read timeouts (mapped to FFmpeg's connection timeout), and a
belt-and-braces wall-clock check in case a given camera/FFmpeg build doesn't
honour them. A real end-to-end run — actual OpenCV, an intentionally-silent
fake RTSP server, a real backend and Redis — showed the exact expected
sequence: 1s, 2s, 4s, 8s, 16s, capped at 30s.

That same live run caught a real bug no unit test had: the account
`manage.py bootstrap` creates is a Django superuser, and the original
`perform_create` logic never assigned it a café — camera creation failed with
an unhelpful "conflict" error on the exact account every fresh install starts
with. Fixed with `apps.core.viewsets.CafeScopedCreateMixin`, shared by the
camera and staff-account viewsets, with regression tests using that same
account shape.

175 backend tests, 37 worker tests, 10 frontend tests.

## Phase 3 — YOLO person detection ✅

Model loading with CUDA/CPU auto-detection (an explicit `AI_DEVICE=cuda` that
finds no GPU fails loudly rather than silently downgrading to CPU);
person-class-only detection at a configurable confidence threshold; inference
throttled to `AI_TARGET_FPS`, independent of the camera's own frame rate;
per-camera detection statistics, both a periodic persisted snapshot
(`Camera.last_person_count`) and a near-real-time cache
(`/api/v1/cameras/{id}/detections/`) for a live-view badge.

Frame dropping under load falls out of the Phase 2 design for free: detection
reads from the same single-slot `latest_frame` holder the preview does, so a
detection tick that falls behind simply picks up whatever frame is current
next time, never a stale queued one.

A model that fails to load — no internet on first run, an unsupported CPU, out
of memory, an explicitly requested GPU that isn't there — degrades to
capture-only mode automatically. The worker's reported capabilities
(`person_detection`) reflect what actually loaded, never what was configured;
a café should never have to wonder why detection silently isn't running.

Verified against real inference, not just fakes: the real YOLO11n model,
downloaded once and cached, correctly found exactly two people (with sensible
confidence scores) in ultralytics' own bundled sample photograph — and found
none of them when the confidence threshold was raised past their actual
scores, confirming the threshold is real, not decorative.

`ultralytics` turned out to require the full `opencv-python` build, not the
headless one Phase 2 chose: it references `cv2.imshow` unconditionally at
import time, which does not exist in the headless build, so importing
ultralytics with only headless installed fails outright — not just when a GUI
function is actually called. Switched to full opencv-python, matching
ultralytics' own official Docker images, which needs two additional system
libraries (`libgl1`, `libglib2.0-0`) on the minimal base image.

A second real bug surfaced only by actually deploying this in a container
mentally: the `ai_models` Docker volume from Phase 1 was never wired up.
`YOLO("yolo11n.pt")` resolves a bare filename against the process's current
working directory, not the mounted volume, so the downloaded weights would
have been silently lost on every container recreation. Fixed with
`AI_MODELS_DIR` and `resolve_model_path`, and the volume's ownership is now
set up before it is first attached so the non-root worker user can write to it.

186 backend tests, 62 worker tests, 10 frontend tests.

## Phase 4 — Multi-object tracking ✅

ByteTrack by default, with BoT-SORT selectable (`AI_TRACKER=botsort`) — both
ultralytics' own bundled implementations, built on top of Phase 3's detector
rather than replacing it, so a detection tick's output feeds straight into
tracking with no second inference pass. Anonymous, temporary track ids;
occlusion recovery (a person briefly missed by the detector keeps their id
when they reappear, within `track_buffer`); a `track_count` alongside
`person_count` in `camera_stats` and the live-view badge, since the two can
legitimately differ during a brief occlusion.

BoT-SORT's optional appearance/ReID mode is never enabled — not exposed as a
setting at all, not just defaulted off. That mode extracts an embedding that
functions as a biometric feature, which spec §26 rules out; association here
is motion-and-IoU only, exactly like ByteTrack.

Single-camera tracking only, as planned: cross-camera identity is not reliably
solvable without appearance matching, which is the same biometric trade-off
just declined. The architecture allows multi-camera aggregation later
(counting, not identifying), but the product will not claim to follow one
person between cameras.

**Not ultralytics' `Model.track()` convenience API.** Reading its source
turned up why that would have been a real bug: it ties tracker state to
`predictor.trackers`, a list indexed by video-stream position on the shared
detection model. Every camera here shares one model (Phase 3's design, to
avoid loading N copies of the same weights) and calls it independently, so two
cameras' detection ticks interleaving would have conflated their tracks
through that shared, positionally-indexed list. Each camera instead owns one
independent tracker, fed through a small duck-typed shim — ultralytics'
tracker classes only ever read `.xywh`/`.conf`/`.cls` off whatever object
they're given, so a real ultralytics `Boxes` object is never required.

A second, subtler bug turned up the same way: `BYTETracker.__init__`
unconditionally resets a process-global track-id counter. Naively constructing
a tracker per camera would have meant every second camera starting up (or one
camera's tracker being rebuilt after an edit) silently corrupted id uniqueness
for every camera already running — an already-assigned id could be handed out
again. Fixed by preserving and restoring the counter around construction, with
a regression test that creates ten trackers and asserts on the ids actually
issued, not just on construction succeeding.

Verified against the real ultralytics tracker classes throughout — pure
Kalman-filter/IoU math with no model weights and no network access, so there
was no reason to fake them — and then against real YOLO11n detections on
ultralytics' bundled sample photographs: the same two people in one photo and
four people in another kept stable, unique track ids across repeated ticks of
the identical frame.

194 backend tests, 85 worker tests, 10 frontend tests.

## Phase 5 — Entry/exit detection and stay time ✅

An entrance/exit is a directed line, not a polygon: every example in the spec
of a "zone" resolves to "customer crosses a threshold." `Zone` (backend) holds
two points and a side (`entry_is_positive_side`); `ZoneCrossingDetector`
(worker) tracks each person's bottom-centre reference point tick to tick and
fires a crossing only when their path actually intersects the finite
configured segment — not just its infinite extension, so someone walking near
the *line* but nowhere close to the *doorway* is never counted. Pure geometry,
no model weights: a signed cross-product side test plus a standard
orientation-based segment-intersection test, fully unit-tested with no ML
dependency at all.

Occlusion tolerance falls out of the same design as Phase 4's tracker: a
track's last known position is not cleared the instant it goes briefly
unseen, only pruned after a generous 300-tick window, so a person occluded
exactly while crossing a threshold is still correctly detected the moment
they reappear on the other side.

`CustomerSession` is a projection over the event log, same principle as every
other derived table in this product: `person_entered` opens a session (or, if
one is already open for that camera+track, treats a repeat entry near the
threshold as jitter rather than a second visit); `person_exited` closes it
with `exit_reason=line_crossing` and a duration computed from real
`occurred_at` timestamps, never frame counts. Track ids are only unique
within one camera's current AI worker process, not globally or across a
restart — the session model treats that as a fact to design around, not a bug
to hide.

Two situations never produce a `person_exited` event at all: the tracker
genuinely loses someone, and the AI worker process restarts (fresh track-id
counter, so no future event can ever again match the old session). Both look
identical from the database's side — an ACTIVE session whose `last_seen_at`
has stopped advancing — so both are handled by the same mechanism: a
`camera_stats` heartbeat now carries an `active_track_ids` roster of everyone
currently in frame, which bumps `last_seen_at` for every open session still
present (this is what lets a customer who sits still for an hour, no
crossings at all in that time, stay correctly ACTIVE); a Celery beat task,
`close_stale_sessions`, runs every `SESSION_STALE_CHECK_INTERVAL_SECONDS`
(default 60s) and ends any session whose `last_seen_at` has gone quiet for
longer than `SESSION_STALE_GRACE_SECONDS` (default 120s, several multiples of
the heartbeat interval), with `exit_reason=track_lost` and `exit_at` backdated
to the last real evidence of presence — not to "now," so a slow beat tick
never inflates a customer's measured stay.

The zone editor draws directly on the camera's last snapshot: an SVG overlay
whose `viewBox` is set to the camera's actual reported resolution (not its
on-screen pixel size), so every point captured is already in the same pixel
space the worker's crossing detector uses — no separate scale factor to get
wrong, and nothing to recompute if the browser window is resized. A short
arrow on each line, computed with the identical sign convention as
`worker/zones.py::side_of_line`, shows staff which direction currently counts
as an entry; "Flip direction" reverses `entry_is_positive_side` with one
click rather than requiring the line to be redrawn.

A live end-to-end run — real HTTP requests against a running backend, a real
logged-in session through the Next.js BFF, not mocks — caught a real bug no
unit test had: the new `Zone` list endpoint inherited the project's default
DRF pagination, so `GET /cameras/{id}/zones/` returned a `{count, results}`
envelope instead of the bare array the editor expected, and the zones page
500'd. A camera has at most a handful of lines, so pagination there was
never buying anything; fixed by setting `pagination_class = None` on
`ZoneViewSet`, with a regression test asserting the response is a plain list.
The same live run exercised the full pipeline for real: created a camera and
a zone over HTTP, ingested `person_entered`/`person_exited` events through
the actual ingest endpoint, and confirmed the resulting session's
`duration_seconds` matched the timestamps exactly (7m30s in, 7m30s out).

236 backend tests, 121 worker tests, 21 frontend tests.

## Phase 6 — Dynamic colour system ✅

The colour is a function of one thing only: how long the customer behind a
box or a row has been there. Not room occupancy, not a discrete "busy" flag —
per-session stay time, continuously interpolated across an admin-configured
list of `{seconds, colour}` stops (traffic-light default: green at 0 minutes,
amber at 30, red at 60). "Continuous, not discrete buckets" from the spec
means what it says: a session at 29:59 and one at 30:01 render almost
indistinguishably, not as a hard jump from green to amber the instant a
threshold is crossed.

The computation itself — piecewise-linear RGB interpolation between
consecutive stops, clamped at both ends — exists as two independent
implementations that must agree exactly: `apps/core/color.py` (Python) and
`frontend/src/lib/stay-color.ts` (TypeScript), one for the backend and the
dashboard's initial render, the other for the dashboard's live, per-second
tick (and, from Phase 7, the public display's box overlay). Neither imports
the other — they run in separate processes and languages — so agreement is
enforced by both test suites asserting the identical hand-computed vectors,
the same technique Phase 5 used for the zone-crossing sign convention.
Writing those vectors by hand surfaced a real pitfall before any code
shipped, not after: Python's built-in `round()` uses banker's-rounding
(round-half-to-even), while JavaScript's `Math.round()` always rounds a `.5`
up. At an exact `t=0.5` interpolation point on a half-integer channel value,
the two would have disagreed by one part in 255 — invisible on screen, but a
genuine violation of "always agree." The Python side uses an explicit
round-half-up (`math.floor(x + 0.5)`) instead of the built-in, matching
`Math.round()`'s behaviour for the non-negative values a colour channel
always is, so the two are bit-for-bit identical at every `t` — confirmed by
the shared vectors passing identically in both languages' suites, not
discovered by a mismatch after the fact.

`Cafe.stay_color_stops` is the configuration: a validated JSON list (at
least two stops, first at `seconds=0`, strictly increasing, 6-digit hex
colours only) with a sensible default so an unconfigured café still gets
correct traffic-light behaviour. It is deliberately included in the
*public*, unauthenticated café endpoint alongside branding — a colour
palette is not sensitive data, and Phase 7's kiosk browser needs it without
credentials. `CustomerSession.color` exposes the same computation as a
read-only, snapshot-at-read-time field, for anything that only reads the API
once (an analytics export) rather than ticking live.

A minimal Café settings page (`/dashboard/cafe`) lets an owner or manager
edit the stops directly — add or remove a stop, drag a colour picker, retype
a minute value — with a live CSS-gradient preview built from the exact same
interpolation function, so what they see while editing is what a customer's
box will actually look like. The Customers page (Phase 5) now colours both
its "Active now" and "Recent" stay-time cells from this same palette, ticking
the active ones every second.

A live end-to-end run (real backend, real logged-in dashboard session, no
mocks) ingested an entry event timestamped 45 minutes in the past and
confirmed the API's computed `color` matched the hand-verified test vector
for that exact duration exactly, then confirmed the dashboard's independently
computed, live-ticking colour matched the API's own value when read at the
same instant — the two only ever differed by rendering a couple of seconds
apart, which is expected and correct for a continuously interpolated value,
not a disagreement.

265 backend tests, 121 worker tests, 31 frontend tests.

## Phase 7 — Public interactive display ✅

The one real design fork: "live tracking overlay over the camera image" could
have meant actual video with boxes drawn on it, served to an unauthenticated
route. Decided against it -- a synthetic overlay instead. Every tracked
person becomes a coloured dot at their real position (the box centre, in the
camera's own pixel space), sized and coloured by the same stay-time
computation as the dashboard, on a stylised background rather than the
camera's actual pixels. `/display/<slug>` never streams video to anyone who
is not already an authenticated staff member -- the public route stays pure
geometry (a track id, an x/y, a colour), consistent with this project's
anonymous-by-design stance from Phase 1 onward, and without opening a new,
meaningfully larger exposure (live camera footage, reachable by anyone who
can guess or discover a café's slug on its own network) than the rest of the
public surface already accepts.

Four modes, cycling automatically: **normal** (the dot overlay, one card per
camera), **statistics** (current occupancy against seating capacity,
visitors today, average stay), **leaderboard** (today's five longest stays),
and **entertainment** (a rotating message set by the café). The leaderboard
and the messages both apply the same rule the overlay's design fork already
established: durations only, never a track id or a camera name. "Longest
visit today: 1h 42m" is a fun, anonymous number a customer can enjoy reading
about themselves or someone else without anyone in the room being able to
point at who it refers to; "camera 2, track 47: 1h 42m" would be the
opposite. Messages are similarly untargeted by design -- a generic rotating
line, never composed to reference a specific person's stay.

New: `apps.display`, the composition layer between what already exists
(`apps.cameras`'s live-tracks Redis cache, `apps.sessions`'s
`CustomerSession` table) and what a kiosk browser needs. Neither of those
apps needed to change or know a public display exists; `apps/display/live.py`
reads both and shapes the result. `Cafe.stay_color_stops` (Phase 6) and a new
`seating_capacity` field both moved onto the *public* café serializer for
this -- deliberate exceptions to "expose branding only," each with the same
justification: a colour palette and a venue's stated capacity are not
individually sensitive data the way tracking information is, and Phase 7's
unauthenticated kiosk needs both to render anything useful at all.

The WebSocket (`ws/display/<slug>/`) is the one Phase 1 explicitly left as a
placeholder -- `SystemStatusConsumer`'s own docstring said "live tracking
frames are added in Phase 7." Unauthenticated, like the rest of the public
surface; unlike `SystemStatusConsumer`, each connection polls its own data
independently rather than joining a shared broadcast group, because a café
display is one physical TV, not a public multi-viewer service -- there was
nothing for a pub/sub fan-out to buy here. The café itself is re-fetched
every tick rather than cached for the connection's lifetime, so an admin
changing `stay_color_stops` on the Café settings page reaches an
already-running kiosk within about a second, not only on its next reconnect
or page reload.

A real, previously-latent bug surfaced by actually building this: the
live-tracks Redis cache that already existed (Phase 4, for the staff
dashboard) had no handling at all for Redis being briefly unreachable --
`get_latest_tracks` just let the connection error propagate. For an
authenticated staff endpoint that is a tolerable, rare failure; for a public,
unauthenticated page it is worse (an unauthenticated 500 with a stack trace,
if `DEBUG` is ever left on), and for the new WebSocket it was actively
dangerous -- an uncaught exception in the tracks loop would have killed the
one thing Phase 7 was supposed to guarantee, "the WebSocket that keeps it
live." Fixed in the new code, not the old: `get_public_live_tracks` catches
`redis.RedisError` per camera and degrades to an empty overlay for that
camera, logging a warning, rather than taking the display down over a
transient restart -- exactly the kind of failure
docs/architecture.md's own table already treats as routine everywhere else.

A live end-to-end run (real Django, real Redis, a real WebSocket client, a
real Next.js dev server pointed at both) exercised the whole chain: seeded a
tracked box directly in Redis at the exact key the AI worker would write to,
confirmed the public HTTP endpoint placed the resulting dot at the box's
centre and coloured it correctly for an active session's real elapsed
duration, then opened an actual `ws://` connection and watched
`connection.established` → `display.messages` → `display.tracks` →
`display.stats` arrive in order with matching data -- not a mock, the real
consumer, the real composition layer, the real cache. That same run caught a
second, smaller gap: `docker-compose.yml`'s `frontend` service set
`NEXT_PUBLIC_WS_URL` as a runtime environment variable, but Next.js inlines
`NEXT_PUBLIC_*` values into the client bundle at *build* time -- the browser
would have been shipped `ws://localhost:8000` regardless of what a real
deployment's `.env` said, silently working only for whoever's browser
happened to be running on the café server itself. Fixed by passing it
through `build.args` instead, where the Dockerfile was already set up to
receive it.

311 backend tests, 121 worker tests, 31 frontend tests.

## Phase 8 — Analytics dashboard ✅

One rollup table, `DailyStat` — one row per café per *local* calendar day —
is the whole answer to "scheduled rollups so a year of history does not mean
a slow query." A year is at most ~366 rows per café, trivially fast to fetch
and aggregate client-side for any range a dashboard would ask for, so there
is no second rollup granularity: "weekly" and "monthly" trends are just a
wider date range over the same table, not a separately maintained aggregate.
`apps/analytics/rollups.py::compute_daily_stat` is the one function that
reads raw `CustomerSession` rows for analytics purposes at all — the
scheduled task, the API, and the dashboard all read `DailyStat` instead.

"Peak hours and days" turned out to be two genuinely different questions,
not one, and both are answered rather than picking one and hand-waving the
other. `hourly_entries` buckets by local hour of *arrival* — "when do people
show up" — which is simple, defensible, and cheap: an entry-count histogram,
nothing more. `peak_occupancy` is a real concurrent-occupancy peak instead,
from a sweep over every session's `[entry_at, exit_at)` interval, because
those two numbers can genuinely disagree — a handful of long-staying
customers can outlast a short, sharp morning rush in raw headcount even
though the rush wins on arrivals. Both are exposed; neither substitutes for
the other.

Two moving parts keep `DailyStat` current without ever touching raw session
rows on a dashboard request: `apps.analytics.tasks.refresh_daily_stats`
(Celery beat, every `ANALYTICS_ROLLUP_INTERVAL_SECONDS`, default 15 minutes)
recomputes *today* — always partial, `is_final=False` until the day is
actually over — and *yesterday*, but only if it is not yet final, a safety
net for a beat tick landing exactly at local midnight. Neither one ever
walks further back than that; a fresh Phase 8 install on a café with months
of pre-existing `CustomerSession` history needed a second path, `manage.py
backfill_daily_stats`, a one-time (or `--force` re-run after fixing a rollup
bug) command a technician runs during upgrade.

`DailyStatSerializer` exposes `total_stay_seconds` and `ended_session_count`
alongside the already-computed `average_stay_seconds`, not just the average
itself — an average of five days' averages is not the same number as the
correctly-weighted average across all five days combined, and would silently
misweight a slow Tuesday the same as a busy Saturday. `src/lib/analytics.ts`
does that weighted combination once, tested against a hand-worked example
that would have failed under the naive approach, and both the frontend's
aggregation and the backend's own per-day computation share one further
subtlety worth stating plainly: a JS `Date` parsed from a bare `YYYY-MM-DD`
string reads as UTC midnight per the ECMAScript spec, so asking it for a
day-of-week in a timezone behind UTC can silently answer with the *previous*
day — guarded against with an explicit local-midnight suffix before that
date ever reaches `.getDay()`.

Charts are hand-rolled — flexbox bars with percentage heights, not a
charting library — because there was no real coordinate space to justify
SVG (unlike the zone editor or the display's overlay, which place points in
an actual camera's pixel space) and no existing chart dependency in a
frontend that has otherwise stayed to `next`/`react` alone.

A live end-to-end run (real Django, real sqlite, a five-day seeded history
with genuinely overlapping visits) exercised the whole chain: backfilled six
days of rollups, confirmed the API's `average_stay_seconds`,
`longest_stay_seconds`, `hourly_entries`, and `peak_occupancy` (including its
timestamp) all matched hand-computed expectations for data with real
overlap, then confirmed the dashboard's rendered stat tiles showed the
correctly range-aggregated numbers computed from that same data by
`summarizeDailyStats` running client-side.

343 backend tests, 121 worker tests, 39 frontend tests.

## Phase 9 — Table analytics ✅

A table is a rectangle, not a polygon — the same "resolve to the simplest
shape the spec's own examples actually need" reasoning Phase 5 applied to
`Zone`, restated for area instead of a threshold. `TableZone` (backend) holds
an axis-aligned `x1,y1,x2,y2` box; the table editor draws it the same
click-and-drag-on-an-SVG-overlay way the zone editor draws a line, just
normalizing the drag into a rectangle instead of keeping two raw points.

Occupancy detection could not reuse Phase 5's reference-point technique,
because a table is an area to be covered, not a line to be crossed. A seated
person's detected box mostly shows upper body and shoulders — furniture
occludes the rest — so `TableOccupancyDetector` (worker) instead measures how
much of a table's rectangle is actually covered: each tracked box is clipped
to the table, the *union* area of every person's clipped box overlapping that
table is computed exactly (a coordinate-compression grid, so two people
jointly covering one table are never double-counted where their boxes
overlap each other), and the resulting fraction is compared against
`OVERLAP_FRACTION_THRESHOLD` (0.15). A debounced state machine — three
consecutive covered ticks to confirm occupied, five consecutive uncovered
ticks to confirm released — absorbs single-tick detector noise without either
missing a real, brief occupancy or flickering on momentary occlusion.

That heuristic is reliable from directly overhead and only an approximation
from the side — a person standing at a table can register the same as one
seated at it when the camera is wall-mounted. Rather than quietly overclaim
one confidence level for both, `Camera.mount_type` (unknown / overhead /
wall) is new, admin-set, and surfaced honestly: the table editor shows an
explicit caveat banner for anything not `overhead`, including the unset
default, rather than presenting every camera's table occupancy as equally
trustworthy.

`TableSession` is a projection over `table_occupied`/`table_released` events,
the same principle every derived table in this product follows — and the
same heartbeat-and-stale-closing pattern Phase 5 built for customer sessions,
reused rather than reinvented: `camera_stats` now also carries an
`occupied_table_ids` roster alongside Phase 5's `active_track_ids`, bumping
`last_seen_at` for every table still covered so a table occupied for an hour
without a discrete event stays correctly ACTIVE, and `close_stale_table_sessions`
(Celery beat) closes anything whose roster heartbeat goes quiet — a worker
crash or restart never leaves a table stuck occupied forever.

Utilisation and turnover deliberately did *not* get a Phase 8-style rollup
table. A café has a handful of tables, not months of individual customer
visits — `apps/tables/stats.py::table_utilization` sweeps raw `TableSession`
rows for whatever range is asked for, on demand, which is cheap enough
without a maintained aggregate. It reports *every* currently configured
table, including one with zero sessions in range, so a manager sees a
complete picture of the floor rather than silently-missing rows for a table
that simply hasn't turned over yet.

A full-suite run (not just the new app's own tests) caught a real regression
before it shipped: two pre-existing tests in `apps/events/tests/test_ingest.py`
had picked `EventType.TABLE_OCCUPIED`/`TABLE_RELEASED` as "safe, currently
unused" event types to register throwaway test projections on, and cleaned up
with a blind `.clear()` on that event type's whole handler list. Once this
phase registered real projections on those same two types, running the full
backend suite — not just `apps/tables` in isolation — showed those old tests
silently deleting the real projections for the rest of the test session,
breaking unrelated tests with confusing `TableSession.DoesNotExist` errors
far away from the actual cause. Fixed twice over: the throwaway tests moved
to event types nothing else claims, and more robustly, every place that
manipulates the projection registry for a test now snapshots and restores the
exact prior handler list instead of clearing it — a `.clear()` on a shared
registry is never the right cleanup, no matter how "unused" the key looks at
the time.

A live end-to-end run (real Django on sqlite, a real Next.js dev server, a
real logged-in dashboard session) exercised the whole chain: seeded an
overhead camera with two tables and a wall-mounted camera with one, created
an active and two ended `TableSession` rows directly, then confirmed over
HTTP that the worker-config feed correctly included both tables' rectangles,
the utilisation endpoint's occupied-seconds/turnover/percentage matched
hand-computed expectations for the seeded range, and — in the browser-facing
pages themselves — that the new Tables dashboard page rendered the live
occupied table with a ticking duration and the two ended sessions with their
correct release reasons, that the overhead camera's table editor showed no
caveat banner while the wall-mounted one did, and that the dashboard's
"Tables" navigation entry was now a live link rather than the disabled
"soon" placeholder it had been since Phase 1.

401 backend tests, 153 worker tests, 39 frontend tests.

## Phase 10 — Production hardening ✅

A security review came first, not last, because it changes what "hardening"
even means for the rest of the phase: a manual pass over authentication,
authorization, injection surface, secrets handling and container posture
(the full write-up is [docs/security-review.md](security-review.md)) found
the codebase's existing decisions — Argon2 hashing, httpOnly-cookie tokens,
constant-time worker-token comparison, per-café queryset scoping asserted by
a test in every app, non-root Docker users throughout — already sound, and
surfaced exactly two real gaps worth fixing. Both were fixed. `Cafe.logo`
had no upload size cap (`FILE_UPLOAD_MAX_MEMORY_SIZE` only decides where an
upload buffers while streaming in, not how large it may be) — closed with
`validate_logo_size`, a model field validator in the same shape
`stay_color_stops` already used for `validate_color_stops`, so it is
enforced everywhere the field is written. And `sentry-sdk` had been a
declared `requirements/prod.txt` dependency with no code behind it since
early in the project — a declared-but-unwired capability being exactly the
kind of overclaiming this project's documentation avoids everywhere else it
speaks in confident terms about what actually runs, it got wired up in
`config/settings/production.py`, strictly opt-in behind an unset-by-default
`SENTRY_DSN` so the local-first, no-internet-required guarantee holds for
every install that doesn't ask for it, with `include_local_variables=False`
specifically because a stack frame can hold an RTSP URL or a raw request
body and Sentry's own capture path does not run through
`RedactSecretsFilter`. One more finding was reviewed and *deliberately left
alone*, written down rather than silently accepted: refresh-token
blacklisting is off, a decision already made and documented in an earlier
phase (`LogoutView`'s own docstring) for a sound reason — a blacklist table
would add a database write to every token refresh, for every staff member,
all day, to defend against a threat (a stolen refresh token specifically)
already bounded by a 30-minute access-token lifetime. This review confirmed
that trade-off rather than reversing it on its own authority.

docs/privacy.md's Retention section had promised, since an earlier phase,
that "a retention policy with automatic pruning arrives in Phase 10" for the
raw `TrackingEvent` log -- an append-only table that otherwise grows
forever. That promise got checked against what this phase actually shipped
partway through, found not yet true, and fixed rather than quietly edited
away: `apps.events.prune_old_events`, a Celery beat task in the same shape
as `close_stale_sessions`/`close_stale_table_sessions`, deletes any
`TrackingEvent` row past `EVENT_RETENTION_DAYS` (default 90, 0 disables it).
Safe by the same property Phase 8's rollup and Phase 5/9's sessions already
rest on -- every durable figure the product reports is a projection computed
and stored at ingest time, not read back from raw events later, so pruning
only gives up the ability to *recompute* a projection for a given day, never
a number a café can currently see.

Backups are a real, tested round-trip, not a documented one-liner nobody has
run. `scripts/backup.sh` dumps PostgreSQL with `pg_dump --clean --if-exists`
(so the dump is self-contained and `scripts/restore.sh` can load it into a
database that already has data, not just an empty one), gzips it, and prunes
anything past `BACKUP_RETENTION_DAYS`; `scripts/restore.sh` refuses to run
without the operator typing the database's exact name to confirm, unless
`--yes` is passed for a scripted runbook. Both were live-verified against a
real PostgreSQL container: seed two rows, back up, delete them and insert a
different one, confirm restore without the right confirmation is refused
and touches nothing, then confirm restore with the right confirmation brings
back exactly the original two rows and nothing else — and separately, that
a deliberately-aged backup file actually gets pruned on the next run.

Log rotation and resource limits answer the same underlying question --
"what stops a small problem from becoming an outage on a machine nobody is
watching" -- for the two resources most likely to run away unattended: disk
and memory. Every long-running container now sets a 10 MB × 5 file
`json-file` logging cap (Docker's default keeps logs forever, which on a
café mini PC is a slow disk leak, not a log), and every container in
`docker-compose.yml` has a `deploy.resources.limits` ceiling sized to
docs/hardware.md's stated minimums -- a leak or a runaway process gets
OOM-killed and restarted inside its own container rather than able to
starve camera capture or the database on the same small machine. The AI
worker is the one service that could not get a fixed number: docs/hardware.md
sizes that same process anywhere from a 4-core mini PC (1 camera) to a
12+-core tower (16 cameras, two worker processes), so its limit is
env-overridable (`AI_WORKER_CPU_LIMIT`/`AI_WORKER_MEMORY_LIMIT`) rather than
a value baked into the compose file that a larger install would have to
hand-edit around.

systemd units (`deployment/systemd/`) give every service a non-Docker
equivalent for an install that does not want a container runtime at all --
backend, event consumer, Celery worker, Celery beat, frontend, AI worker, a
one-shot migrate unit run by hand on install and upgrade (the same reason
`docker-compose.yml` gives `migrate` its own service rather than folding it
into `backend`: a schema change is a step a human runs once, never
something a long-running unit should retry on its own), and a nightly
backup timer. Each runs as a dedicated non-root user with
`NoNewPrivileges`, `ProtectSystem=strict` and `ProtectHome=true` -- the same
non-root, locked-down posture the three Docker images already had (`USER
appuser` / `nextjs` / `worker`), restated in systemd's own vocabulary
instead of a container boundary, so neither deployment path is the
"hardened" one and the other isn't.

The upgrade procedure that used to be two lines in docs/installation.md
("git pull; docker compose up -d --build") is now a documented, reasoned
sequence in docs/production.md -- back up, pull, rebuild, migrate, restart,
verify, in that specific order, because a backup taken *after* a bad
migration already ran is not useful, and a rollback path (restore the
pre-upgrade backup, check out the previous commit) exists precisely because
step one is never skippable.

409 backend tests, 153 worker tests, 39 frontend tests. Most of Phase 10 is
infrastructure with no unit-test surface of its own -- a resource limit, a
logging driver, and a systemd unit file are not Python or TypeScript
functions to assert on -- so the real code this phase added (the logo size
cap, the Sentry wiring, the event-retention task) each carry the same test
rigor as any other phase, and everything else was verified the way
infrastructure has to be: for real, against a real running PostgreSQL
container, not mocked.

## Phase 11 — Final QA and productisation ✅

The end-to-end review this phase opened with found no dead code, no stray
TODOs, no broken documentation cross-links, and every URL this project's
own docs claim to expose actually resolves to a real Django route (checked
mechanically, not by memory) — ten phases of insisting on real, tested,
live-verified work rather than stubs paid off exactly where it should: at
the point of trying to find something wrong.

What the review *did* find were three places where a backend had been
built, tested, and documented in an earlier phase, and then never actually
wired to a page a café's staff could reach — the gap between "the API
exists" and "a café can use it," which no amount of backend testing alone
would ever surface. **Display messages** (Phase 7's entertainment-mode
rotation) had a fully tested `DisplayMessageViewSet` and even its BFF
routes already written, and no dashboard page ever called them — the nav
item had sat behind a "soon" badge since the phase that built its backend.
**Staff account management** (`/api/v1/auth/users/`) has existed since
Phase 1's own architecture, complete with role scoping and a
self-deactivation guard, with no page to reach it at all — adding a second
staff account meant a technician running a management command by hand.
**Self-service password change** (`/api/v1/auth/password/`) was the same
story: tested since Phase 1, never once called from the dashboard, despite
the bootstrap command's own first-run output telling every new owner to
"change it after your first sign-in" with no page for them to do that on.
All three were finished properly, not stubbed: real pages, real BFF
routes, and live-verified end to end against a running backend --
including the parts that only show up under real use, like confirming an
owner really cannot deactivate their own account through the UI, and that
a freshly reset password actually works for login while the old one no
longer does.

Closing that last gap surfaced a real design question with no self-service
answer: what happens when someone forgets their password, on a product
that deliberately has no email service to send a reset link through (spec
§16)? `UserViewSet.reset_password`, a new owner/manager-only action, in
the same "generated, shown once, never logged" shape as `manage.py
bootstrap`'s own generated owner password -- recovery is an admin action
here, not a self-service email flow, because the latter would mean either
compromising the local-first guarantee or building an SMTP dependency this
product has never needed anywhere else.

The review also turned up two settings that had been real and load-bearing
since early phases -- `ALLOW_VIDEO_RECORDING` (§26) and `BEHIND_TLS_PROXY`
-- but were never actually listed in `.env.example`, the one file meant to
be the complete, honest inventory of everything a deployment can configure.
An operator reading `.env.example` top to bottom would never have learned
either existed. Fixed by adding both, with the same reasoning their code
comments already carried.

**Installation rehearsal surfaced a genuine bug, not just confirmation that
things already worked.** Attempting a from-scratch `docker compose up -d
--build` failed immediately with a gRPC session-key crash, traced to
Compose's newer "bake" build driver choking on this project's own directory
name -- `Smart Café Vision` is not ASCII, and neither is `café` itself, the
word this entire product is named after. `COMPOSE_BAKE=false` does not
avoid it in the affected Compose version; the confirmed workaround (build
each image with plain `docker build`, bypassing the broken bake path
entirely, then `docker compose up -d` without `--build`) is now documented
in installation.md's troubleshooting section, alongside a note that a café
whose own name, or whose owner's name, is not ASCII is exactly the
demographic most likely to hit this by installing into a path built from
that name. A concurrent, unrelated flakiness reaching a public Debian
package mirror prevented finishing a full from-scratch image build during
this phase to confirm the workaround end-to-end against a live build --
noted honestly rather than silently assumed fixed; the bake crash itself
was reproduced twice, identically, independent of that network issue, so
the finding and its workaround stand regardless.

The last deliverable is [docs/owner-guide.md](owner-guide.md) -- every
other document in this project, including this one, assumes the reader
can read a Dockerfile. This one deliberately assumes the opposite: it is
written for whoever runs the café, not the computer, and says nothing
about Docker, APIs, or environment variables anywhere in it. Writing it
honestly required checking every claim against what the product actually
does rather than what it was supposed to do -- an early draft's roles
table invented a behavioural difference between `staff` and `viewer` that
does not exist in the permission code (both are simply read-only), caught
and corrected before publishing rather than after a café owner read it and
believed it.

412 backend tests, 153 worker tests, 39 frontend tests -- up from 401, 153,
and 39 at the close of Phase 10, entirely from closing the three wiring
gaps and adding password-reset. Every test suite, `ruff check`, and the
migration-drift check all pass clean as of this phase's close.

This is the last of the eleven phases. Smart Café Vision is a complete,
locally-run, anonymous occupancy and stay-time analytics system for cafés,
end to end: RTSP cameras in, YOLO detection and multi-object tracking,
entry/exit and table-occupancy derivation, a dynamic stay-time display, a
public kiosk screen, historical analytics, and the production hardening
and operator documentation a real installation actually needs to run
unattended. What comes after this is ordinary maintenance -- dependency
updates, real-world bug reports, hardware-specific tuning -- not a
twelfth phase.
