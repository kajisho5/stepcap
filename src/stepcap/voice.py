"""Voice notes: record the microphone while recording steps, then turn the speech
into text on this computer (RM-066). Off by default (`record --voice`).

- Recording: ``sounddevice`` (PortAudio), 16 kHz mono 16-bit WAV in the session
  (``audio.wav``). While recording is paused, silence is written instead of the
  microphone, so nothing said during a pause is kept and the timeline stays aligned.
- Speech to text: ``faster-whisper`` on the CPU. The model (default ``base``,
  ~150 MB) is downloaded once from Hugging Face and cached; after that it works
  offline. The audio never leaves the computer.
- Result: ``voice.jsonl`` with one line per spoken segment (secrets masked).
  ``load_session`` turns them into ``voice`` context events placed before the
  step that follows them. ``audio.wav`` is deleted after a successful
  transcription unless ``--keep-audio``.

Both libraries are optional: ``pip install "stepcap[voice]"``.
"""

from __future__ import annotations

import contextlib
import json
import queue
import threading
import time
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from stepcap.redact import redact_text
from stepcap.session import VOICE_FILE

SAMPLE_RATE = 16000
AUDIO_FILE = "audio.wav"
DEFAULT_MODEL = "base"
MODELS = ("tiny", "base", "small", "medium", "large-v3")
INSTALL_HINT = 'pip install "stepcap[voice]"'
BINARY_HINT = "use the voice edition of the binary (stepcap-voice-*) from the Releases page"


class VoiceError(Exception):
    pass


@dataclass
class Segment:
    start: float
    end: float
    text: str


def missing(transcribe: bool = True) -> list[str]:
    """Python modules that voice notes need but are not installed (checked without
    importing them: faster-whisper takes seconds to import)."""
    from importlib.util import find_spec

    mods = ("sounddevice", "faster_whisper") if transcribe else ("sounddevice",)
    out = []
    for mod in mods:
        try:
            found = find_spec(mod) is not None
        except (ImportError, ValueError):
            found = False
        if not found:
            out.append(mod)
    return out


def install_hint() -> str:
    import sys

    return BINARY_HINT if getattr(sys, "frozen", False) else INSTALL_HINT


def probe() -> dict[str, Any]:
    """For `stepcap doctor`: what voice notes would use on this computer."""
    out: dict[str, Any] = {"missing": missing()}
    if "sounddevice" not in out["missing"]:
        try:
            import sounddevice as sd

            dev = sd.query_devices(kind="input")
            out["microphone"] = dev.get("name") if isinstance(dev, dict) else str(dev)
        except Exception as exc:
            out["microphone_error"] = str(exc)
    return out


class AudioRecorder:
    """Microphone -> 16-bit mono WAV, written on a thread (never in the audio callback)."""

    def __init__(self, path: Path, t0: float, stream_factory=None) -> None:
        self.path = Path(path)
        self.t0 = t0
        self.paused = threading.Event()
        self.offset = 0.0
        self.frames = 0
        self.error: str | None = None
        self._q: queue.Queue[bytes | None] = queue.Queue()
        self._factory = stream_factory
        self._stream: Any = None
        self._thread: threading.Thread | None = None

    def _callback(self, indata, frames, time_info, status) -> None:
        data = bytes(indata)
        if self.paused.is_set():
            data = b"\0" * len(data)
        self._q.put(data)

    def _writer(self, wav: wave.Wave_write) -> None:
        while True:
            chunk = self._q.get()
            if chunk is None:
                break
            wav.writeframes(chunk)
            self.frames += len(chunk) // 2

    def start(self) -> None:
        if self._factory is None:
            try:
                import sounddevice as sd
            except Exception as exc:
                raise VoiceError(f"cannot record audio ({exc}); {install_hint()}") from exc

            def factory(callback):
                return sd.RawInputStream(
                    samplerate=SAMPLE_RATE, channels=1, dtype="int16", callback=callback
                )

            self._factory = factory
        wav = wave.open(str(self.path), "wb")  # noqa: SIM115 - closed in stop() / on error
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(SAMPLE_RATE)
        try:
            self._stream = self._factory(self._callback)
            self._stream.start()
        except Exception as exc:
            wav.close()
            with contextlib.suppress(OSError):
                self.path.unlink()
            raise VoiceError(f"cannot open the microphone: {exc}") from exc
        self.offset = round(time.monotonic() - self.t0, 3)
        self._thread = threading.Thread(target=self._writer, args=(wav,), daemon=True)
        self._thread.start()
        self._wav = wav

    def stop(self) -> dict[str, Any]:
        if self._stream is not None:
            with contextlib.suppress(Exception):
                self._stream.stop()
            with contextlib.suppress(Exception):
                self._stream.close()
        self._q.put(None)
        if self._thread is not None:
            self._thread.join(10)
            self._wav.close()
        return {
            "file": self.path.name,
            "offset": self.offset,
            "seconds": round(self.frames / SAMPLE_RATE, 2),
        }


