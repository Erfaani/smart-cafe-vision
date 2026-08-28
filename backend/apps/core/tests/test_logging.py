"""Credentials must never reach a log file (spec §28)."""
from __future__ import annotations

import logging

import pytest

from apps.core.logging import RedactSecretsFilter, RequestIDFilter, request_id_var, scrub


@pytest.mark.parametrize(
    ("raw", "must_not_contain"),
    [
        ("connecting to rtsp://admin:hunter2@192.168.1.64:554/stream", "hunter2"),
        ("RTSP://Admin:S3cr3t!@cam.local/live", "S3cr3t!"),
        ('{"password": "hunter2"}', "hunter2"),
        ("token=abcdef123456", "abcdef123456"),
        ("Authorization: Bearer eyJhbGciOi", "eyJhbGciOi"),
        ("api_key = 'zzz-secret'", "zzz-secret"),
    ],
)
def test_scrub_removes_credentials(raw, must_not_contain):
    assert must_not_contain not in scrub(raw)


def test_scrub_keeps_the_useful_part_of_an_rtsp_url():
    cleaned = scrub("stream rtsp://admin:hunter2@192.168.1.64:554/Streaming/Channels/101 failed")
    assert "192.168.1.64" in cleaned and "Streaming/Channels/101" in cleaned
    assert "hunter2" not in cleaned


def _record(msg, args=()):
    # logging.LogRecord special-cases a single Mapping arg, so a dict must be
    # wrapped in a tuple exactly as logging itself passes it.
    return logging.LogRecord("t", logging.INFO, __file__, 1, msg, args, None)


def test_filter_scrubs_message_and_args():
    record = _record("connecting %s", ("rtsp://admin:hunter2@cam/live",))
    RedactSecretsFilter().filter(record)
    assert "hunter2" not in record.getMessage()


def test_filter_scrubs_dict_args():
    record = _record("%(url)s", ({"url": "rtsp://admin:hunter2@cam/live"},))
    RedactSecretsFilter().filter(record)
    assert "hunter2" not in record.getMessage()


def test_request_id_filter_uses_the_context_value():
    token = request_id_var.set("abc123")
    try:
        record = _record("hello")
        RequestIDFilter().filter(record)
        assert record.request_id == "abc123"
    finally:
        request_id_var.reset(token)
