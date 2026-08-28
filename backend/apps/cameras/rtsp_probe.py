"""A minimal RTSP client used only to answer "can we connect, and with what
credentials?" — never to decode video.

Why not just use OpenCV here: this runs inside the Django API process on a
button click, and it must answer in a few seconds without pulling FFmpeg/OpenCV
into the backend image (that dependency belongs to the AI worker, which is the
thing that actually decodes frames — see backend/Dockerfile). RTSP's handshake
is small and text-based (modelled on HTTP), so a plain socket implementing just
OPTIONS and DESCRIBE is enough to distinguish the failure modes an installer
actually hits: wrong IP, wrong path, wrong password, camera powered off.

This deliberately does not open the media stream. A DESCRIBE 200 response means
the camera accepted the URL and credentials; it does not guarantee the stream
decodes as valid video, which is verified for real once the AI worker opens it
(Phase 3 onward). Overclaiming that guarantee here would violate the "do not
fake CV functionality" rule this project holds itself to.
"""
from __future__ import annotations

import hashlib
import logging
import socket
from dataclasses import dataclass
from enum import StrEnum
from urllib.parse import urlparse

from scv_contracts.redact import redact_rtsp_credentials

logger = logging.getLogger("smartcafe.cameras")

CONNECT_TIMEOUT_SECONDS = 5.0
READ_TIMEOUT_SECONDS = 5.0
RECV_CHUNK = 4096
MAX_RESPONSE_BYTES = 65536


class ProbeStatus(StrEnum):
    OK = "ok"
    CAMERA_OFFLINE = "camera_offline"
    AUTH_FAILED = "auth_failed"
    STREAM_NOT_FOUND = "stream_not_found"
    STREAM_TIMEOUT = "stream_timeout"
    INVALID_RESPONSE = "invalid_response"
    INVALID_URL = "invalid_url"


#: User-facing text per status (spec §24). Kept alongside the status enum so a
#: new status can't ship without a message for it.
MESSAGES: dict[ProbeStatus, str] = {
    ProbeStatus.OK: "Connected successfully.",
    ProbeStatus.CAMERA_OFFLINE: "Camera offline: could not reach the host on the RTSP port.",
    ProbeStatus.AUTH_FAILED: "Authentication failed: check the username and password.",
    ProbeStatus.STREAM_NOT_FOUND: "Stream not found: check the path portion of the URL.",
    ProbeStatus.STREAM_TIMEOUT: "Stream timeout: the camera accepted the connection but did not respond in time.",
    ProbeStatus.INVALID_RESPONSE: "Unable to connect to RTSP stream: the host answered, but not with RTSP.",
    ProbeStatus.INVALID_URL: "The RTSP URL could not be parsed.",
}


@dataclass(frozen=True, slots=True)
class ProbeResult:
    status: ProbeStatus
    message: str
    detail: str = ""

    @property
    def ok(self) -> bool:
        return self.status is ProbeStatus.OK


def _digest_response(
    username: str, password: str, realm: str, nonce: str, method: str, uri: str
) -> str:
    """RFC 2069 digest response. RTSP mandates MD5 here; this is protocol
    compliance, not a general-purpose cryptographic recommendation."""
    ha1 = hashlib.md5(f"{username}:{realm}:{password}".encode()).hexdigest()
    ha2 = hashlib.md5(f"{method}:{uri}".encode()).hexdigest()
    return hashlib.md5(f"{ha1}:{nonce}:{ha2}".encode()).hexdigest()


def _parse_auth_challenge(header_value: str) -> dict[str, str]:
    """Parse `Digest realm="...", nonce="...", ...` into a dict."""
    scheme, _sep, rest = header_value.partition(" ")
    params: dict[str, str] = {"__scheme__": scheme.strip()}
    for part in rest.split(","):
        key, sep, value = part.strip().partition("=")
        if sep:
            params[key.strip()] = value.strip().strip('"')
    return params


class _RtspSession:
    """One TCP connection, enough state to send a couple of requests on it."""

    def __init__(self, sock: socket.socket) -> None:
        self._sock = sock
        self._cseq = 0

    def request(self, method: str, uri: str, extra_headers: dict[str, str] | None = None) -> tuple[int, dict[str, str], bytes]:
        self._cseq += 1
        headers = {"CSeq": str(self._cseq), "User-Agent": "SmartCafeVision-Probe/1.0"}
        headers.update(extra_headers or {})
        header_lines = "".join(f"{key}: {value}\r\n" for key, value in headers.items())
        message = f"{method} {uri} RTSP/1.0\r\n{header_lines}\r\n"
        self._sock.sendall(message.encode())
        return self._read_response()

    def _read_response(self) -> tuple[int, dict[str, str], bytes]:
        buffer = b""
        self._sock.settimeout(READ_TIMEOUT_SECONDS)
        try:
            while b"\r\n\r\n" not in buffer and len(buffer) < MAX_RESPONSE_BYTES:
                chunk = self._sock.recv(RECV_CHUNK)
                if not chunk:
                    break
                buffer += chunk
        except TimeoutError as exc:
            raise _StreamTimeout() from exc

        if not buffer:
            raise _StreamTimeout()

        head, _sep, body = buffer.partition(b"\r\n\r\n")
        lines = head.decode(errors="replace").split("\r\n")
        status_line = lines[0] if lines else ""
        parts = status_line.split(" ", 2)
        if len(parts) < 2 or not parts[0].upper().startswith("RTSP"):
            raise _InvalidResponse(status_line)

        try:
            status_code = int(parts[1])
        except ValueError as exc:
            raise _InvalidResponse(status_line) from exc

        headers: dict[str, str] = {}
        for line in lines[1:]:
            key, sep, value = line.partition(":")
            if sep:
                headers[key.strip().lower()] = value.strip()

        return status_code, headers, body


