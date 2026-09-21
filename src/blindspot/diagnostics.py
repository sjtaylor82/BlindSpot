"""Shareable error details and developer diagnostic reports.

Everything here is built to be safe to send to someone else. Text is passed
through `redact`, which removes credentials and personal paths, and item names
in log lines are hidden unless the user opts in. The report is shown to the user
in full before it is copied or saved, so nothing is sent without being read.
"""

from __future__ import annotations

import getpass
import platform
import re
import sys
import time
import traceback
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from . import __version__

REDACTED = "[redacted]"
LOG_EXCERPT_LINES = 300
LOG_READ_BYTES = 512 * 1024

# Settings that are safe to report as they are. Anything else is left out.
SAFE_SETTINGS = (
    "logging_level",
    "announce_track_changes",
    "resume_mode",
    "follow_braille_lyrics",
    "playback_volume_percent",
)

_BEARER = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]+")
_SECRET_FIELD = re.compile(
    r"(?i)(?P<key>\b(?:access_token|refresh_token|client_secret|api_key|apikey|"
    r"code_verifier|authorization|password)[\"']?\s*[=:]\s*)"
    r"(?P<value>[\"']?[^\s\"'&,}]+[\"']?)"
)
_QUERY_SECRET = re.compile(r"(?i)([?&](?:code|state)=)[^&\s\"']+")
_LONG_TOKEN = re.compile(r"\b[A-Za-z0-9_\-.]{40,}\b")
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_WINDOWS_USER = re.compile(r"(?i)([A-Za-z]:[\\/]Users[\\/])[^\\/\s'\"]+")
_UNIX_USER = re.compile(r"(/Users/|/home/)[^/\s'\"]+")
# Install locations only say where BlindSpot happens to be unpacked; the
# package-relative part is what a developer needs.
_APP_PATH = re.compile(r"[A-Za-z]:[\\/][^\s'\"]*?[\\/](?:src[\\/])?blindspot[\\/]")
# A quoted string, allowing for escaped quotes such as 'We\'ve Only Just Begun'.
_QUOTED = r"""(?:'(?:[^'\\]|\\.)*'|"(?:[^"\\]|\\.)*")"""
_NAME_FIELD = re.compile(
    rf"(?i)\b(name|title|artist|album|playlist|query|show|episode)={_QUOTED}"
)
_LOOKUP_NAMES = re.compile(
    rf"(?i)(lookup failed for ){_QUOTED}( by ){_QUOTED}"
)
_LOG_LINE = re.compile(
    r"^(\d{4}-\d\d-\d\d [\d:,]+ \w+ )(blindspot[\w.]*)(: )(.*)$"
)
_ANY_QUOTED = re.compile(_QUOTED)
# BlindSpot logs item names with %r, so every quoted string on its own log
# lines is treated as a possible name. These shapes are known to hold only
# technical values and stay readable.
_HARMLESS_QUOTES = ("query_fields=", "types={", "backend=b")


@dataclass(frozen=True, slots=True)
class ErrorDetails:
    """What went wrong, captured when it happened."""

    message: str
    task: str = ""
    error_type: str = ""
    traceback: str = ""
    status: int | None = None
    retry_after: int | None = None
    occurred: float = 0.0


def capture_error(
    error: BaseException | None,
    message: str,
    task: str = "",
) -> ErrorDetails:
    """Record an error with its type, traceback and any Spotify status."""
    if error is None:
        return ErrorDetails(message, task, occurred=time.time())
    kind = type(error)
    return ErrorDetails(
        message=message,
        task=task,
        error_type=f"{kind.__module__}.{kind.__qualname__}",
        traceback="".join(
            traceback.format_exception(kind, error, error.__traceback__)
        ),
        status=getattr(error, "status", None),
        retry_after=getattr(error, "retry_after", None),
        occurred=time.time(),
    )


def redact(text: str, secrets: Iterable[str] = ()) -> str:
    """Remove credentials, personal paths and account details from `text`."""
    for secret in secrets:
        secret = str(secret or "").strip()
        if len(secret) >= 6:
            text = text.replace(secret, REDACTED)
    text = _BEARER.sub(f"Bearer {REDACTED}", text)
    text = _SECRET_FIELD.sub(lambda match: match["key"] + REDACTED, text)
    text = _QUERY_SECRET.sub(lambda match: match[1] + REDACTED, text)
    text = _WINDOWS_USER.sub(lambda match: match[1] + "[user]", text)
    text = _UNIX_USER.sub(lambda match: match[1] + "[user]", text)
    text = _APP_PATH.sub("blindspot\\\\", text)
    text = _EMAIL.sub("[email]", text)
    text = _LONG_TOKEN.sub("[redacted token]", text)
    try:
        user = getpass.getuser()
    except Exception:
        user = ""
    if len(user) >= 4:
        text = re.sub(
            rf"(?i)\b{re.escape(user)}\b",
            "[user]",
            text,
        )
    return text


