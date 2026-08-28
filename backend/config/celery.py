"""Celery application.

Background jobs are for analytics rollups and housekeeping only. Video
inference never runs here: it belongs to the dedicated AI worker (spec §17).
"""
from __future__ import annotations

import os

from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.development")

app = Celery("smartcafe")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()


@app.task(bind=True, ignore_result=True)
def debug_task(self) -> str:  # pragma: no cover - operational smoke task
    return f"celery ok: {self.request.id}"