class _StreamTimeout(Exception):
    pass


class _InvalidResponse(Exception):
    def __init__(self, status_line: str) -> None:
        super().__init__(status_line)
        self.status_line = status_line


def probe_rtsp(
    url: str,
    username: str = "",
    password: str = "",
    *,
    connect_timeout: float = CONNECT_TIMEOUT_SECONDS,
) -> ProbeResult:
    """Attempt an RTSP OPTIONS/DESCRIBE handshake against `url`.

    Never raises: every failure mode this function knows about is reported as a
    ProbeResult, and anything unexpected is caught and reported as
    INVALID_RESPONSE with the exception type as detail, because a "test
    connection" button that 500s is worse than one that reports "unknown
    error".
    """
    try:
        parsed = urlparse(url)
    except ValueError:
        return ProbeResult(ProbeStatus.INVALID_URL, MESSAGES[ProbeStatus.INVALID_URL])

    if parsed.scheme.lower() != "rtsp" or not parsed.hostname:
        return ProbeResult(ProbeStatus.INVALID_URL, MESSAGES[ProbeStatus.INVALID_URL])

    host = parsed.hostname
    port = parsed.port or 554

    try:
        raw_sock = socket.create_connection((host, port), timeout=connect_timeout)
    except (TimeoutError, ConnectionRefusedError, OSError) as exc:
        logger.info("rtsp_probe_offline host=%s port=%s error=%s", host, port, type(exc).__name__)
        return ProbeResult(
            ProbeStatus.CAMERA_OFFLINE,
            MESSAGES[ProbeStatus.CAMERA_OFFLINE],
            detail=type(exc).__name__,
        )

    try:
        with raw_sock:
            session = _RtspSession(raw_sock)
            return _handshake(session, url, username, password)
    except _StreamTimeout:
        return ProbeResult(ProbeStatus.STREAM_TIMEOUT, MESSAGES[ProbeStatus.STREAM_TIMEOUT])
    except _InvalidResponse as exc:
        return ProbeResult(
            ProbeStatus.INVALID_RESPONSE,
            MESSAGES[ProbeStatus.INVALID_RESPONSE],
            detail=exc.status_line[:200],
        )
    except Exception as exc:  # noqa: BLE001 - a probe must never crash the request
        logger.warning("rtsp_probe_unexpected_error error=%s", type(exc).__name__)
        return ProbeResult(
            ProbeStatus.INVALID_RESPONSE,
            MESSAGES[ProbeStatus.INVALID_RESPONSE],
            detail=redact_rtsp_credentials(str(exc))[:200],
        )


def _handshake(session: _RtspSession, url: str, username: str, password: str) -> ProbeResult:
    status, _headers, _body = session.request("OPTIONS", url)
    if status == 401:
        return _authenticated_describe(session, url, username, password, challenge_headers=_headers)
    if status >= 400:
        return _status_to_result(status)

    status, headers, _body = session.request("DESCRIBE", url, {"Accept": "application/sdp"})
    if status == 401:
        return _authenticated_describe(session, url, username, password, challenge_headers=headers)
    return _status_to_result(status)


def _authenticated_describe(
    session: _RtspSession,
    url: str,
    username: str,
    password: str,
    *,
    challenge_headers: dict[str, str],
) -> ProbeResult:
    if not username:
        return ProbeResult(ProbeStatus.AUTH_FAILED, MESSAGES[ProbeStatus.AUTH_FAILED])

    challenge = challenge_headers.get("www-authenticate", "")
    params = _parse_auth_challenge(challenge)
    scheme = params.get("__scheme__", "").lower()

    if scheme == "digest":
        realm = params.get("realm", "")
        nonce = params.get("nonce", "")
        response = _digest_response(username, password, realm, nonce, "DESCRIBE", url)
        auth_header = (
            f'Digest username="{username}", realm="{realm}", nonce="{nonce}", '
            f'uri="{url}", response="{response}"'
        )
    elif scheme == "basic":
        import base64

        token = base64.b64encode(f"{username}:{password}".encode()).decode()
        auth_header = f"Basic {token}"
    else:
        return ProbeResult(ProbeStatus.AUTH_FAILED, MESSAGES[ProbeStatus.AUTH_FAILED])

    status, _headers, _body = session.request(
        "DESCRIBE", url, {"Accept": "application/sdp", "Authorization": auth_header}
    )
    return _status_to_result(status)


def _status_to_result(status: int) -> ProbeResult:
    if status == 200:
        return ProbeResult(ProbeStatus.OK, MESSAGES[ProbeStatus.OK])
    if status in (401, 403):
        return ProbeResult(ProbeStatus.AUTH_FAILED, MESSAGES[ProbeStatus.AUTH_FAILED])
    if status == 404:
        return ProbeResult(ProbeStatus.STREAM_NOT_FOUND, MESSAGES[ProbeStatus.STREAM_NOT_FOUND])
    return ProbeResult(
        ProbeStatus.INVALID_RESPONSE,
        MESSAGES[ProbeStatus.INVALID_RESPONSE],
        detail=f"RTSP status {status}",
    )