def hide_names(text: str) -> str:
    """Hide song, artist, playlist and device names in log text.

    BlindSpot's own log lines have every quoted string hidden, apart from a few
    shapes known to be purely technical. Labelled names are hidden anywhere.
    """
    lines = []
    for line in text.split("\n"):
        match = _LOG_LINE.match(line)
        if match and not any(mark in match[4] for mark in _HARMLESS_QUOTES):
            head, source, colon, body = match.groups()
            line = head + source + colon + _ANY_QUOTED.sub("[hidden]", body)
        lines.append(line)
    text = "\n".join(lines)
    text = _NAME_FIELD.sub(lambda match: f"{match[1]}=[hidden]", text)
    return _LOOKUP_NAMES.sub(
        lambda match: f"{match[1]}[hidden]{match[2]}[hidden]",
        text,
    )


def system_summary() -> list[str]:
    try:
        import wx

        toolkit = wx.version()
    except Exception:
        toolkit = "unknown"
    return [
        f"BlindSpot: {__version__}",
        f"Python: {platform.python_version()}",
        f"wxPython: {toolkit}",
        f"Operating system: {platform.platform()}",
        f"Packaged build: {'yes' if getattr(sys, 'frozen', False) else 'no'}",
    ]


def _timestamp(moment: float | None = None) -> str:
    when = datetime.fromtimestamp(moment) if moment else datetime.now()
    return when.strftime("%d %B %Y at %I:%M %p").lstrip("0")


def error_report(
    details: ErrorDetails,
    secrets: Iterable[str] = (),
) -> str:
    """Format one error so it can be pasted into a bug report."""
    lines = ["BlindSpot error details", ""]
    lines += system_summary()
    lines.append(f"When: {_timestamp(details.occurred)}")
    if details.task:
        lines.append(f"What BlindSpot was doing: {details.task}")
    if details.error_type:
        lines.append(f"Error type: {details.error_type}")
    lines.append(f"Message: {details.message}")
    if details.status is not None:
        lines.append(f"Spotify status: {details.status}")
    if details.retry_after is not None:
        lines.append(f"Spotify asked to wait: {details.retry_after} seconds")
    if details.traceback:
        lines += ["", "Traceback:", details.traceback.rstrip()]
    return redact("\n".join(lines) + "\n", secrets)


def tail_lines(
    path: Path,
    count: int = LOG_EXCERPT_LINES,
    max_bytes: int = LOG_READ_BYTES,
) -> list[str]:
    """Return the last `count` lines of a possibly large log file."""
    try:
        with path.open("rb") as handle:
            handle.seek(0, 2)
            size = handle.tell()
            handle.seek(max(0, size - max_bytes))
            data = handle.read()
    except OSError:
        return []
    lines = data.decode("utf-8", errors="replace").splitlines()
    if size > max_bytes and lines:
        lines = lines[1:]  # the first line was cut off mid-way
    return lines[-count:]


def diagnostic_report(
    settings: Mapping[str, object],
    *,
    secrets_configured: Mapping[str, str],
    connected: bool,
    last_error: ErrorDetails | None,
    log_lines: list[str] | None,
    logging_level: str,
    include_names: bool = False,
    secrets: Iterable[str] = (),
) -> str:
    """Build the developer report.

    `log_lines` is None when the user chose not to include the log.
    """
    lines = ["BlindSpot diagnostic report", ""]
    lines.append(f"Created: {_timestamp()}")
    lines += system_summary()
    lines += ["", "Settings (non-secret only):"]
    for key in SAFE_SETTINGS:
        if key in settings:
            lines.append(f"  {key}: {settings[key]}")
    custom = len(settings.get("global_shortcuts") or {})
    lines.append(f"  custom global shortcuts: {custom}")
    lines += ["", "Credentials (whether set, never their values):"]
    for label, state in secrets_configured.items():
        lines.append(f"  {label}: {state}")
    lines.append(f"  Spotify connected: {'yes' if connected else 'no'}")
    lines += ["", "Last error this session:"]
    if last_error:
        body = error_report(last_error, secrets)
        # The report header repeats the system summary already shown above.
        keep = body.split("When:", 1)
        lines.append("  When:" + keep[1].rstrip().replace("\n", "\n  "))
    else:
        lines.append("  none")
    lines.append("")
    if log_lines is None:
        lines.append("Log: not included.")
    elif not log_lines:
        if logging_level == "Off":
            lines.append(
                "Log: logging is switched off, so there is nothing to include. "
                "Set logging to Debug in Preferences, repeat the problem, then "
                "create this report again."
            )
        else:
            lines.append("Log: no log lines were found.")
    else:
        note = (
            "names and search terms included"
            if include_names
            else "names and search terms hidden"
        )
        lines.append(f"Recent log lines ({len(log_lines)}, {note}):")
        excerpt = "\n".join(log_lines)
        if not include_names:
            excerpt = hide_names(excerpt)
        lines.append(excerpt)
    return redact("\n".join(lines) + "\n", secrets)
