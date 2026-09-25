from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .i18n import tr
from .models import SpotifyItem
from .network import TLS_CONTEXT
from .podcasts import _directory_feeds, _normalise, _read_url, _similarity
from .portable import PortableStore


logger = logging.getLogger(__name__)

PODCAST_NAMESPACE = "https://podcastindex.org/namespace/1.0"
WHISPER_RELEASE = "b5130"
WHISPER_URL = (
    "https://github.com/ggml-org/whisper.cpp/releases/download/"
    f"{WHISPER_RELEASE}/whisper-bin-x64.zip"
)
MODEL_URL = (
    "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/"
    "ggml-base-q5_1.bin"
)
FFMPEG_URL = (
    "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/"
    "ffmpeg-master-latest-win64-lgpl-shared.zip"
)
USER_AGENT = "BlindSpot podcast transcription"
WHISPER_TIMING_VERSION = 2
WHISPER_MAX_LINE_CHARACTERS = 60
WHISPER_PLAYBACK_OFFSET_MS = 3_000


class TranscriptError(RuntimeError):
    pass


class TranscriptUnavailable(TranscriptError):
    pass


class WhisperSetupRequired(TranscriptError):
    pass


@dataclass(frozen=True, slots=True)
class TranscriptLine:
    start_ms: int
    text: str


@dataclass(frozen=True, slots=True)
class Transcript:
    lines: tuple[TranscriptLine, ...]
    source: str
    complete: bool = True
    translated_text: str = ""
    translated_language: str = ""

    @property
    def text(self) -> str:
        return "\n".join(line.text for line in self.lines)


@dataclass(frozen=True, slots=True)
class EpisodeMedia:
    audio_url: str
    transcript_url: str = ""
    transcript_type: str = ""


def _timestamp_ms(value: str) -> int:
    parts = value.replace(",", ".").split(":")
    if len(parts) == 2:
        parts.insert(0, "0")
    if len(parts) != 3:
        return 0
    try:
        hours, minutes = int(parts[0]), int(parts[1])
        seconds = float(parts[2])
    except ValueError:
        return 0
    return int((hours * 3600 + minutes * 60 + seconds) * 1000)


def parse_transcript(payload: bytes, content_type: str = "") -> Transcript:
    text = payload.decode("utf-8-sig", errors="replace")
    content_type = content_type.casefold()
    if "json" in content_type or text.lstrip().startswith(("{", "[")):
        try:
            value = json.loads(text)
        except ValueError as error:
            raise TranscriptUnavailable(tr("Publisher transcript is invalid.")) from error
        segments = value.get("segments", []) if isinstance(value, dict) else value
        lines: list[TranscriptLine] = []
        for segment in segments if isinstance(segments, list) else []:
            if not isinstance(segment, dict):
                continue
            body = str(segment.get("body") or segment.get("text") or "").strip()
            start = segment.get("startTime", segment.get("start", 0))
            if body:
                try:
                    start_ms = int(float(start) * (1 if float(start) >= 1000 else 1000))
                except (TypeError, ValueError):
                    start_ms = 0
                lines.append(TranscriptLine(start_ms, body))
        if lines:
            return Transcript(tuple(lines), "publisher")

    timed: list[TranscriptLine] = []
    pattern = re.compile(
        r"(?m)^(?:\d+\s*\n)?"
        r"(?P<start>\d{1,2}:\d{2}(?::\d{2})?[.,]\d{3})\s*-->[^\n]*\n"
        r"(?P<body>.*?)(?=\n\s*\n|\Z)",
        re.DOTALL,
    )
    for match in pattern.finditer(text.replace("\r\n", "\n")):
        body = re.sub(r"<[^>]+>", "", match.group("body"))
        body = " ".join(body.split())
        if body:
            timed.append(TranscriptLine(_timestamp_ms(match.group("start")), body))
    if timed:
        return Transcript(tuple(timed), "publisher")

    plain = re.sub(r"<[^>]+>", " ", text)
    paragraphs = [" ".join(part.split()) for part in re.split(r"\n\s*\n", plain)]
    lines = tuple(TranscriptLine(0, part) for part in paragraphs if part)
    if not lines:
        raise TranscriptUnavailable(tr("Publisher transcript is empty."))
    return Transcript(lines, "publisher")


