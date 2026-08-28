# API

Interactive reference, generated from the code:

- Swagger UI — <http://localhost:8000/api/docs/>
- ReDoc — <http://localhost:8000/api/redoc/>
- OpenAPI schema — <http://localhost:8000/api/schema/>

Everything the product exposes lives under `/api/v1/` so the whole surface can
be versioned at once. Operational endpoints sit outside it.

---

## Authentication

JWT bearer tokens. The dashboard does not handle them directly — its Next.js
server keeps them in httpOnly cookies and attaches them server-side.

```http
POST /api/v1/auth/login/
Content-Type: application/json

{"email": "owner@example.com", "password": "..."}
```

```json
{
  "access": "eyJhbGciOi...",
  "refresh": "eyJhbGciOi...",
  "user": { "id": "...", "email": "...", "role": "owner", "cafe_slug": "my-cafe" }
}
```

The profile comes back with the token because the dashboard needs the role and
café on its first paint to decide which navigation to render.

| Endpoint | Method | Purpose |
|---|---|---|
| `/api/v1/auth/login/` | POST | Email + password → tokens. Rate limited to 10/min |
| `/api/v1/auth/refresh/` | POST | Refresh token → new access token |
| `/api/v1/auth/logout/` | POST | Ends the client session |
| `/api/v1/auth/me/` | GET, PATCH | Current profile |
| `/api/v1/auth/password/` | POST | Change password |
| `/api/v1/auth/users/` | GET, POST | Staff accounts, scoped to the caller's café |
| `/api/v1/auth/users/{id}/` | PATCH | Change a staff account's role, name, or reactivate it (`is_active: true`) |
| `/api/v1/auth/users/{id}/deactivate/` | POST | Disable an account (blocked for your own account, see below) |
| `/api/v1/auth/users/{id}/reset-password/` | POST | Owner/manager-initiated reset (Phase 11) |

A failed login returns 401 with an identical body whether the email exists or
not, so the endpoint cannot be used to enumerate a café's staff.

There is no self-service "forgot password" flow — this product has no email
service to send a reset link through (spec §16, local-first). Recovery is an
owner/manager action instead: `reset-password` generates a random password,
sets it, and returns it in the response body exactly once (`{"password":
"..."}`) — the same "shown once, never stored, never logged" shape as
`manage.py bootstrap`'s generated owner password. `deactivate` (unlike a
plain `PATCH {"is_active": false}`, which the generic update endpoint would
otherwise allow) refuses with `self_deactivation` if the caller targets
their own account — an owner cannot accidentally lock themselves out.

### Roles

| Role | Can |
|---|---|
| `owner` | Everything, including tenant-level operations |
| `manager` | Configuration and staff management within their café |
| `staff` | Read access |
| `viewer` | Read access |

Non-superusers only ever see their own café's data. That is enforced in each
viewset's `get_queryset`, and asserted by tests.

---

## Cafés

| Endpoint | Method | Purpose |
|---|---|---|
| `/api/v1/cafes/` | GET, POST | List/create (scoped) |
| `/api/v1/cafes/{slug}/` | GET, PATCH, DELETE | Detail |
| `/api/v1/cafes/public/{slug}/` | GET | **Unauthenticated.** Branding for the display |

The public endpoint returns exactly `name`, `slug`, `logo`, `default_language`,
`privacy_notice`, `stay_color_stops`, and `seating_capacity`. It uses its own
serializer rather than a field subset, so a field added to the café model
cannot silently widen it. `stay_color_stops` (Phase 6) and `seating_capacity`
(Phase 7) are deliberate exceptions — a colour palette and a venue's stated
seating capacity are not individually sensitive the way tracking data is, and
the unauthenticated public display needs both: the first to colour a
customer's dot, the second as the denominator for an occupancy percentage in
statistics mode. Pass `?lang=fa` to select the Persian privacy notice.

### Stay-time colour (Phase 6)

```json
"stay_color_stops": [
  {"seconds": 0, "color": "#22c55e"},
  {"seconds": 1800, "color": "#f59e0b"},
  {"seconds": 3600, "color": "#ef4444"}
]
```

