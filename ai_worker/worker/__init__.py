"""Smart Café Vision AI worker.

Runs as its own process (and its own container) so that inference load can never
add latency to the dashboard, and so the backend can be restarted without
interrupting camera capture.

Phase 1 scope: process lifecycle, configuration, and the heartbeat/event
publishing path. There is deliberately no detection code here yet -- cameras
arrive in Phase 2, YOLO in Phase 3, tracking in Phase 4.
"""

__version__ = "0.1.0"