def _episode_media_from_feed(feed_url: str, episode_name: str) -> EpisodeMedia | None:
    import xml.etree.ElementTree as ET

    try:
        root = ET.fromstring(_read_url(feed_url, limit=15_000_000))
    except (OSError, ET.ParseError):
        return None
    matches: list[tuple[float, EpisodeMedia]] = []
    for entry in root.findall(".//item"):
        title = (entry.findtext("title") or "").strip()
        enclosure = entry.find("enclosure")
        audio_url = str(enclosure.get("url") or "") if enclosure is not None else ""
        if not title or not audio_url:
            continue
        transcript_url = ""
        transcript_type = ""
        transcripts = entry.findall(f"{{{PODCAST_NAMESPACE}}}transcript")
        if not transcripts:
            transcripts = [
                child for child in entry
                if child.tag.rsplit("}", 1)[-1] == "transcript"
            ]
        for candidate in transcripts:
            candidate_url = str(candidate.get("url") or "")
            candidate_type = str(candidate.get("type") or "")
            if candidate_url and candidate_type in {
                "application/json", "application/srt", "application/x-subrip",
                "text/html", "text/plain", "text/srt", "text/vtt",
            }:
                transcript_url, transcript_type = candidate_url, candidate_type
                if candidate.get("rel") == "captions" or "vtt" in candidate_type:
                    break
        score = _similarity(episode_name, title)
        if _normalise(episode_name) == _normalise(title):
            score = 1.0
        matches.append((score, EpisodeMedia(audio_url, transcript_url, transcript_type)))
    if not matches:
        return None
    score, media = max(matches, key=lambda match: match[0])
    return media if score >= 0.78 else None


def find_episode_media(item: SpotifyItem) -> EpisodeMedia:
    direct_audio = str(item.raw.get("audio_url") or "")
    if direct_audio:
        return EpisodeMedia(
            direct_audio,
            str(item.raw.get("transcript_url") or ""),
            str(item.raw.get("transcript_type") or ""),
        )
    show = item.album or str((item.raw.get("show") or {}).get("name") or "")
    publisher = item.artist or str((item.raw.get("show") or {}).get("publisher") or "")
    if not show:
        raise TranscriptUnavailable(tr("Podcast feed unavailable."))
    feeds = _directory_feeds(show, publisher)
    logger.info(
        "Looking for publisher transcript: show=%r episode=%r feeds=%d",
        show, item.name, len(feeds),
    )
    for feed_url in feeds:
        media = _episode_media_from_feed(feed_url, item.name)
        if media:
            logger.info("Matched transcript episode %r in %s", item.name, feed_url)
            return media
    raise TranscriptUnavailable(tr("Episode audio is unavailable from its public feed."))


def fetch_publisher_transcript(media: EpisodeMedia) -> Transcript | None:
    if not media.transcript_url:
        return None
    try:
        payload = _read_url(media.transcript_url, limit=25_000_000)
        return parse_transcript(payload, media.transcript_type)
    except (OSError, TranscriptError):
        logger.exception("Publisher transcript could not be read")
        return None


