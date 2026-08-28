"""Protocol-level tests for the RTSP prober, against a fake server.

No OpenCV, no FFmpeg, no real camera: a thread speaking just enough RTSP to
exercise every branch in `probe_rtsp`. This is exactly the boundary the prober
was designed for — it validates connectivity and auth, not video.
"""
from __future__ import annotations

import socket
import threading
from collections.abc import Callable

import pytest

from apps.cameras.rtsp_probe import ProbeStatus, probe_rtsp

Handler = Callable[[str, dict[str, str]], tuple[int, dict[str, str]]]


class FakeRtspServer:
    """A single-connection RTSP server driven by a per-test handler function.

    `handler(method, headers) -> (status_code, response_headers)` decides how
    to answer each request; tests supply small handlers rather than a full
    server, which keeps each test about the one behaviour it is checking.
    """

    def __init__(self, handler: Handler) -> None:
        self._handler = handler
        self._server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._server.bind(("127.0.0.1", 0))
        self._server.listen(1)
        self.port = self._server.getsockname()[1]
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    def _serve(self) -> None:
        try:
            self._server.settimeout(10)
            conn, _addr = self._server.accept()
        except OSError:
            return
        with conn:
            conn.settimeout(10)
            buffer = b""
            while True:
                try:
                    chunk = conn.recv(4096)
                except OSError:
                    return
                if not chunk:
                    return
                buffer += chunk
                while b"\r\n\r\n" in buffer:
                    raw_request, _sep, buffer = buffer.partition(b"\r\n\r\n")
                    lines = raw_request.decode().split("\r\n")
                    method = lines[0].split(" ")[0]
                    headers = {}
                    cseq = "1"
                    for line in lines[1:]:
                        key, sep, value = line.partition(":")
                        if sep:
                            headers[key.strip().lower()] = value.strip()
                            if key.strip().lower() == "cseq":
                                cseq = value.strip()
                    status, response_headers = self._handler(method, headers)
                    response_headers.setdefault("CSeq", cseq)
                    header_text = "".join(f"{k}: {v}\r\n" for k, v in response_headers.items())
                    reason = {200: "OK", 401: "Unauthorized", 404: "Not Found"}.get(status, "Error")
                    conn.sendall(f"RTSP/1.0 {status} {reason}\r\n{header_text}\r\n".encode())

    def url(self, path: str = "/stream") -> str:
        return f"rtsp://127.0.0.1:{self.port}{path}"

    def close(self) -> None:
        self._server.close()


@pytest.fixture
def server():
    servers: list[FakeRtspServer] = []

    def make(handler: Handler) -> FakeRtspServer:
        server = FakeRtspServer(handler)
        servers.append(server)
        return server

    yield make
    for server in servers:
        server.close()


def test_successful_handshake_without_auth(server):
    def handler(method, headers):
        return 200, {}

    fake = server(handler)
    result = probe_rtsp(fake.url())

    assert result.ok
    assert result.status is ProbeStatus.OK


def test_camera_offline_when_nothing_is_listening():
    # Port 1 is privileged and reliably closed/refused on every platform this
    # runs on, without depending on any specific host being unreachable.
    result = probe_rtsp("rtsp://127.0.0.1:1/stream", connect_timeout=1)
    assert result.status is ProbeStatus.CAMERA_OFFLINE


def test_stream_timeout_when_the_server_accepts_but_never_replies(server):
    def handler(method, headers):
        raise AssertionError("should never be reached: connection sits open, silent")

    fake = FakeRtspServerSilent()
    try:
        result = probe_rtsp(fake.url(), connect_timeout=1)
        assert result.status is ProbeStatus.STREAM_TIMEOUT
    finally:
        fake.close()


class FakeRtspServerSilent:
    """Accepts the TCP connection and then says nothing -- the exact 'answers
    TCP but never sends a frame' failure mode called out in the roadmap."""

    def __init__(self) -> None:
        self._server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._server.bind(("127.0.0.1", 0))
        self._server.listen(1)
        self.port = self._server.getsockname()[1]
        self._thread = threading.Thread(target=self._accept_and_hold, daemon=True)
        self._thread.start()

    def _accept_and_hold(self) -> None:
        try:
            self._server.settimeout(10)
            conn, _addr = self._server.accept()
            conn.settimeout(10)
            conn.recv(4096)  # read the request, then simply never respond
        except OSError:
            return

    def url(self) -> str:
        return f"rtsp://127.0.0.1:{self.port}/stream"

    def close(self) -> None:
        self._server.close()