An ordered list of `{seconds, color}` stops driving the colour of a
customer's box on the public display and their row on the Customers page —
see docs/architecture.md for the interpolation itself. Validated on write: at
least two stops, the first always at `seconds: 0`, strictly increasing, each
`color` a 6-digit hex string. `PATCH /api/v1/cafes/{slug}/` with a new
`stay_color_stops` array to reconfigure it; a malformed list is rejected with
a 400 and a field-level message, same envelope as any other validation error.

---

## Events

| Endpoint | Method | Auth | Purpose |
|---|---|---|---|
| `/api/v1/events/` | GET | JWT | Read-only event log, filterable |
| `/api/v1/events/ingest/` | POST | `X-Worker-Token` | Worker event ingest |
| `/api/v1/events/bus-stats/` | GET | JWT | Stream depth and pending count |

### Ingest

The Redis stream is the primary path. This endpoint exists for a worker that can
reach the API but not Redis, and for manual replay during support work. Both
paths converge on the same `ingest()` function, so behaviour cannot drift.

```http
POST /api/v1/events/ingest/
X-Worker-Token: <AI_WORKER_TOKEN>
Content-Type: application/json

[
  {
    "schema_version": 1,
    "event_id": "1f0c...",
    "type": "person_entered",
    "cafe_id": "8f0d...",
    "camera_id": "a21b...",
    "worker_id": "worker-1",
    "occurred_at": "2026-08-21T18:42:13.221000+00:00",
    "payload": {"track_id": 27, "zone": "entrance"}
  }
]
```

```json
{"accepted": 1, "stored": 1, "duplicate": 0, "rejected": 0}
```

Up to 500 events per request. Redelivery is expected and safe: a repeated
`event_id` is reported as `duplicate`, not stored twice.

The token is compared in constant time. The worker is a machine on the LAN, not
a person, so it gets a service token rather than a user account — it can be
rotated independently and never inherits dashboard privileges.

---

## Cameras

| Endpoint | Method | Auth | Purpose |
|---|---|---|---|
| `/api/v1/cameras/` | GET, POST | JWT | List/create, scoped to the caller's café |
| `/api/v1/cameras/{id}/` | GET, PATCH, DELETE | JWT | Detail |
| `/api/v1/cameras/{id}/test-connection/` | POST | JWT | Run the RTSP handshake now |
| `/api/v1/cameras/{id}/snapshot.jpg/` | GET | JWT | Latest cached frame |
| `/api/v1/cameras/{id}/stream.mjpg/` | GET | JWT | Live MJPEG preview |
| `/api/v1/cameras/{id}/detections/` | GET | JWT | Near-real-time person count and boxes |
| `/api/v1/cameras/{id}/tracks/` | GET | JWT | Near-real-time tracked boxes with anonymous track ids |
| `/api/v1/cameras/{id}/zones/` | GET, POST | JWT | Entrance/exit lines for this camera |
| `/api/v1/cameras/{id}/zones/{zone_id}/` | GET, PATCH, DELETE | JWT | Detail |
| `/api/v1/cameras/{id}/tables/` | GET, POST | JWT | Table rectangles for this camera (Phase 9) |
| `/api/v1/cameras/{id}/tables/{table_id}/` | GET, PATCH, DELETE | JWT | Detail |
| `/api/v1/cameras/worker-config/` | GET | `X-Worker-Token` | Camera list with decrypted credentials, active zones, and active tables |

### RTSP credentials

`rtsp_url` must not contain a username or password — `rtsp_username` and
`rtsp_password` are separate fields, encrypted at rest
(`CREDENTIALS_ENCRYPTION_KEY`). `rtsp_password` is write-only: it is accepted
on create/update and never appears in a response. Sending a blank password on
an update leaves the stored one unchanged, so editing a camera's location does
not require retyping its password.

`mount_type` (Phase 9) is `unknown` (the default), `overhead`, or `wall` —
admin-entered, never observed. It does not change detection behaviour; it
only sets how confidently the table editor and this camera's table
occupancy should be presented, since a wall-mounted camera's box-overlap
reading is an approximation while an overhead one is reliable (see Tables
below).

### Testing a connection

```http
POST /api/v1/cameras/{id}/test-connection/
```

