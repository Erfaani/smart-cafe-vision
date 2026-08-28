# Production

Everything needed to run a real café install past the first day: backups,
log rotation, resource limits, a non-Docker (systemd) option, and the
upgrade procedure. See also [security-review.md](security-review.md) for
the hardening review this phase did, and [hardware.md](hardware.md) for
sizing.

---

## Backups

```bash
scripts/backup.sh                              # backup now, to ./backups/
BACKUP_DIR=/mnt/nas/backups scripts/backup.sh   # elsewhere
BACKUP_RETENTION_DAYS=30 scripts/backup.sh      # default is 14
```

Dumps PostgreSQL with `pg_dump --clean --if-exists`, gzips it, and prunes
anything in `BACKUP_DIR` older than `BACKUP_RETENTION_DAYS`. `--clean
--if-exists` means the dump is self-contained: restoring it drops and
recreates every table, so `scripts/restore.sh` works whether the target
database is empty or already has data, without a "relation already exists"
error stopping it halfway through. Safe to run unattended from cron or a
systemd timer — it never prompts.

**What is not in this backup.** Café logos live in the `media_data` volume,
not the database. They are small, and trivially re-uploaded from the Café
settings page if lost, so `scripts/backup.sh` deliberately stays focused on
the database — the data that cannot be reconstructed (every customer
session, every table occupancy record, every analytics rollup). If a
deployment wants the logo backed up too:

```bash
docker compose exec -T backend tar czf - -C /app/mediafiles . > backups/media-$(date +%F).tar.gz
```

### Scheduling

**Docker install**, host crontab:

```cron
30 3 * * * cd /opt/smartcafe && ./scripts/backup.sh >> /var/log/smartcafe-backup.log 2>&1
```

**systemd install:** `deployment/systemd/smartcafe-backup.timer` (see
below) runs the same script nightly with `SMARTCAFE_NO_DOCKER=1`, and
catches up a missed run (`Persistent=true`) if the machine was off at the
scheduled time.

### Restoring

```bash
scripts/restore.sh backups/smartcafe-20260827-030000.sql.gz
```

Destructive — it replaces every table in the live database. It will not run
without the operator typing the database's exact name to confirm, unless
`--yes` is passed (for a scripted disaster-recovery runbook where that
confirmation has already happened elsewhere). Restart the backend,
event-consumer and Celery services afterward — they may hold cached state
from before the restore:

```bash
docker compose restart backend event-consumer celery celery-beat
```

Both scripts were live-verified against a real PostgreSQL instance: seed
data → backup → mutate the data → restore → confirm the original data came
back exactly, and confirm restore refuses to run without the correct typed
confirmation.

---

## Log rotation

**Docker** (`docker-compose.yml`, `docker-compose.ai.yml`): every
long-running service sets

```yaml
logging:
  driver: json-file
  options:
    max-size: "10m"
    max-file: "5"
```

50 MB per service, capped — Docker's default `json-file` driver otherwise
keeps logs forever, which on a café mini PC nobody is actively watching is a
slow disk leak, not a log.

**systemd install:** journald already rotates on its own. Cap the total
size it is allowed to use on disk in `/etc/systemd/journald.conf`:

```ini
[Journal]
SystemMaxUse=500M
```

then `sudo systemctl restart systemd-journald`. Tail one service's logs with
`journalctl -u smartcafe-backend.service -f`.

---

## Event log retention

The same "don't grow forever on a disk nobody is watching" concern applies
to the database, not just log files: `TrackingEvent` is an append-only
record of everything the AI worker has ever reported. A Celery beat task,
`apps.events.prune_old_events`, deletes rows older than
`EVENT_RETENTION_DAYS` (default 90) on a schedule
(`EVENT_PRUNE_INTERVAL_SECONDS`, default daily). This is safe by
construction, not just in practice: every durable figure the product
reports — customer sessions, table sessions, daily analytics rollups — is
computed and stored in its own table at ingest time, never read back from
raw events later, so pruning only gives up the ability to *recompute* a
projection for a given day if a bug is ever found in one, never a number a
café can currently see. Set `EVENT_RETENTION_DAYS=0` to disable pruning
entirely and keep the full raw log indefinitely.

---

## Resource limits

Every container in `docker-compose.yml` has a `deploy.resources.limits`
ceiling, sized to docs/hardware.md's stated minimums for the *non*-AI
services (they do not scale with camera count):

| Service | CPU | Memory |
|---|---|---|
| postgres | 1.0 | 1 GB |
| redis | 0.5 | 768 MB |
| backend | 1.0 | 512 MB |
| event-consumer | 0.5 | 256 MB |
| celery | 1.0 | 512 MB |
| celery-beat | 0.25 | 128 MB |
| frontend | 1.0 | 512 MB |
| nginx | 0.5 | 128 MB |

A limit being hit is a container that gets OOM-killed and restarted
(`restart: unless-stopped`), not a graceful degradation — the point is
containment: a leak or a runaway process stays inside its own container
instead of starving camera capture or the database on the same small
machine. If `docker logs` shows a service repeatedly restarting, check
`docker stats` before assuming a code bug — it may simply need more room on
an unusually busy install.