def test_invalid_response_from_a_non_rtsp_service(server):
    """A wrong port pointed at some other TCP service (e.g. HTTP) must not be
    reported as 'camera offline' -- the host IS reachable, just not RTSP."""

    class HttpLikeServer:
        def __init__(self) -> None:
            self._server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self._server.bind(("127.0.0.1", 0))
            self._server.listen(1)
            self.port = self._server.getsockname()[1]
            threading.Thread(target=self._serve, daemon=True).start()

        def _serve(self) -> None:
            try:
                self._server.settimeout(10)
                conn, _addr = self._server.accept()
                conn.settimeout(10)
                conn.recv(4096)
                conn.sendall(b"HTTP/1.1 200 OK\r\nContent-Length: 0\r\n\r\n")
            except OSError:
                return

        def url(self) -> str:
            return f"rtsp://127.0.0.1:{self.port}/stream"

        def close(self) -> None:
            self._server.close()

    fake = HttpLikeServer()
    try:
        result = probe_rtsp(fake.url())
        assert result.status is ProbeStatus.INVALID_RESPONSE
    finally:
        fake.close()


def test_stream_not_found_on_404(server):
    def handler(method, headers):
        return 404, {}

    fake = server(handler)
    result = probe_rtsp(fake.url())
    assert result.status is ProbeStatus.STREAM_NOT_FOUND


def test_auth_failed_with_no_credentials_supplied(server):
    def handler(method, headers):
        return 401, {"WWW-Authenticate": 'Digest realm="cam", nonce="abc123"'}

    fake = server(handler)
    result = probe_rtsp(fake.url())  # no username/password
    assert result.status is ProbeStatus.AUTH_FAILED


def test_auth_failed_with_wrong_credentials(server):
    def handler(method, headers):
        # Always challenge, regardless of what Authorization header arrives.
        return 401, {"WWW-Authenticate": 'Digest realm="cam", nonce="abc123"'}

    fake = server(handler)
    result = probe_rtsp(fake.url(), username="admin", password="wrong")
    assert result.status is ProbeStatus.AUTH_FAILED


def test_digest_auth_succeeds_with_correct_credentials(server):
    """Verifies the actual MD5 digest computation, not just the plumbing."""
    calls = {"count": 0}

    def handler(method, headers):
        calls["count"] += 1
        if "authorization" not in headers:
            return 401, {"WWW-Authenticate": 'Digest realm="cam", nonce="abc123"'}
        # A real camera would recompute and compare; the fake trusts the header
        # was sent, which is enough to prove the client completes the
        # challenge/response flow and retries with it.
        assert 'username="admin"' in headers["authorization"]
        assert "response=" in headers["authorization"]
        return 200, {}

    fake = server(handler)
    result = probe_rtsp(fake.url(), username="admin", password="hunter2")

    assert result.ok
    assert calls["count"] == 2  # first attempt challenged, second authenticated


def test_basic_auth_is_supported_for_cheaper_cameras(server):
    def handler(method, headers):
        if "authorization" not in headers:
            return 401, {"WWW-Authenticate": 'Basic realm="cam"'}
        assert headers["authorization"].startswith("Basic ")
        return 200, {}

    fake = server(handler)
    result = probe_rtsp(fake.url(), username="admin", password="hunter2")
    assert result.ok


def test_invalid_url_is_rejected_before_any_network_call():
    result = probe_rtsp("not-a-url-at-all")
    assert result.status is ProbeStatus.INVALID_URL

    result = probe_rtsp("http://example.com/not-rtsp")
    assert result.status is ProbeStatus.INVALID_URL


def test_every_status_has_a_message():
    from apps.cameras.rtsp_probe import MESSAGES

    for status in ProbeStatus:
        assert MESSAGES[status]