```json
{"status": "auth_failed", "ok": false, "message": "Authentication failed: check the username and password.", "detail": ""}
```

Runs a real RTSP `OPTIONS`/`DESCRIBE` handshake (Digest and Basic auth
supported) against whatever is currently saved on the camera — never against
values in the request body, so the test always reflects reality. It does not
decode video; a `200 OK` here means the camera accepted the connection and
credentials, not that the stream will decode correctly once the AI worker
opens it. Returns `200` on success, `502` on a specific, named failure:

| `status` | Meaning |
|---|---|
| `ok` | Connected successfully |
| `camera_offline` | Could not reach the host on the RTSP port |
| `auth_failed` | Wrong username/password, or none supplied when required |
| `stream_not_found` | The path portion of the URL is wrong |
| `stream_timeout` | The camera accepted the connection but never answered |
| `invalid_response` | The host answered, but not with RTSP (wrong port) |
| `invalid_url` | The RTSP URL could not be parsed |

### Worker config

```http
GET /api/v1/cameras/worker-config/?cafe_id=<uuid>
X-Worker-Token: <AI_WORKER_TOKEN>
```

```json
[
  {
    "id": "a21b...",
    "name": "Entrance",
    "url": "rtsp://admin:hunter2@192.168.1.64:554/live",
    "transport": "tcp",
    "zones": [
      {
        "id": "97335108-...",
        "name": "Front door",
        "point_a": [100.0, 0.0],
        "point_b": [100.0, 200.0],
        "entry_is_positive_side": true
      }
    ],
    "tables": [
      {"id": "7c5536b1-...", "name": "Table 1", "x1": 100.0, "y1": 100.0, "x2": 300.0, "y2": 300.0}
    ]
  }
]
```

The one endpoint that returns a decrypted RTSP password — gated by the
worker's service token, never by a user's JWT. Only enabled cameras for the
requested café are returned. Polled by the AI worker every
`CAMERA_POLL_INTERVAL_SECONDS` (default 15s); an edit to a camera's connection
details, its zones, or its tables takes up to that long to reach a running
worker — an edit to any of them forces the worker to reconnect that camera's
stream and rebuild its crossing and table-occupancy detectors (see
`CameraConfig.config_signature`). `zones` is reshaped for the worker
(`point_a`/`point_b` as `[x, y]` pairs, not the `/zones/` endpoint's flat
columns); `tables` keeps the flat `x1/y1/x2/y2` columns unchanged, since a
rectangle has no equivalent reshape to make. Both lists include only
`is_active` entries — a disabled zone or table is simply absent, not sent
with a flag.

### Live preview

The browser never talks to the AI worker or to Django directly for this — the
Next.js dashboard proxies both endpoints through its own server
(`/api/cameras/{id}/stream`, `/api/cameras/{id}/snapshot`), attaching the
access token server-side, consistent with the rest of the app (see
docs/architecture.md). The preview is a low, fixed-rate JPEG the worker caches
in Redis (`CAMERA_PREVIEW_INTERVAL_SECONDS`, default 0.5s) — not the frame rate
the AI processes, and not available until a camera has connected at least once.

### Detections

```http
GET /api/v1/cameras/{id}/detections/
```

```json
{
  "person_count": 2,
  "inference_ms": 47.0,
  "boxes": [{"x1": 748.5, "y1": 41.8, "x2": 1148.1, "y2": 711.1, "confidence": 0.84}],
  "updated_at": "2026-08-22T18:12:03.441000+00:00"
}
```

The most recent detection tick, read from the same Redis cache pattern as the
preview frame (`CAMERA_LATEST_DETECTIONS`, TTL-bounded) — not a database
query. `404` until a camera's AI worker has run at least one detection tick,
which never happens if the worker is running in capture-only mode (no model
loaded, or `AI_DETECTION_ENABLED=false`). Boxes are pixel coordinates against
the frame's native resolution, and confidence only — this is the detector's
raw per-tick output, with no track id and nothing that could identify who is
in the box. For track ids, see Tracks below.

For history rather than "right now", `Camera.last_person_count` and
`Camera.last_inference_ms` on the regular camera detail response are a
periodic snapshot at the same cadence as `camera_stats`, and persist across a
worker restart.