def read_wav(path: Path):
    """16 kHz mono float32 samples (numpy) from a WAV written by AudioRecorder."""
    import numpy as np

    with wave.open(str(path), "rb") as w:
        if w.getsampwidth() != 2 or w.getnchannels() != 1 or w.getframerate() != SAMPLE_RATE:
            raise VoiceError(f"{path}: expected 16 kHz mono 16-bit PCM")
        raw = w.readframes(w.getnframes())
    return np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0


def transcribe(
    path: Path, model: str = DEFAULT_MODEL, language: str | None = None
) -> tuple[list[Segment], str | None]:
    """Speech in ``path`` -> segments (seconds from the start of the file), language."""
    try:
        from faster_whisper import WhisperModel
    except Exception as exc:
        raise VoiceError(f"speech-to-text is not installed ({exc}); {install_hint()}") from exc
    audio = read_wav(path)
    if len(audio) < SAMPLE_RATE // 4:
        return [], language
    whisper = WhisperModel(model, device="cpu", compute_type="int8")
    segments, info = whisper.transcribe(audio, language=language, vad_filter=True)
    out = [Segment(round(s.start, 2), round(s.end, 2), s.text.strip()) for s in segments]
    return [s for s in out if s.text], getattr(info, "language", language)


def write_voice(
    session: Path, segments: list[Segment], offset: float, lang: str | None
) -> list[dict[str, Any]]:
    lines = []
    for s in segments:
        text = redact_text(s.text).strip()
        if not text:
            continue
        ev: dict[str, Any] = {
            "kind": "voice",
            "ts": round(offset + s.start, 3),
            "end": round(offset + s.end, 3),
            "text": text,
        }
        if lang:
            ev["lang"] = lang
        lines.append(ev)
    with open(Path(session) / VOICE_FILE, "w", encoding="utf-8", newline="\n") as fh:
        for ev in lines:
            fh.write(json.dumps(ev, ensure_ascii=False) + "\n")
    return lines


def transcribe_session(
    session: Path,
    model: str = DEFAULT_MODEL,
    language: str | None = None,
    keep_audio: bool = False,
    engine=None,
) -> dict[str, Any]:
    """Transcribe SESSION/audio.wav into voice.jsonl and update session.json."""
    from stepcap.session import SESSION_FILE, read_json, write_json

    session = Path(session)
    meta = read_json(session / SESSION_FILE) if (session / SESSION_FILE).is_file() else {}
    audio = meta.get("audio") or {}
    wav = session / audio.get("file", AUDIO_FILE)
    if not wav.is_file():
        raise VoiceError(f"{wav} does not exist (record with --voice, or it was already deleted)")
    segments, lang = (engine or transcribe)(wav, model, language)
    lines = write_voice(session, segments, float(audio.get("offset", 0.0)), lang)
    audio.update({"transcribed": True, "model": model, "language": lang, "segments": len(lines)})
    if not keep_audio:
        wav.unlink()
        audio["deleted"] = True
    meta["audio"] = audio
    write_json(session / SESSION_FILE, meta)
    return {"session": str(session), "segments": len(lines), "language": lang, "lines": lines}
