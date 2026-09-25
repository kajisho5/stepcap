"""Voice notes (RM-066): microphone -> WAV -> local speech-to-text -> steps and skill."""

from __future__ import annotations

import json
import os
import time
import wave
from pathlib import Path

import pytest

from stepcap import voice
from stepcap.build.pipeline import BuildOptions, run_build
from stepcap.cli import main
from stepcap.session import VOICE_FILE, load_session, read_json, write_json
from stepcap.simulate import simulate
from stepcap.skill.run import SkillOptions, run_skill

JFK = Path(__file__).parent / "fixtures" / "jfk.wav"  # public domain speech, 16 kHz mono


class FakeStream:
    """Stands in for sounddevice.RawInputStream: the test pushes audio blocks."""

    def __init__(self, callback):
        self.callback = callback
        self.running = False

    def start(self):
        self.running = True

    def stop(self):
        self.running = False

    def close(self):
        pass

    def feed(self, samples: bytes):
        self.callback(samples, len(samples) // 2, None, None)


def test_recorder_writes_wav_and_silences_pauses(tmp_path):
    streams = []

    def factory(cb):
        streams.append(FakeStream(cb))
        return streams[-1]

    t0 = time.monotonic() - 2.0
    rec = voice.AudioRecorder(tmp_path / "audio.wav", t0, stream_factory=factory)
    rec.start()
    assert 1.9 <= rec.offset <= 3.0  # seconds after the recording's ts 0
    s = streams[0]
    s.feed(b"\x10\x00" * 1600)  # 0.1 s of sound
    rec.paused.set()
    s.feed(b"\x10\x00" * 1600)  # said while paused: must not be kept
    rec.paused.clear()
    s.feed(b"\x20\x00" * 1600)
    info = rec.stop()
    assert info == {"file": "audio.wav", "offset": rec.offset, "seconds": 0.3}
    with wave.open(str(tmp_path / "audio.wav")) as w:
        assert (w.getframerate(), w.getnchannels(), w.getsampwidth()) == (16000, 1, 2)
        data = w.readframes(w.getnframes())
    assert data[:3200] == b"\x10\x00" * 1600
    assert data[3200:6400] == b"\0" * 3200
    assert data[6400:] == b"\x20\x00" * 1600


def test_microphone_error_is_reported(tmp_path):
    def broken(cb):
        raise OSError("no default input device")

    rec = voice.AudioRecorder(tmp_path / "audio.wav", time.monotonic(), stream_factory=broken)
    with pytest.raises(voice.VoiceError, match="cannot open the microphone"):
        rec.start()
    assert not (tmp_path / "audio.wav").exists()


def _session_with_audio(tmp_path, spec):
    s = tmp_path / "s"
    simulate(spec, s)
    meta = read_json(s / "session.json")
    meta["audio"] = {"file": "audio.wav", "offset": 1.0, "seconds": 11.0}
    write_json(s / "session.json", meta)
    (s / "audio.wav").write_bytes(JFK.read_bytes())
    return s


def test_transcribe_session_with_a_stand_in_engine(tmp_path, spec):
    s = _session_with_audio(tmp_path, spec)
    token = "ghp_" + "a" * 36

    def engine(path, model, language):
        assert path == s / "audio.wav" and model == "tiny"
        return [
            voice.Segment(0.2, 1.1, "First open the projects page."),
            voice.Segment(4.0, 5.0, f"the token is {token}"),
            voice.Segment(6.0, 6.5, "   "),
        ], "en"

    res = voice.transcribe_session(s, "tiny", None, keep_audio=False, engine=engine)
    assert res["segments"] == 2 and not (s / "audio.wav").exists()
    lines = [json.loads(x) for x in (s / VOICE_FILE).read_text("utf-8").splitlines()]
    assert lines[0] == {
        "kind": "voice",
        "ts": 1.2,
        "end": 2.1,
        "text": lines[0]["text"],
        "lang": "en",
    }
    assert token not in json.dumps(lines)  # secrets masked before writing
    meta = read_json(s / "session.json")
    assert (
        meta["audio"]["transcribed"] and meta["audio"]["deleted"] and meta["audio"]["segments"] == 2
    )
    _, events = load_session(s)
    said = [e for e in events if e["kind"] == "voice"]
    steps = {e["id"]: e["ts"] for e in events if "id" in e}
    # each note is placed before the first step at or after the time it was said
    assert said[0]["seq"] == min(i for i, t in steps.items() if t >= 1.2)
    with pytest.raises(voice.VoiceError, match="does not exist"):
        voice.transcribe_session(s, engine=engine)


def test_keep_audio(tmp_path, spec):
    s = _session_with_audio(tmp_path, spec)
    voice.transcribe_session(s, keep_audio=True, engine=lambda p, m, lang: ([], None))
    assert (s / "audio.wav").exists() and (s / VOICE_FILE).read_text("utf-8") == ""


def test_narration_reaches_guide_and_skill(tmp_path, spec):
    spec = json.loads(json.dumps(spec))
    spec["events"].insert(0, {"kind": "say", "text": "We are setting up the Q3 launch project."})
    spec["events"].insert(3, {"kind": "say", "text": "Use the name from the brief."})
    spec["events"] = [e for e in spec["events"] if e["kind"] != "manual"]  # no F7 notes
    s = tmp_path / "s"
    simulate(spec, s)
    run_build(s, BuildOptions(formats=("md",)))
    doc = read_json(s / "steps.json")
    typed = next(x for x in doc["steps"] if x["kind"] == "type")
    assert typed["description"].endswith("Use the name from the brief.")
    assert "Use the name from the brief." in (s / "guide.md").read_text("utf-8")
    # an edited description is kept on rebuild; untouched ones follow the language
    typed["description"] = "My own words"
    write_json(s / "steps.json", doc)
    run_build(s, BuildOptions(formats=("md",), lang="ja"))
    doc = read_json(s / "steps.json")
    assert next(x for x in doc["steps"] if x["kind"] == "type")["description"] == "My own words"

    res = run_skill(s, SkillOptions(out_dir=tmp_path / "o", name="demo"))
    assert res.ok, res.problems
    md = (tmp_path / "o" / "demo" / "SKILL.md").read_text("utf-8")
    assert "From the narration: “We are setting up the Q3 launch project.”" in md
    assert "Narration: “Use the name from the brief.”" in md


def test_cli_transcribe_and_record_flags(tmp_path, spec, capsys, monkeypatch):
    s = _session_with_audio(tmp_path, spec)
    monkeypatch.setattr(
        voice, "transcribe", lambda p, m, lang: ([voice.Segment(0, 1, "hello there")], "en")
    )
    monkeypatch.setattr(
        voice.transcribe_session, "__defaults__", ("base", None, False, voice.transcribe)
    )
    assert main(["transcribe", str(s), "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["segments"] == 1 and data["lines"][0]["text"] == "hello there"
    assert main(["transcribe", str(s)]) == 1  # audio already transcribed and deleted
    assert "does not exist" in capsys.readouterr().err

    from stepcap.gui import controller as ctl

    assert ctl.record_argv(tmp_path / "x", False, False, False, voice=True)[-1] == "--voice"
    monkeypatch.setattr(voice, "missing", lambda transcribe=True: ["sounddevice"])
    assert main(["record", "--voice", "-o", str(tmp_path / "r")]) == 1
    assert "stepcap[voice]" in capsys.readouterr().err
    assert ctl.voice_hint() == voice.INSTALL_HINT


def test_read_wav_rejects_other_formats(tmp_path):
    pytest.importorskip("numpy")
    p = tmp_path / "stereo.wav"
    with wave.open(str(p), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(44100)
        w.writeframes(b"\0" * 400)
    with pytest.raises(voice.VoiceError, match="16 kHz mono"):
        voice.read_wav(p)


@pytest.mark.skipif(
    not os.environ.get("STEPCAP_TEST_WHISPER"),
    reason="set STEPCAP_TEST_WHISPER=1 (downloads a model)",
)
def test_real_speech_to_text():
    pytest.importorskip("faster_whisper")
    segments, lang = voice.transcribe(JFK, "tiny", None)
    text = " ".join(s.text for s in segments).lower()
    assert lang == "en"
    assert "ask not what your country can do for you" in text