### Tracks

```http
GET /api/v1/cameras/{id}/tracks/
```

```json
{
  "track_count": 2,
  "tracks": [{"track_id": 3, "x1": 748.5, "y1": 41.8, "x2": 1148.1, "y2": 711.1, "confidence": 0.84}],
  "updated_at": "2026-08-22T18:12:03.441000+00:00"
}
```

The tracker's current view (`CAMERA_LATEST_TRACKS`, same TTL-bounded Redis
cache pattern as Detections), not a database query — `404` under the same
conditions as Detections, plus whenever the tracker itself failed to build
(rare; a per-camera failure that leaves detection running without it). `tracks`
is **not** index-aligned with Detections' `boxes`: tracking can drop an
unconfirmed detection or carry a briefly-occluded track forward with no
matching detection this tick, so treat the two as separate views, not a pair
to zip together.

`track_id` is anonymous and temporary — meaningless outside this camera's
current tracking session, and freely reused once a track is lost. It carries
no information about who the person is, only that boxes bearing the same id
across consecutive calls are believed to be the same person. Cross-camera: the
same person seen by two cameras gets two unrelated ids: no re-identification
model runs anywhere in this system (spec §26).

For history, `Camera.last_track_count` on the regular camera detail response
is a periodic snapshot at the same cadence as `camera_stats`, deliberately
tracked as a separate figure from `last_person_count` since the two can
genuinely differ during a brief occlusion.

### Zones

```http
POST /api/v1/cameras/{id}/zones/
Content-Type: application/json

{"name": "Front door", "point_a_x": 100, "point_a_y": 0, "point_b_x": 100, "point_b_y": 200}
```

```json
{
  "id": "97335108-...",
  "camera": "a21b...",
  "name": "Front door",
  "point_a_x": 100.0, "point_a_y": 0.0,
  "point_b_x": 100.0, "point_b_y": 200.0,
  "entry_is_positive_side": true,
  "is_active": true,
  "created_at": "2026-08-23T10:07:08.034Z",
  "updated_at": "2026-08-23T10:07:08.034Z"
}
```

An entrance/exit line, not a polygon: coordinates are pixels against the
camera's own frame at whatever resolution the worker last reported
(`Camera.resolution_width`/`resolution_height`) — draw one on the snapshot,
not by guessing numbers. `camera` is read-only and taken from the URL, never
from the request body. `entry_is_positive_side` picks which side of the
directed line `point_a` → `point_b` counts as an entry; `PATCH
{"entry_is_positive_side": false}` flips it without redrawing the line. Set
`is_active: false` to stop entry/exit detection on a line without deleting
it — useful while temporarily covering a doorway. This endpoint is never
paginated: a camera has at most a handful of lines.

### Tables (Phase 9)

```http
POST /api/v1/cameras/{id}/tables/
Content-Type: application/json

{"name": "Table 1", "x1": 100, "y1": 100, "x2": 300, "y2": 300}
```

```json
{
  "id": "7c5536b1-...",
  "camera": "a21b...",
  "name": "Table 1",
  "x1": 100.0, "y1": 100.0,
  "x2": 300.0, "y2": 300.0,
  "is_active": true,
  "created_at": "2026-08-24T21:11:53.585Z",
  "updated_at": "2026-08-24T21:11:53.585Z"
}
```

A table's rectangle, not a polygon — the same reasoning as Zones above,
restated for an area instead of a threshold: coordinates are pixels against
the camera's own frame, drawn on the snapshot rather than typed in. `camera`
is read-only, taken from the URL. `is_active: false` stops occupancy
detection for that table without deleting its history. Never paginated, same
reasoning as Zones.

---

## Customer sessions

| Endpoint | Method | Auth | Purpose |
|---|---|---|---|
| `/api/v1/sessions/` | GET | JWT | Current and historical sessions, scoped to the caller's café |
| `/api/v1/sessions/{id}/` | GET | JWT | Detail |

Read-only: a session is entirely derived from the event pipeline (zone
crossings and `camera_stats` heartbeats — see docs/architecture.md), never
created or edited through the API. Filterable by `?status=active|ended` and
`?camera_id=<uuid>`; ordered by `-entry_at`.

