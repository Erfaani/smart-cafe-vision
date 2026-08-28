# AI worker

Runs the computer-vision pipeline in its own process, separate from the Django
backend (spec §17). It reads camera streams, produces anonymous events, and
writes them to the Redis event stream. It never touches the database.

## Status by phase

| Capability | Phase | State |
|---|---|---|
| Process lifecycle, heartbeat, event publishing | 1 | **working** |
| RTSP capture and reconnection | 2 | not started |
| YOLO person detection | 3 | not started |
| ByteTrack / BoT-SORT tracking | 4 | not started |
| Entry/exit zones and stay time | 5 | not started |

The worker does **not** simulate detections while those phases are incomplete.
Invented occupancy numbers would be indistinguishable from real ones on the
dashboard, and a café owner could staff a shift based on them.

## Running

```bash
pip install -r requirements.txt
pip install -e ../shared

export REDIS_URL=redis://localhost:6379/0
export CAFE_ID=<uuid of the café>       # see docs/installation.md
python -m worker
```

The dashboard's health panel should switch the AI worker component from
*degraded* to *ok* within about ten seconds.
