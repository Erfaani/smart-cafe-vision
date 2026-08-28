# Installation

Two routes: Docker (recommended for a real café) and a local development setup.

---

## Requirements

- Docker Engine 24+ with Compose v2, **or** Python 3.12 + Node 20+ + PostgreSQL 16 + Redis 7
- 4 GB RAM minimum for the backend stack alone; see [hardware.md](hardware.md)
  for camera-dependent sizing
- No internet connection is needed at runtime — only to build the images

---

## Docker installation

### 1. Configure

```bash
cp .env.example .env
python scripts/generate_keys.py
```

`generate_keys.py` fills in `DJANGO_SECRET_KEY`, `AI_WORKER_TOKEN` and
`CREDENTIALS_ENCRYPTION_KEY`. It is idempotent and never overwrites a value that
is already set — re-running it will not make stored camera passwords
undecryptable.

Then edit `.env`:

```bash
POSTGRES_PASSWORD=<something other than the default>
DJANGO_SETTINGS_MODULE=config.settings.production
DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1,backend,192.168.1.50   # the server's LAN IP
FRONTEND_ORIGIN=http://192.168.1.50:3000
NEXT_PUBLIC_WS_URL=ws://192.168.1.50:8000
```

The LAN IP matters: staff will open the dashboard from a phone or a back-office
PC, and the café TV will open the display page. `localhost` only works on the
server itself.

### 2. Start

```bash
docker compose up -d --build
```

This starts PostgreSQL, Redis, the API, the event consumer, Celery and the
dashboard. Migrations run automatically in the `migrate` service.

Verify:

```bash
curl http://localhost:8000/readyz/
```

`ai_workers` reporting *degraded* is correct at this point — no worker exists
until Phase 2/3 are installed.

### 3. Create the café and the first account

```bash
docker compose run --rm backend python manage.py bootstrap \
    --email you@example.com \
    --cafe-name "My Café" \
    --timezone Europe/Berlin \
    --language en \
    --seating-capacity 40
```

The generated password is printed **once**. Save it, then change it after your
first sign-in.

Re-running this command with the same arguments is safe: it will not create a
second café or reset the password.

### 4. Sign in

<http://localhost:3000> (or the LAN IP).

### 5. Verify the event pipeline

Before any camera exists, confirm the whole path works:

```bash
docker compose exec backend python manage.py emit_test_event
docker compose logs event-consumer --tail 20
```

You should see the event stored. This is also the fastest way to tell, later,
whether a problem is in the worker or in the backend.

### Optional: one port for everything

```bash
docker compose --profile proxy up -d
```

nginx then serves the dashboard, API, WebSocket and display on port 80.

---

## Local development installation

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -r backend/requirements/dev.txt   # Linux/macOS: .venv/bin/python
.venv/Scripts/python -m pip install -e ./shared

cd frontend && npm install && cd ..

cp .env.example .env
python scripts/generate_keys.py
```

Start PostgreSQL and Redis (Docker is easiest even in development):

```bash
docker compose up -d postgres redis
```

Point the app at them and run it:

```bash
# .env
POSTGRES_HOST=127.0.0.1
REDIS_URL=redis://127.0.0.1:6379/0
DJANGO_SETTINGS_MODULE=config.settings.development
```

```bash
cd backend
../.venv/Scripts/python manage.py migrate
../.venv/Scripts/python manage.py bootstrap --email you@example.com
../.venv/Scripts/python manage.py runserver 0.0.0.0:8000
```

In two more terminals:

```bash
cd backend && ../.venv/Scripts/python manage.py consume_events
cd frontend && npm run dev
```

`runserver` serves WebSockets too — daphne is installed and takes over the dev
server, so development matches production behaviour.

### Without PostgreSQL

For quick experiments only:

```bash
DATABASE_URL=sqlite:///dev.sqlite3
```

Never in production: the analytics queries in Phase 8 rely on PostgreSQL.

---

## AI worker

```bash
docker compose -f docker-compose.yml -f docker-compose.ai.yml up -d ai-worker
```

The worker needs the café's UUID:

```bash
docker compose exec backend python manage.py shell -c \
  "from apps.tenants.models import Cafe; print(Cafe.objects.first().id)"