```json
{
  "id": "79bcc82c-...",
  "camera_id": "a21b...",
  "track_id": 5,
  "status": "ended",
  "entry_at": "2026-08-23T10:00:00Z",
  "entry_zone_name": "Front door",
  "exit_at": "2026-08-23T10:07:30Z",
  "exit_zone_name": "Front door",
  "exit_reason": "line_crossing",
  "duration_seconds": 450.0,
  "color": "#f59e0b",
  "created_at": "2026-08-23T10:08:04.301Z",
  "updated_at": "2026-08-23T10:08:04.426Z"
}
```

`track_id` carries the same caveat as Tracks above: meaningful only within
one camera's tracking process, freely reused across sessions and after a
worker restart — never treat it as a stable customer identity. `exit_reason`
is `line_crossing` (the person crossed a configured exit line) or
`track_lost` (no exit event ever arrived — the tracker lost them, or the
worker restarted mid-visit; a periodic task closes these once `last_seen_at`
goes stale, see docs/architecture.md), empty while `status` is `active`.
`duration_seconds` and `color` (Phase 6) on an active session are both
"as of this request" snapshots, not live values; the dashboard ticks its own
display from `entry_at` and the café's `stay_color_stops` between polls
rather than re-fetching once a second — see docs/architecture.md for the
colour computation itself.

---

## Table sessions and utilisation (Phase 9)

| Endpoint | Method | Auth | Purpose |
|---|---|---|---|
| `/api/v1/tables/sessions/` | GET | JWT | Current and historical table occupancy, scoped to the caller's café |
| `/api/v1/tables/sessions/{id}/` | GET | JWT | Detail |
| `/api/v1/tables/utilization/` | GET | JWT | Occupied-time and turnover per table over a date range |

Read-only, same principle as customer sessions: a `TableSession` is entirely
derived from `table_occupied`/`table_released` events and `camera_stats`
heartbeats, never created or edited through the API. Filterable by
`?status=active|ended`, `?camera_id=<uuid>`, and `?table_zone_id=<uuid>`;
ordered by `-occupied_at`.

```json
{
  "id": "26473cd7-...",
  "camera_id": "a21b...",
  "table_zone_id": "7c5536b1-...",
  "table_name": "Table 1",
  "status": "active",
  "occupied_at": "2026-08-24T20:54:53.599Z",
  "released_at": null,
  "release_reason": "",
  "duration_seconds": 1081.8,
  "created_at": "2026-08-24T21:11:53.601Z",
  "updated_at": "2026-08-24T21:11:53.601Z"
}
```

`camera_id` and `table_zone_id` are plain ids, not foreign keys — same
reasoning as `CustomerSession.camera_id`: a session's history must survive
its table or camera being edited or deleted. `table_name` is denormalized
at occupancy time for the same reason. `release_reason` is `cleared` (a real
`table_released` event) or `stale` (the roster heartbeat went quiet and
`close_stale_table_sessions` closed it — a worker crash or restart never
leaves a table stuck occupied), empty while `status` is `active`.
`duration_seconds` is an "as of this request" snapshot on an active session,
same caveat as customer sessions.

### Utilisation

```http
GET /api/v1/tables/utilization/?start=2026-08-24T00:00:00Z&end=2026-08-25T00:00:00Z
```

```json
[
  {
    "table_zone_id": "7c5536b1-...",
    "table_name": "Table 1",
    "camera_id": "a21b...",
    "occupied_seconds": 1089.4,
    "turnover_count": 1,
    "utilization_percent": 1.3
  }
]
```

`start`/`end` are both required, ISO-8601 datetimes — a 400 with
`invalid_range` if either is missing. Computed on demand from raw
`TableSession` rows for the requested window, not from a maintained rollup:
a café has a handful of tables, not months of visits, so there was nothing
a Phase 8-style aggregate would buy here. Every currently configured table
is reported, including one with zero sessions in range — a manager sees the
whole floor, not just tables that happened to turn over. `occupied_seconds`
clips each overlapping session to the requested window (an active session or
one that started before `start` only counts its portion inside the range);
`turnover_count` counts only sessions that *began* inside the range, so a
still-ongoing sit-down from before `start` is not double-counted as a new
turnover.

