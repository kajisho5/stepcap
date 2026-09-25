"""`stepcap mcp` (RM-044): the tools directly, and over stdio with the MCP SDK client."""

import asyncio
import io
import json
import sys

import pytest
from PIL import Image

from stepcap.mcp_server import ToolError, Tools
from stepcap.simulate import simulate


@pytest.fixture
def root(tmp_path, spec):
    spec = json.loads(json.dumps(spec))
    spec["accessibility"] = True
    spec["screens"]["home"]["url"] = "https://tasks.example.com/projects"
    spec["events"].insert(0, {"kind": "say", "text": "Set up the launch project."})
    simulate(spec, tmp_path / "demo", record_urls=True)
    return tmp_path


def test_tools_directly(root, tmp_path):
    t = Tools([root])
    sessions = t.list_sessions()["sessions"]
    assert [s["session"] for s in sessions] == [str(root / "demo")]
    assert sessions[0]["steps"] == 12 and sessions[0]["voice_notes"]

    steps = t.get_steps("demo")  # relative to the first root
    assert steps["title"].startswith("Create a project")
    first = steps["steps"][0]
    assert first["element"] == {"name": "+ New project", "role": "button"}
    assert "Browser at `https://tasks.example.com/projects`" in first["context"]
    assert any("Narration" in c for c in first["context"])
    typed = next(s for s in steps["steps"] if s["kind"] == "type")
    assert typed["input"]["name"] == "project_name"

    png = t.step_image(str(root / "demo"), 1)
    img = Image.open(io.BytesIO(png))
    assert img.format == "PNG" and img.width == 1280
    with pytest.raises(ToolError, match="step must be 1-12"):
        t.step_image("demo", 13)

    built = t.build_guide("demo", "ja")
    assert (root / "demo" / "guide.html").is_file() and built["steps"] == 12
    with pytest.raises(ToolError, match="lang"):
        t.build_guide("demo", "fr")

    home = tmp_path / "home"
    t = Tools([root], home=home)
    res = t.make_skill("demo", name="launch", install="claude")
    assert res["ok"] and res["installed_to"] == str(home / ".claude" / "skills" / "launch")
    assert res["info"]["coverage"]["score"] == 1.0
    with pytest.raises(ToolError, match="already exists"):
        t.make_skill("demo", name="launch", install="claude")
    assert t.make_skill("demo", name="launch", install="claude", replace=True)["ok"]
    checked = t.check_skill(res["skill_dir"], "demo")
    assert checked["ok"] and checked["coverage"]["total"] > 0


def test_paths_outside_roots_are_refused(root, tmp_path):
    t = Tools([root / "demo"])
    with pytest.raises(ToolError, match="outside the allowed folders"):
        t.get_steps(str(tmp_path))
    with pytest.raises(ToolError, match="outside the allowed folders"):
        t.get_steps("../")
    with pytest.raises(ToolError, match="not a stepcap recording"):
        Tools([root]).get_steps(str(root))
    with pytest.raises(ToolError, match="outside"):
        Tools([root]).make_skill("demo", out_dir="/tmp/elsewhere-stepcap")


def test_cli_without_sdk(monkeypatch, capsys):
    import builtins

    real_import = builtins.__import__

    def fake_import(name, *a, **kw):
        if name.startswith("mcp"):
            raise ImportError("No module named 'mcp'")
        return real_import(name, *a, **kw)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    from stepcap.cli import main

    assert main(["mcp"]) == 1
    assert "stepcap[mcp]" in capsys.readouterr().err


def test_over_stdio_with_the_sdk_client(root):
    mcp = pytest.importorskip("mcp")

    async def run():
        params = mcp.StdioServerParameters(
            command=sys.executable, args=["-m", "stepcap", "mcp", "--root", str(root)]
        )
        async with mcp.Client(params) as c:
            names = {t.name for t in (await c.list_tools()).tools}
            assert names == {
                "list_sessions",
                "get_steps",
                "step_image",
                "build_guide",
                "make_skill",
                "check_skill",
            }
            listed = (await c.call_tool("list_sessions", {})).structured_content
            session = listed["sessions"][0]["session"]
            img = await c.call_tool("step_image", {"session": session, "step": 2})
            assert img.content[0].type == "image" and img.content[0].mime_type == "image/png"
            bad = await c.call_tool("get_steps", {"session": "/"})
            assert bad.is_error and "outside the allowed folders" in bad.content[0].text

    asyncio.run(asyncio.wait_for(run(), 60))