```

Put it in `.env` as `CAFE_ID`. Within ten seconds the health panel should move
the AI worker component from *degraded* to *ok*.

For GPU acceleration see [gpu-setup.md](gpu-setup.md).

---

## Adding a camera

1. In the dashboard, go to **Cameras → Add camera**.
2. Fill in:
   - **RTSP URL** — no username or password in it, e.g.
     `rtsp://192.168.1.64:554/Streaming/Channels/101`. Consult the camera
     vendor's documentation for the exact path; Hikvision and Dahua both use
     `/Streaming/Channels/<N>01` for the main stream.
   - **Username / Password** — separate fields, encrypted at rest.
   - **Transport** — TCP is recommended and the default; UDP can lower latency
     on a network known to handle it well, at the cost of tolerating dropped
     packets less gracefully.
3. Click **Test** before saving. It runs a real RTSP handshake and reports a
   specific reason on failure — *camera offline*, *authentication failed*,
   *stream not found*, *stream timeout* — rather than a generic error.
4. Save, then enable it. Within `CAMERA_POLL_INTERVAL_SECONDS` (default 15s)
   a running AI worker picks it up and starts capturing.
5. **Live cameras** shows a preview once the worker has connected. The
   preview is a low-rate cached JPEG, not the camera's native frame rate.

**Finding the right RTSP path.** If the vendor's default path does not work, an
ONVIF device discovery tool or `ffprobe rtsp://user:pass@host:554/` from a
terminal on the same network as the camera will report the working path.

**Editing an existing camera.** Leave the password field blank to keep the
current one — the form only overwrites it when you type a new value.

---

## Upgrading

```bash
scripts/backup.sh          # always back up first
git pull
docker compose up -d --build
```

The `migrate` service applies schema changes automatically on start. Full
upgrade procedure, including what to do if it goes wrong, and the
non-Docker (systemd) equivalent: [production.md](production.md#upgrading).

---

## Production installs

Backups, log rotation, resource limits, a non-Docker (systemd) option, and
the upgrade procedure above are all covered in
[production.md](production.md). A security review of this project is in
[security-review.md](security-review.md).

---

## Troubleshooting

**Sign-in does nothing, no error.** The session cookie was rejected. On a plain
HTTP LAN install, leave `BEHIND_TLS_PROXY` unset — setting it marks cookies
`secure`, and a browser silently drops those over HTTP.

**`DisallowedHost` in the backend logs.** Add the address you are using to
`DJANGO_ALLOWED_HOSTS`.

**Dashboard loads but every panel is empty.** Check
`docker compose logs backend`. Usually `CORS_ALLOWED_ORIGINS` does not include
the origin the browser is actually using.

**`/readyz/` says the event stream is degraded.** The consumer is falling behind
the worker. Check `docker compose logs event-consumer`; on a small machine this
usually means the inference rate is set too high for the hardware.

**`docker compose up -d --build` fails immediately with `failed to dial
gRPC: ... header key "x-docker-expose-session-sharedkey" contains value
with non-printable ASCII characters`, before any image starts building.**
This is a real bug in Docker Compose's "bake" build driver (confirmed
against Compose v5.4.0 / buildx v0.36), not a problem with this project's
Dockerfiles — it crashes whenever the project directory's own path contains
a non-ASCII character, which for this product is a genuinely likely thing
to hit: `café` itself is not ASCII, and an install path built from a
venue's own name (`C:\Café Roma\smartcafevision`) or an owner's name
(`/home/José/...`) triggers it just as easily as this repository's own
`Smart Café Vision` folder name does. `COMPOSE_BAKE=false` does **not**
avoid it in the affected version — bake is not optional there. Two real
workarounds, in order of preference:

1. Move (or clone) the install to a path with no accented or non-ASCII
   characters, then `docker compose up -d --build` normally.
2. If the path cannot change, bypass `docker compose build` entirely: build
   each image with plain `docker build` (which does not go through the
   broken bake path) and tag it to match what Compose expects, then start
   the stack without `--build`:

   ```bash
   docker build -f backend/Dockerfile -t smartcafe-backend .
   for svc in celery celery-beat event-consumer migrate; do
     docker tag smartcafe-backend "smartcafe-$svc"
   done
   docker build -f frontend/Dockerfile -t smartcafe-frontend \
     --build-arg NEXT_PUBLIC_WS_URL=${NEXT_PUBLIC_WS_URL:-ws://localhost:8000} ./frontend

   docker compose up -d   # no --build -- the images above already exist
   ```

   Repeat the `docker build`/`docker tag` steps after every `git pull`
   during an upgrade, in place of `docker compose up -d --build`'s normal
   rebuild step.