---

## Public display

| Endpoint | Method | Purpose |
|---|---|---|
| `/api/v1/cafes/public/<slug>/live/` | GET | Tracked-person positions, one entry per enabled camera |
| `/api/v1/cafes/public/<slug>/stats/` | GET | Occupancy and an anonymous, duration-only leaderboard |
| `/api/v1/cafes/public/<slug>/messages/` | GET | Active entertainment-mode messages, resolved to one language |
| `/api/v1/display-messages/` | GET, POST | Staff CRUD for the message rotation, scoped to the caller's café |
| `/api/v1/display-messages/<id>/` | GET, PATCH, DELETE | Detail |

Everything under `public/<slug>/` is unauthenticated, same principle as
`PublicCafeView` above — a kiosk browser on a café TV has no login. All three
404 for an unknown or deactivated café, same as the branding endpoint.

### Live

```json
[
  {
    "camera_id": "a21b...",
    "camera_name": "Entrance",
    "resolution_width": 1280,
    "resolution_height": 720,
    "people": [
      {"track_id": 5, "x": 640.0, "y": 400.0, "entry_at": "2026-08-23T23:53:49Z", "color": "#f59d0b"}
    ]
  }
]
```

Position is the tracked box's centre, not `ai_worker/worker/zones.py`'s
bottom-centre crossing-reference point — a different purpose (placing a dot
on screen, not testing a threshold crossing). `entry_at` is `null` for a
track with no matching ACTIVE `CustomerSession` — not yet crossed a
configured entry line, or the camera has no zone drawn on it at all — and
still appears, coloured as fresh rather than omitted, so a camera with no
zone configured yet does not look broken. Only cameras that are enabled and
have a known resolution (at least one successful connection) are included.
Never actual video or a bounding box — position and colour only; see
docs/architecture.md for why.

### Stats

```json
{
  "occupancy": 3,
  "seating_capacity": 40,
  "visitors_today": 27,
  "average_stay_seconds": 1840.5,
  "leaderboard_seconds": [4820.0, 3110.0, 2400.0, 1900.0, 1750.0]
}
```

`occupancy` counts every currently ACTIVE session regardless of when it
began (a session spanning midnight still counts). `visitors_today` and
`average_stay_seconds` use the café's own timezone to define "today", not
UTC. `leaderboard_seconds` is durations only, longest first, capped at
five — deliberately never a track id or camera name, so a fun, anonymous
number can never be used to single out who in the room it refers to.

### Messages

```json
[{"id": "1921508f-...", "text": "Did you know our beans are roasted locally?"}]
```

Pass `?lang=fa` to override the café's `default_language`. A message with no
Persian translation falls back to English rather than a blank line. Staff
manage the rotation through `/api/v1/display-messages/`, the same
authenticated shape as any other café-scoped resource (`text_en`, `text_fa`,
`is_active`) — messages are always generic, never composed to reference a
specific tracked person's stay.

---

## Analytics

| Endpoint | Method | Purpose |
|---|---|---|
| `/api/v1/analytics/daily/` | GET | Daily rollups for a date range, scoped to the caller's café |

Read-only, entirely derived — see docs/architecture.md for how it stays
current. Open to any authenticated role, not just owner/manager: this is
insight, not configuration. Filter with `?start=YYYY-MM-DD&end=YYYY-MM-DD`
(both inclusive); ordered ascending by date. Never paginated: a full year is
at most ~366 rows, and a client asking for a range wants all of it to draw
one chart, not paged through it.

```json
[
  {
    "date": "2026-08-19",
    "visitor_count": 4,
    "ended_session_count": 4,
    "total_stay_seconds": 5400.0,
    "average_stay_seconds": 1350.0,
    "longest_stay_seconds": 2700.0,
    "hourly_entries": [0,0,0,0,0,0,0,0,2,0,0,0,1,0,0,0,0,1,0,0,0,0,0,0],
    "peak_occupancy": 2,
    "peak_occupancy_at": "2026-08-19T08:10:00Z",
    "is_final": true
  }
]
```

