"""The JSON Schemas describe what stepcap actually writes (RM-046)."""

from __future__ import annotations

import json

import pytest

from stepcap import schemas
from stepcap.build.pipeline import BuildOptions, run_build
from stepcap.cli import main
from stepcap.session import load_session, read_json
from stepcap.shell import parse_record
from stepcap.simulate import simulate

jsonschema = pytest.importorskip("jsonschema")
referencing = pytest.importorskip("referencing")


def _validator(name: str):
    from referencing.jsonschema import DRAFT202012

    registry = referencing.Registry().with_resources(
        (s["$id"], DRAFT202012.create_resource(s)) for s in map(schemas.load, schemas.NAMES)
    )
    schema = schemas.load(name)
    jsonschema.Draft202012Validator.check_schema(schema)
    return jsonschema.Draft202012Validator(schema, registry=registry)


def _check(name: str, doc) -> None:
    errors = sorted(_validator(name).iter_errors(doc), key=str)
    assert not errors, "\n".join(f"{list(e.absolute_path)}: {e.message}" for e in errors)


def _events(session):
    return [json.loads(line) for line in (session / "events.jsonl").read_text("utf-8").splitlines()]


def test_schemas_are_valid_and_listed():
    for name in schemas.NAMES:
        schema = schemas.load(name)
        jsonschema.Draft202012Validator.check_schema(schema)
        assert schema["$id"].endswith(f"/{name}.schema.json")
    with pytest.raises(ValueError):
        schemas.path("nope")


def test_simulated_session_matches(tmp_path, spec):
    spec = json.loads(json.dumps(spec))
    spec["accessibility"] = True
    spec["screens"]["home"]["url"] = "https://tasks.example.com/projects?token=abc"
    spec["events"].insert(3, {"kind": "copy", "screen": "dialog", "text": "Q3 launch plan"})
    spec["events"].append({"kind": "terminal", "command": "git status", "exit": 1})
    spec["events"].insert(0, {"kind": "say", "text": "Set up the launch project."})
    session = tmp_path / "s"
    simulate(spec, session, record_urls=True, record_clipboard=True)
    run_build(session, BuildOptions(formats=("md",)))
    _check("session", read_json(session / "session.json"))
    kinds = set()
    for ev in _events(session):
        _check("event", ev)
        kinds.add(ev["kind"])
    expected = {"click", "type", "drag", "scroll", "key", "manual"}
    expected |= {"app_switch", "clipboard", "url"}
    assert expected <= kinds
    # a `stepcap shell` line in terminal.jsonl becomes a context event on load
    rec = parse_record(b"1727200000.5\t0\t/home/me\tgit pull\n")
    (session / "terminal.jsonl").write_text(json.dumps(rec) + "\n", encoding="utf-8")
    for line in (session / "voice.jsonl").read_text("utf-8").splitlines():
        _check("voice", json.loads(line))
    _, merged = load_session(session)
    for ev in merged:
        _check("event", ev)
    assert sum(ev["kind"] == "terminal" for ev in merged) == 2
    assert any(ev["kind"] == "voice" for ev in merged)
    doc = read_json(session / "steps.json")
    _check("steps", doc)
    assert any(s.get("element") for s in doc["steps"]) and any(s.get("input") for s in doc["steps"])


def test_edited_steps_match(demo_session):
    from stepcap.edit.server import EditApp

    run_build(demo_session, BuildOptions(formats=("md",)))
    srv = EditApp(demo_session)
    doc = read_json(demo_session / "steps.json")
    first = doc["steps"][0]
    srv.set_box({"id": first["id"], "rect": None})  # removed frame -> box null
    srv.set_arrows({"id": first["id"], "arrows": [[10, 10, 200, 120]]})
    _check("steps", read_json(demo_session / "steps.json"))


def test_recorder_events_match(harness):
    h = harness(record_typing=True)
    h.click(0.0, 100, 100)
    h.click(1.0, 300, 300)
    h.proc.on_mouse(1.05, 300, 300, "left", True)
    h.proc.on_mouse(1.10, 300, 300, "left", False)  # double click
    h.click(3.0, 50, 60, button="right")
    h.type(4.0, "hello world")
    h.proc.on_mouse(6.0, 10, 10, "left", True)
    h.proc.on_mouse(6.4, 400, 300, "left", False)  # drag
    h.proc.on_scroll(8.0, 500, 500, 0, -2)
    h.proc.on_key(10.0, "ctrl", True)
    h.proc.on_key(10.02, "s", True)
    h.proc.on_key(10.03, "s", False)
    h.proc.on_key(10.05, "ctrl", False)
    evs = h.done()
    assert {e["kind"] for e in evs} >= {"click", "type", "drag", "scroll", "key"}
    for ev in evs:
        _check("event", ev)


def test_terminal_lines_match():
    rec = parse_record(b"1727200000.5\t0\t/home/me\tgit pull\n")
    _check("terminal", rec)


def test_schema_rejects_wrong_data():
    with pytest.raises(AssertionError):
        _check("event", {"kind": "click", "ts": 1.0, "seq": 3})  # a step needs an id
    with pytest.raises(AssertionError):
        _check("event", {"id": 1, "kind": "type", "ts": 1.0})  # chars / masked missing
    with pytest.raises(AssertionError):
        _check("steps", {"format": 2, "steps": [{"id": "s1", "kind": "wave", "title": "x"}]})


def test_cli_schema(capsys):
    assert main(["schema", "steps"]) == 0
    assert json.loads(capsys.readouterr().out)["title"] == "stepcap steps.json"
    assert main(["schema"]) == 0
    assert set(json.loads(capsys.readouterr().out)) == set(schemas.NAMES)
    assert main(["schema", "event", "--path"]) == 0
    assert capsys.readouterr().out.strip().endswith("event.schema.json")
