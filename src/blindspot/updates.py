from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.request
import webbrowser
from dataclasses import dataclass

from .portable import application_directory, resource_directory


LATEST_RELEASE_API = (
    "https://api.github.com/repos/sjtaylor82/BlindSpot/releases/latest"
)
RELEASES_URL = "https://github.com/sjtaylor82/BlindSpot/releases"


@dataclass(frozen=True)
class Release:
    version: str
    url: str
    assets: tuple[dict, ...] = ()


def version_parts(value: str) -> tuple[int, ...]:
    value = value.strip().removeprefix("v")
    try:
        return tuple(int(part) for part in value.split("."))
    except ValueError:
        return ()


def newer_than(candidate: str, current: str) -> bool:
    candidate_parts = version_parts(candidate)
    current_parts = version_parts(current)
    if not candidate_parts or not current_parts:
        return False
    length = max(len(candidate_parts), len(current_parts))
    return (
        candidate_parts + (0,) * (length - len(candidate_parts))
        > current_parts + (0,) * (length - len(current_parts))
    )


def latest_release(timeout: float = 10) -> Release:
    request = urllib.request.Request(
        LATEST_RELEASE_API,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "BlindSpot update checker",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        payload = json.load(response)
    return Release(
        version=str(payload["tag_name"]).removeprefix("v"),
        url=str(payload["html_url"]),
        assets=tuple(payload.get("assets", ())),
    )


def pick_asset(release: Release, platform: str = sys.platform) -> dict | None:
    wanted = (
        "blindspot-macos.zip"
        if platform == "darwin"
        else "blindspot-windows.zip"
    )
    return next(
        (
            asset
            for asset in release.assets
            if str(asset.get("name", "")).casefold() == wanted
        ),
        None,
    )


def supports_automatic_update(
    release: Release,
    platform: str = sys.platform,
    frozen: bool | None = None,
) -> bool:
    if frozen is None:
        frozen = bool(getattr(sys, "frozen", False))
    return bool(
        platform == "win32"
        and frozen
        and pick_asset(release, platform) is not None
    )


def download_and_install(
    release: Release,
    progress_callback=None,
) -> bool:
    if not supports_automatic_update(release):
        webbrowser.open(release.url)
        return True
    asset = pick_asset(release)

    destination = os.path.join(
        tempfile.gettempdir(),
        str(asset["name"]),
    )

    def report(block_number, block_size, total_size):
        if progress_callback and total_size > 0:
            progress_callback(
                min(100, int(block_number * block_size * 100 / total_size))
            )

    urllib.request.urlretrieve(
        str(asset["browser_download_url"]),
        destination,
        reporthook=report,
    )
    schedule_windows_replacement(destination)
    return True


def schedule_windows_replacement(zip_path: str) -> None:
    app_directory = application_directory()
    probe = app_directory / ".update-write-test"
    try:
        probe.write_text("ok", encoding="ascii")
    finally:
        probe.unlink(missing_ok=True)

    script = resource_directory() / "portable_updater.ps1"
    ready = (
        tempfile.gettempdir()
        + f"\\BlindSpot-update-ready-{os.getpid()}.txt"
    )
    helper = subprocess.Popen(
        [
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(script),
            "-BlindSpotProcessId",
            str(os.getpid()),
            "-ZipPath",
            zip_path,
            "-AppDirectory",
            str(app_directory),
            "-ExecutablePath",
            str(app_directory / "BlindSpot.exe"),
            "-ReadyPath",
            ready,
        ],
        creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0),
        close_fds=True,
    )
    deadline = time.monotonic() + 1800
    while not os.path.isfile(ready):
        if helper.poll() is not None:
            raise RuntimeError("The update helper stopped during preparation.")
        if time.monotonic() >= deadline:
            raise TimeoutError("Update preparation timed out.")
        time.sleep(0.2)
    status = open(ready, encoding="ascii").read().strip().lower()
    os.remove(ready)
    if status != "ready":
        raise RuntimeError("The update could not be prepared.")
