# Smart Café Vision

Local-first computer vision for cafés and restaurants. It uses the venue's
existing IP cameras to measure how busy the room is and how long people stay,
and turns that into two things: an analytics dashboard for the owner, and a
playful public display for the customers.

**Anonymous by design.** No face recognition, no identities, no stored footage.
The system counts people and measures durations using temporary track numbers
that are discarded when a person leaves. See [docs/privacy.md](docs/privacy.md).

**Local by design.** Video never leaves the café's own network. Detection,
tracking, timing, the database and the dashboard all keep working with the
internet unplugged.

---

## Current status

Phases 1–11 of 11 are complete. What that means concretely:

| Component | State |
|---|---|
| Backend API, auth, roles, multi-café model | working |
| PostgreSQL schema + migrations | working |
| Redis Streams event bus (worker → backend) | working |
| Event ingest, deduplication, audit log | working |
| Health and readiness monitoring | working |
| Admin dashboard shell + sign-in | working |
| Camera management (add/edit/delete, encrypted credentials) | working |
| RTSP connection testing (specific failure reasons) | working |
| Camera capture with automatic reconnection | working |
| Live MJPEG preview, proxied through the backend | working |
| YOLO person detection (CPU or GPU, graceful capture-only fallback) | working |
| Multi-object tracking (ByteTrack / BoT-SORT, anonymous track ids) | working |
| Per-camera live and periodic detection/tracking statistics | working |
| Entrance/exit line editor, drawn on the camera's own snapshot | working |
| Entry/exit crossing detection and `CustomerSession` stay time | working |
| Session recovery after a worker restart / a lost track | working |
| Dynamic, continuously-interpolated stay-time colour | working |
| Café settings page (stay-colour thresholds, branding, privacy notice) | working |
| Public display message rotation, managed from the dashboard | working |
| Staff account management (add/deactivate, change role) | working |
| `/display/<slug>` public kiosk page (4 auto-cycling modes) | working |
| Live tracking overlay, occupancy stats, anonymous leaderboard | working |
| WebSocket push to the public display | working |
| Analytics dashboard (daily rollups, trends, peak hours/occupancy) | working |
| Table editor, drawn on the camera's own snapshot | working |
| Table occupancy detection and `TableSession` history | working |
| Table utilisation and turnover report | working |
| Docker Compose stack | working |
| Database backup / restore scripts | working |
| Event log retention (`EVENT_RETENTION_DAYS`, scheduled pruning) | working |
| Log rotation, per-container resource limits | working |
| systemd units for a non-Docker install | working |
| Documented, verified upgrade procedure | working |
| Security review | working |
| Operator's guide for a café owner (not a developer) | working |

Every customer's box on the public display and their row on the Customers
page show the same colour for the same stay duration: `apps/core/color.py`
and `frontend/src/lib/stay-color.ts` are independent, cross-verified
implementations of one interpolation, configurable per café under Café
settings. The display itself never shows actual camera video, even to an
unauthenticated viewer — every tracked person is a synthetic, coloured dot
at their real position, and the leaderboard/messages never name a track id
or camera; see [docs/architecture.md](docs/architecture.md).

Analytics reads a `DailyStat` rollup table, not raw sessions, so a dashboard
request never scans a year of history to answer "what were our busiest
hours" — see the roadmap's Phase 8 write-up for the rollup and the peak-hours
/ peak-occupancy distinction it draws.

The dashboard's Customers page and the `/api/v1/sessions/` endpoint report
real, derived sessions now — an entrance/exit line has to be drawn on a
camera (Cameras → Zones) before that camera contributes any of them, since
without a line there is nothing to derive a session from.

Table occupancy is honest about what a camera's angle can actually support:
a table drawn as a rectangle on a directly-overhead camera gets reliable
occupancy, one on a wall-mounted camera gets an approximation, and the table
editor says which — see `Camera.mount_type` and the roadmap's Phase 9
write-up.

Production hardening (Phase 10) is done: backups
([docs/production.md](docs/production.md#backups)) are live-verified against
a real database round-trip, not just written and hoped for; every container
has a log-rotation and resource-memory ceiling; a non-Docker install can run
entirely under systemd (`deployment/systemd/`); and a manual security review
([docs/security-review.md](docs/security-review.md)) fixed what it found
(an unbounded logo upload, a declared-but-unwired error-tracking dependency)
and wrote down, with reasoning, what it deliberately left alone.

Phase 11 closed the project out: an end-to-end review found three
backends that had been built and tested in earlier phases but never
actually wired to a page (managing display messages, managing staff
accounts, and changing your own password) — all three finished properly
and live-verified, not left as gaps. It also found and documented a real
bug in Docker Compose's newer build path that crashes on this project's
own directory name (`café` is not ASCII), and closed with
[docs/owner-guide.md](docs/owner-guide.md) — the one document in this
project written for whoever runs the café, not whoever installed the
software.

All eleven phases are now complete. Full plan, including the detailed
write-up for each phase: [docs/roadmap.md](docs/roadmap.md).

---

## Quick start (Docker)

```bash
cp .env.example .env
python scripts/generate_keys.py      # fills in the secrets

docker compose up -d --build
docker compose run --rm backend python manage.py bootstrap \
    --email you@example.com --cafe-name "My Café" --timezone Europe/Berlin
```

The bootstrap command prints a generated password once. Then open
<http://localhost:3000> and sign in.

To check the whole event path end to end before any camera exists:

```bash
docker compose exec backend python manage.py emit_test_event
docker compose logs event-consumer --tail 20
```

Detailed instructions, including running without Docker:
[docs/installation.md](docs/installation.md).

---

## Repository layout

```
backend/       Django + DRF + Channels. API, auth, event ingest, analytics.
ai_worker/     Separate process for camera capture and inference.
frontend/      Next.js dashboard and the /display/<slug> public kiosk page.
shared/        scv-contracts: the event schema both sides install.
deployment/    nginx configuration.
docs/          Architecture, installation, privacy, hardware, roadmap.
scripts/       Operational helpers.
```

The event contract lives in `shared/` as a real installed package rather than a
copied file, so a change to an event shape breaks both sides at install time
instead of silently at 2am in a café.

---

## Documentation

- [Owner's guide](docs/owner-guide.md) — for whoever runs the café, not the computer
- [Architecture](docs/architecture.md) — how the pieces fit and why
- [Installation](docs/installation.md) — Docker and bare-metal setup
- [Development](docs/development.md) — running tests, project conventions
- [Privacy](docs/privacy.md) — what is and is not stored, GDPR notes
- [Hardware](docs/hardware.md) — what to buy for 1, 4, 8 or 16 cameras
- [GPU setup](docs/gpu-setup.md) — NVIDIA Container Toolkit, CPU fallback
- [Production](docs/production.md) — backups, log rotation, resource limits, systemd, upgrading
- [Security review](docs/security-review.md) — the Phase 10 hardening review
- [Roadmap](docs/roadmap.md) — the eleven phases

API reference is generated from the code: <http://localhost:8000/api/docs/>.

---

## Licence

Not yet chosen. Treat as all rights reserved until stated otherwise.
