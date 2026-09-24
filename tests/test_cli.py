import json

from stepcap import __version__
from stepcap.cli import main


def test_version(capsys):
    try:
        main(["--version"])
    except SystemExit as exc:
        assert exc.code == 0
    assert __version__ in capsys.readouterr().out


def test_no_command_prints_help(capsys):
    assert main([]) == 2
    assert "record" in capsys.readouterr().out


def test_simulate_then_build_json(tmp_path, spec, capsys):
    ev = tmp_path / "ev.json"
    ev.write_text(json.dumps(spec), encoding="utf-8")
    out = tmp_path / "demo"
    assert main(["simulate", str(ev), "-o", str(out), "--json"]) == 0
    res = json.loads(capsys.readouterr().out)
    assert res["events"] == 12
    assert main(["build", str(out), "-f", "md,html", "--json"]) == 0
    res = json.loads(capsys.readouterr().out)
    assert res["steps"] == 12 and "guide.html" in res["outputs"]
    # second simulate into the same dir is refused (input overwrite guard)
    assert main(["simulate", str(ev), "-o", str(out)]) == 1
    assert "not empty" in capsys.readouterr().err


def test_build_errors_exit_nonzero(tmp_path, capsys):
    assert main(["build", str(tmp_path / "nope")]) == 1
    assert "error" in capsys.readouterr().err
    assert main(["build", str(tmp_path), "-f", "pdf"]) == 1


def test_simulate_dry_run(tmp_path, spec, capsys):
    ev = tmp_path / "ev.json"
    ev.write_text(json.dumps(spec), encoding="utf-8")
    assert main(["simulate", str(ev), "-o", str(tmp_path / "x"), "--dry-run"]) == 0
    assert not (tmp_path / "x").exists()


def test_record_rejects_bad_hotkeys(capsys):
    assert main(["record", "--hotkey-stop", "F7"]) == 2
    assert "different" in capsys.readouterr().err