class TranscriptCache:
    def __init__(self, store: PortableStore) -> None:
        self.root = store.root / "transcripts"
        self.audio_root = store.root / "transcript-audio"
        self.root.mkdir(parents=True, exist_ok=True)

    def path(self, episode_id: str) -> Path:
        safe_id = re.sub(r"[^A-Za-z0-9_.-]", "_", episode_id)
        return self.root / f"{safe_id}.json"

    def audio_path(self, episode_id: str) -> Path:
        safe_id = re.sub(r"[^A-Za-z0-9_.-]", "_", episode_id)
        return self.audio_root / f"{safe_id}.media"

    def translation_path(self, episode_id: str) -> Path:
        return self.path(episode_id).with_suffix(".translation.json")

    def read_translation(
        self,
        episode_id: str,
        transcript: Transcript,
        target_language: str,
    ) -> Transcript:
        try:
            value = json.loads(
                self.translation_path(episode_id).read_text(encoding="utf-8")
            )
        except (OSError, TypeError, ValueError):
            return transcript
        if (
            value.get("target_language") != target_language
            or value.get("source_text") != transcript.text
            or not value.get("text")
        ):
            return transcript
        return Transcript(
            transcript.lines,
            transcript.source,
            transcript.complete,
            str(value["text"]),
            target_language,
        )

    def write_translation(
        self,
        episode_id: str,
        transcript: Transcript,
        target_language: str,
        translated_text: str,
    ) -> Transcript:
        path = self.translation_path(episode_id)
        temporary = path.with_suffix(".json.tmp")
        temporary.write_text(
            json.dumps(
                {
                    "target_language": target_language,
                    "source_text": transcript.text,
                    "text": translated_text,
                },
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        temporary.replace(path)
        return Transcript(
            transcript.lines,
            transcript.source,
            transcript.complete,
            translated_text,
            target_language,
        )

    def read(self, episode_id: str) -> Transcript | None:
        try:
            value = json.loads(self.path(episode_id).read_text(encoding="utf-8"))
            lines = tuple(
                TranscriptLine(int(line["start_ms"]), str(line["text"]))
                for line in value.get("lines", [])
                if str(line.get("text") or "").strip()
            )
            source = str(value.get("source") or "cache")
            complete = bool(value.get("complete", True))
            if (
                source == "whisper"
                and int(value.get("timing_version") or 1)
                < WHISPER_TIMING_VERSION
            ):
                # Older Whisper caches used decoder segments as transcript
                # lines.  A segment can span roughly 30 seconds, so its start
                # is too coarse for cursor playback.  Keep the text visible
                # while prompting the normal path to regenerate finer timing.
                complete = False
            return Transcript(lines, source, complete) if lines else None
        except (OSError, TypeError, ValueError, KeyError):
            return None

    def write(self, episode_id: str, transcript: Transcript) -> None:
        path = self.path(episode_id)
        temporary = path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps({
            "source": transcript.source,
            "complete": transcript.complete,
            "timing_version": (
                WHISPER_TIMING_VERSION
                if transcript.source == "whisper"
                else 1
            ),
            "lines": [
                {"start_ms": line.start_ms, "text": line.text}
                for line in transcript.lines
            ],
        }, indent=2, ensure_ascii=False), encoding="utf-8")
        temporary.replace(path)


class WhisperTranscriber:
    """Stream public podcast audio through rolling WAV segments and whisper.cpp."""

    def __init__(self, store: PortableStore) -> None:
        self.root = store.root / "transcription"
        self.tools = self.root / "tools"
        self.model = self.root / "models" / "ggml-base-q5_1.bin"
        self.stop_event = threading.Event()
        self._processes: list[subprocess.Popen] = []

    @property
    def ready(self) -> bool:
        return self._find_tool("whisper-cli") is not None and self._find_tool("ffmpeg") is not None and self.model.is_file()

    def stop(self) -> None:
        self.stop_event.set()
        for process in tuple(self._processes):
            try:
                process.terminate()
            except OSError:
                pass

    def _find_tool(self, name: str) -> Path | None:
        executable = f"{name}.exe" if sys.platform == "win32" else name
        local = next(self.tools.rglob(executable), None) if self.tools.exists() else None
        system = shutil.which(name)
        return local or (Path(system) if system else None)

    def install(self, progress: Callable[[str], None] | None = None) -> None:
        if sys.platform != "win32":
            raise TranscriptError(tr("Automatic Whisper setup is currently available on Windows only."))
        self.tools.mkdir(parents=True, exist_ok=True)
        self.model.parent.mkdir(parents=True, exist_ok=True)
        if self._find_tool("whisper-cli") is None:
            self._download_archive(WHISPER_URL, self.tools / "whisper", progress)
        if self._find_tool("ffmpeg") is None:
            self._download_archive(FFMPEG_URL, self.tools / "ffmpeg", progress)
        if not self.model.is_file():
            self._download(MODEL_URL, self.model, progress)

    def _download(self, url: str, destination: Path, progress: Callable[[str], None] | None) -> None:
        if progress:
            progress(tr("Downloading optional transcription components..."))
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        temporary = destination.with_suffix(destination.suffix + ".part")
        try:
            with urllib.request.urlopen(request, timeout=60, context=TLS_CONTEXT) as response, temporary.open("wb") as output:
                shutil.copyfileobj(response, output, length=1024 * 1024)
            temporary.replace(destination)
        except Exception:
            temporary.unlink(missing_ok=True)
            raise

    def _download_archive(self, url: str, destination: Path, progress: Callable[[str], None] | None) -> None:
        destination.mkdir(parents=True, exist_ok=True)
        archive = destination / "download.zip"
        self._download(url, archive, progress)
        try:
            with zipfile.ZipFile(archive) as zipped:
                for member in zipped.infolist():
                    target = (destination / member.filename).resolve()
                    if destination.resolve() not in target.parents and target != destination.resolve():
                        raise TranscriptError(tr("Invalid transcription component archive."))
                zipped.extractall(destination)
        finally:
            archive.unlink(missing_ok=True)

    def transcribe(
        self,
        audio_url: str | Path,
        update: Callable[[Transcript], None],
        *,
        audio_path: Path | None = None,
        audio_ready: Callable[[Path], None] | None = None,
    ) -> Transcript:
        ffmpeg = self._find_tool("ffmpeg")
        whisper = self._find_tool("whisper-cli")
        if not ffmpeg or not whisper or not self.model.is_file():
            raise WhisperSetupRequired(tr("Whisper transcription components are not installed."))
        self.stop_event.clear()
        self.root.mkdir(parents=True, exist_ok=True)
        source: str | Path = audio_url
        if audio_path is not None:
            audio_path.parent.mkdir(parents=True, exist_ok=True)
            if not audio_path.is_file():
                temporary = audio_path.with_suffix(audio_path.suffix + ".part")
                request = urllib.request.Request(
                    audio_url, headers={"User-Agent": USER_AGENT}
                )
                try:
                    with urllib.request.urlopen(
                        request, timeout=60, context=TLS_CONTEXT
                    ) as response, temporary.open("wb") as output:
                        shutil.copyfileobj(response, output, length=1024 * 1024)
                    temporary.replace(audio_path)
                except Exception:
                    temporary.unlink(missing_ok=True)
                    raise
            source = audio_path
            if audio_ready:
                audio_ready(audio_path)
        lines: list[TranscriptLine] = []
        with tempfile.TemporaryDirectory(prefix="blindspot-transcript-", dir=self.root) as folder_name:
            folder = Path(folder_name)
            pattern = str(folder / "segment-%06d.wav")
            decoder_command = [
                str(ffmpeg), "-nostdin", "-loglevel", "error",
            ]
            if isinstance(source, str):
                decoder_command.extend(["-user_agent", USER_AGENT])
            decoder_command.extend([
                "-i", str(source), "-vn", "-ac", "1", "-ar", "16000",
                "-f", "segment", "-segment_time", "60", "-c:a",
                "pcm_s16le", pattern,
            ])
            decoder = subprocess.Popen(
                decoder_command,
                creationflags=(
                    subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
                ),
            )
            self._processes.append(decoder)
            index = 0
            try:
                while not self.stop_event.is_set():
                    segment = folder / f"segment-{index:06d}.wav"
                    next_segment = folder / f"segment-{index + 1:06d}.wav"
                    if segment.exists() and (next_segment.exists() or decoder.poll() is not None):
                        output_base = folder / f"result-{index:06d}"
                        process = subprocess.Popen([
                            str(whisper), "-m", str(self.model), "-f", str(segment),
                            "-ml", str(WHISPER_MAX_LINE_CHARACTERS), "-sow",
                            "-osrt", "-of", str(output_base), "-np",
                        ], creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0)
                        self._processes.append(process)
                        process.wait()
                        self._processes.remove(process)
                        if self.stop_event.is_set():
                            break
                        result = output_base.with_suffix(".srt")
                        if process.returncode or not result.is_file():
                            raise TranscriptError(tr("Whisper could not transcribe this episode."))
                        parsed = parse_transcript(result.read_bytes(), "application/x-subrip")
                        offset = index * 60_000
                        lines.extend(TranscriptLine(line.start_ms + offset, line.text) for line in parsed.lines)
                        update(Transcript(tuple(lines), "whisper", False))
                        segment.unlink(missing_ok=True)
                        result.unlink(missing_ok=True)
                        index += 1
                        continue
                    if decoder.poll() is not None:
                        break
                    time.sleep(0.2)
            finally:
                if decoder.poll() is None:
                    decoder.terminate()
                decoder.wait()
                if decoder in self._processes:
                    self._processes.remove(decoder)
        if not lines:
            if self.stop_event.is_set():
                raise TranscriptUnavailable(tr("Transcription stopped before any text was produced."))
            if decoder.returncode:
                raise TranscriptError(tr("The episode audio could not be decoded."))
            raise TranscriptUnavailable(tr("No speech was found in this episode."))
        return Transcript(tuple(lines), "whisper", not self.stop_event.is_set())