`date` is the café's own local calendar day, not UTC. `visitor_count`
includes every session that entered that day, active or ended;
`ended_session_count` and `total_stay_seconds` travel alongside the
already-computed `average_stay_seconds` so a client combining several days
can compute a correctly-weighted average (sum of totals ÷ sum of counts)
rather than naively averaging each day's average. `hourly_entries` is an
entry-count histogram by local hour (index 0–23) — "when do people arrive."
`peak_occupancy` is a different number answering a different question — the
true concurrent-occupancy peak from a sweep over every session's presence
interval, which can genuinely exceed what the busiest single arrival-hour
would suggest. `is_final` is `false` for today (and briefly for yesterday,
right at local midnight) — those numbers are always partial and are
recomputed roughly every fifteen minutes until the day is over.

---

## Operational endpoints

Unauthenticated by design, so a monitoring probe or a technician can check them
without credentials. They expose component status only — a test asserts that no
café name or id appears in the response.

| Endpoint | Purpose |
|---|---|
| `/healthz/` | Liveness. Does no I/O; always 200 if the process is alive |
| `/readyz/` | Readiness. Full component report; 503 when something critical is down |

```json
{
  "status": "degraded",
  "environment": "production",
  "version": "0.1.0",
  "components": {
    "database": {"status": "ok", "latency_ms": 1.2},
    "redis": {"status": "ok", "latency_ms": 0.4},
    "event_stream": {"status": "ok", "stream_length": 128},
    "ai_workers": {"status": "degraded", "detail": "No AI worker has registered a heartbeat.", "workers": []}
  }
}
```

Status vocabulary is fixed: `ok`, `degraded`, `down`.

---

## Errors

One envelope everywhere, so a client needs one error path:

```json
{
  "error": {
    "code": "not_found",
    "message": "No Cafe matches the given query.",
    "detail": {"timezone": ["'Mars/Olympus' is not a valid IANA time zone."]}
  }
}
```

`detail` is present only for field-level validation errors.

| Code | Status | Meaning |
|---|---|---|
| `invalid_credentials` | 401 | Login failed |
| `not_authenticated` | 401 | Missing or expired token |
| `permission_denied` | 403 | Role is insufficient |
| `not_found` | 404 | No such object, or not visible to this café |
| `conflict` | 409 | Violates a uniqueness constraint |
| `throttled` | 429 | Rate limit |
| `batch_too_large` | 400 | More than 500 events in one ingest request |
| `event_bus_unavailable` | 503 | Redis is unreachable |

Every response carries an `X-Request-ID` header. Supplying one on the way in
preserves it, which is what lets a single frame's journey — worker → API →
websocket — be traced through one grep.

---

## WebSocket

| Path | Purpose |
|---|---|
| `ws/system/` | System status push |
| `ws/display/<slug>/` | Public display live push (Phase 7) |

Authentication is by access token in the query string (`?token=...`), because a
browser cannot set an `Authorization` header on a WebSocket handshake. Session
cookies also work for same-origin pages. An unauthenticated connection is closed
with code **4401** — browsers cannot read a 401 on a handshake, so the close
code carries the meaning.

### Public display

`ws/display/<slug>/` is unauthenticated on purpose, same as the rest of the
public display surface — closed with **4404** for an unknown or deactivated
café rather than 4401. Optional `?lang=fa` overrides the café's
`default_language` for the message payload. Every message is server push;
the client sends nothing but an optional `{"type": "ping"}` to keep
intermediaries from idling a long-lived kiosk connection out, answered with
`{"type": "pong"}`.

On connect: `connection.established`, then `display.messages` once. After
that, `display.tracks` arrives about once a second and `display.stats` about
every ten — the same shapes as the HTTP endpoints above, pushed rather than
polled, and each connection reads its own data independently rather than
subscribing to a shared broadcast (see docs/architecture.md for why that
tradeoff is fine here). The café is re-read on every tick, so a
`stay_color_stops` or message change from the dashboard reaches an
already-open kiosk within about a second.

```json
{"type": "display.tracks", "payload": [{"camera_id": "...", "people": [...]}]}
```