The AI worker (`docker-compose.ai.yml`) is the one exception, because unlike
everything above it genuinely needs to scale with camera count — see
docs/hardware.md's 1-to-16-camera table:

```bash
AI_WORKER_CPU_LIMIT=8.0     # .env -- raise alongside camera count
AI_WORKER_MEMORY_LIMIT=8g
```

Defaults (4.0 / 4g) cover the 1-2 camera, CPU-only case docs/hardware.md
calls the typical install.

---

## Running without Docker (systemd)

Unit files live in `deployment/systemd/`. Each runs as a dedicated non-root
user with `NoNewPrivileges`, `ProtectSystem=strict` and `ProtectHome=true`
— the same non-root, locked-down posture the Docker images already have
(`USER appuser` / `nextjs` / `worker`), expressed in systemd terms instead
of a container boundary.

### 1. Create the user and directory layout

```bash
sudo useradd --system --create-home --home-dir /opt/smartcafe --shell /usr/sbin/nologin smartcafe
sudo -u smartcafe git clone <this repo> /opt/smartcafe/src   # or copy a release tarball
```

Assumed layout (adjust the units if yours differs):

```
/opt/smartcafe/
├── .env                  # from .env.example, same as the Docker install
├── .venv/                # python -m venv .venv && pip install -r backend/requirements/prod.txt
├── backend/
├── frontend/              # npm ci && npm run build
├── ai_worker/
├── scripts/
└── backups/
```

### 2. Install PostgreSQL and Redis

Distribution packages (`postgresql`, `redis-server`) rather than Docker —
that is the point of this path. Create the database and role matching
`.env`'s `POSTGRES_*` values.

### 3. Migrate, then install the units

```bash
sudo cp deployment/systemd/*.service deployment/systemd/*.timer /etc/systemd/system/
sudo systemctl daemon-reload

sudo systemctl start smartcafe-migrate.service   # one-time, and again on every upgrade
sudo journalctl -u smartcafe-migrate.service --no-pager   # confirm it succeeded

sudo systemctl enable --now smartcafe-backend.service
sudo systemctl enable --now smartcafe-consumer.service
sudo systemctl enable --now smartcafe-celery.service
sudo systemctl enable --now smartcafe-celery-beat.service
sudo systemctl enable --now smartcafe-frontend.service
sudo systemctl enable --now smartcafe-worker.service     # once the AI worker is set up, see gpu-setup.md

sudo systemctl enable --now smartcafe-backup.timer
```

`smartcafe-migrate.service` is deliberately never `enable`d or started
automatically — the same reason `docker-compose.yml` gives `migrate` its
own one-shot service rather than folding it into `backend`: applying schema
changes is a step a human runs once per install/upgrade, never something a
long-running unit should retry on its own or two replicas could race.

### 4. Verify

```bash
curl http://localhost:8000/readyz/
systemctl status smartcafe-backend.service smartcafe-consumer.service smartcafe-celery.service
```

---

## Upgrading

Same shape on both paths: **back up, pull, rebuild, migrate, restart,
verify** — in that order, because migrate has to run against the *new*
code's migrations before the new code starts serving traffic, and a backup
taken *after* a bad migration already ran is not useful.

### Docker

```bash
scripts/backup.sh                       # 1. back up first, always
git pull                                 # 2. get the new code
docker compose up -d --build             # 3. rebuild images
                                          #    (the `migrate` service applies
                                          #    schema changes automatically
                                          #    as part of `up`)
curl http://localhost:8000/readyz/       # 4. verify
```

If `readyz` reports a problem after an upgrade and it is not immediately
obvious, `docker compose logs backend event-consumer` first — most upgrade
issues show up there within the first few log lines.

### systemd

```bash
scripts/backup.sh                                       # 1. back up first
git -C /opt/smartcafe/src pull                           # 2. get the new code
cd /opt/smartcafe/src
../.venv/bin/pip install -r backend/requirements/prod.txt  # 3a. backend deps
cd frontend && npm ci && npm run build && cd ..           # 3b. rebuild frontend
sudo systemctl start smartcafe-migrate.service            # 4. migrate
sudo systemctl restart smartcafe-backend.service \
  smartcafe-consumer.service smartcafe-celery.service \
  smartcafe-celery-beat.service smartcafe-frontend.service \
  smartcafe-worker.service                                # 5. restart everything
curl http://localhost:8000/readyz/                        # 6. verify
```

### If it goes wrong

Migrations in this project are additive and forward-only within a phase —
there is no automated down-migration path. If an upgrade's migration fails
partway or the new code misbehaves once running, the fastest safe recovery
is: stop the services, `scripts/restore.sh` the pre-upgrade backup from step
1, check out the previous commit, and restart on the known-good version.
That is the entire reason step 1 is never optional.

---

## Monitoring

`/readyz/` (full component report, 503 when something critical is down) and
`/healthz/` (liveness only, always 200 if the process is alive) are both
unauthenticated by design — a monitoring probe or a technician checking by
hand needs no credentials, and both are already tested to expose component
status only, never a café name or id. Point an external uptime check at
`/readyz/` if the venue wants alerting beyond the dashboard's own health
panel. See docs/api.md's Operational endpoints section for the exact
response shape and status vocabulary.
