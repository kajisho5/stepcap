"""`stepcap edit`: a local web UI to reorder, delete, rename and blur steps.

Standard library only (http.server). Binds to 127.0.0.1 by default and makes
no external requests. Blur is applied to work/ copies; raw/ is never touched.

Hardening for a local, unauthenticated server:
- Host header must be the bound address (blocks DNS-rebinding attacks)
- state-changing requests must be JSON POSTs whose Origin (if sent) matches
  (a cross-site form cannot send application/json without a CORS preflight)
- screenshot ids are validated, request bodies are size-limited
"""

from __future__ import annotations

import contextlib
import json
import re
import shutil
import sys
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import resources
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from PIL import Image, ImageFilter

from stepcap.build import steps as steps_mod
from stepcap.build.annotate import BOX_KINDS, MARKERS
from stepcap.build.pipeline import (
    CHECKLIST_HTML,
    GUIDE_HTML,
    BuildOptions,
    BuildResult,
    load_or_create_steps,
    parse_formats,
    run_build,
)
from stepcap.session import STEPS_FILE, SessionError, is_session, write_json

MAX_BODY = 1_000_000
MAX_ARROWS = 10
_SID = re.compile(r"^[A-Za-z0-9]{1,32}$")
EDITABLE = ("title", "description")


def _check_input(value: Any) -> dict[str, Any]:
    """``input`` of a type step: {"name": "project_name", "variable": true}."""
    if not isinstance(value, dict):
        raise ApiError(400, "input must be an object")
    name, variable = value.get("name"), value.get("variable")
    if not isinstance(name, str) or not steps_mod.INPUT_NAME.match(name):
        raise ApiError(
            400, "input name must start with a-z and use a-z, 0-9 or _ (max 40 characters)"
        )
    if not isinstance(variable, bool):
        raise ApiError(400, "input variable must be true or false")
    return {"name": name, "variable": variable}


class ApiError(Exception):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status


class EditApp:
    """All edit operations, independent of HTTP (tested directly and via HTTP)."""

    def __init__(self, session: Path) -> None:
        self.session = Path(session)
        if not is_session(self.session):
            raise SessionError(f"{self.session} is not a stepcap session")
        self.lock = threading.Lock()

    # --------------------------------------------------------------- steps
    def get_steps(self) -> dict[str, Any]:
        with self.lock:
            doc = steps_mod.load_steps(self.session)
            if doc is None:
                _, doc = load_or_create_steps(self.session, BuildOptions(), BuildResult("", 0))
                write_json(self.session / STEPS_FILE, doc)
            usage: dict[str, int] = {}
            for s in doc["steps"]:
                if s.get("screenshot"):
                    usage[s["screenshot"]] = usage.get(s["screenshot"], 0) + 1
            return {"doc": doc, "usage": usage, "session": self.session.name}

    def save_steps(self, body: dict[str, Any]) -> dict[str, Any]:
        items = body.get("steps")
        if not isinstance(items, list):
            raise ApiError(400, "'steps' must be a list")
        with self.lock:
            doc = steps_mod.load_steps(self.session)
            if doc is None:
                raise ApiError(409, "steps.json does not exist yet; reload the page")
            by_id = {s["id"]: s for s in doc["steps"]}
            new_steps, seen = [], set()
            for item in items:
                if not isinstance(item, dict) or item.get("id") not in by_id:
                    raise ApiError(
                        400,
                        f"unknown step id {item.get('id') if isinstance(item, dict) else item!r}",
                    )
                if item["id"] in seen:
                    raise ApiError(400, f"duplicate step id {item['id']}")
                seen.add(item["id"])
                step = by_id[item["id"]]
                for key in EDITABLE:
                    if key in item:
                        if not isinstance(item[key], str) or len(item[key]) > 5000:
                            raise ApiError(400, f"{key} must be a string (max 5000 chars)")
                        step[key] = item[key].strip() if key == "title" else item[key]
                if "input" in item and step.get("kind") == "type":
                    step["input"] = _check_input(item["input"])
                new_steps.append(step)
            doc["steps"] = new_steps
            if "title" in body:
                if not isinstance(body["title"], str) or not body["title"].strip():
                    raise ApiError(400, "title must be a non-empty string")
                if body["title"].strip() != doc.get("title"):
                    doc["title"] = body["title"].strip()
                    doc["auto_title"] = None
            write_json(self.session / STEPS_FILE, doc)
            return {"ok": True, "steps": len(new_steps), "deleted": len(by_id) - len(new_steps)}

    # --------------------------------------------------------------- images
    def _sid(self, sid: Any) -> str:
        if not isinstance(sid, str) or not _SID.match(sid):
            raise ApiError(400, "invalid screenshot id")
        if not steps_mod.raw_path(self.session, sid).exists():
            raise ApiError(404, f"screenshot {sid} not found")
        return sid

    def image_bytes(self, sid: str) -> bytes:
        sid = self._sid(sid)
        return steps_mod.ensure_work_copy(self.session, sid).read_bytes()

    def blur(self, body: dict[str, Any]) -> dict[str, Any]:
        sid = self._sid(body.get("screenshot"))
        rect = body.get("rect")
        if (
            not isinstance(rect, list)
            or len(rect) != 4
            or not all(isinstance(v, (int, float)) for v in rect)
        ):
            raise ApiError(400, "rect must be [x, y, width, height] in image pixels")
        with self.lock:
            path = steps_mod.ensure_work_copy(self.session, sid)
            img = Image.open(path).convert("RGB")
            x, y, w, h = (round(v) for v in rect)
            x0, y0 = max(0, min(x, x + w)), max(0, min(y, y + h))
            x1, y1 = min(img.width, max(x, x + w)), min(img.height, max(y, y + h))
            if x1 - x0 < 2 or y1 - y0 < 2:
                raise ApiError(400, "rectangle is empty or outside the image")
            region = img.crop((x0, y0, x1, y1))
            radius = max(8, min(x1 - x0, y1 - y0) / 4)
            # pixelate first so a Gaussian blur cannot be partially reversed
            small = region.resize(
                (max(1, (x1 - x0) // 12), max(1, (y1 - y0) // 12)), Image.Resampling.BOX
            )
            region = small.resize(region.size, Image.Resampling.NEAREST)
            region = region.filter(ImageFilter.GaussianBlur(radius))
            img.paste(region, (x0, y0))
            tmp = path.with_name(path.name + ".tmp")
            img.save(tmp, format="PNG")
            tmp.replace(path)
        return {"ok": True, "screenshot": sid, "rect": [x0, y0, x1 - x0, y1 - y0]}

    def set_box(self, body: dict[str, Any]) -> dict[str, Any]:
        """Set (``rect``) or remove (``rect: null``) the highlight frame of one step."""
        rect = body.get("rect")
        if rect is not None and (
            not isinstance(rect, list)
            or len(rect) != 4
            or not all(isinstance(v, (int, float)) for v in rect)
        ):
            raise ApiError(400, "rect must be [x, y, width, height] in image pixels, or null")
        with self.lock:
            doc = steps_mod.load_steps(self.session)
            if doc is None:
                raise ApiError(409, "steps.json does not exist yet; reload the page")
            step = next((s for s in doc["steps"] if s.get("id") == body.get("id")), None)
            if step is None:
                raise ApiError(400, f"unknown step id {body.get('id')!r}")
            if step.get("kind") not in BOX_KINDS:
                raise ApiError(400, "only click and typing steps can have a frame")
            box = None
            if rect is not None:
                w, h = step.get("image_size") or (10**6, 10**6)
                x, y, bw, bh = (round(v) for v in rect)
                x0, y0 = max(0, min(x, x + bw)), max(0, min(y, y + bh))
                x1, y1 = min(w, max(x, x + bw)), min(h, max(y, y + bh))
                if x1 - x0 < 3 or y1 - y0 < 3:
                    raise ApiError(400, "rectangle is empty or outside the image")
                box = [x0, y0, x1 - x0, y1 - y0]
            step["box"] = box
            step["box_source"] = "manual"
            write_json(self.session / STEPS_FILE, doc)
        return {"ok": True, "id": step["id"], "box": box}

    def set_arrows(self, body: dict[str, Any]) -> dict[str, Any]:
        """Replace the hand-drawn arrows of one step: ``[[x1, y1, x2, y2], ...]`` (tail, head)."""
        arrows = body.get("arrows")
        if not isinstance(arrows, list) or len(arrows) > MAX_ARROWS:
            raise ApiError(400, f"arrows must be a list of at most {MAX_ARROWS} items")
        with self.lock:
            doc = steps_mod.load_steps(self.session)
            if doc is None:
                raise ApiError(409, "steps.json does not exist yet; reload the page")
            step = next((s for s in doc["steps"] if s.get("id") == body.get("id")), None)
            if step is None:
                raise ApiError(400, f"unknown step id {body.get('id')!r}")
            if not step.get("screenshot"):
                raise ApiError(400, "this step has no screenshot")
            w, h = step.get("image_size") or (10**6, 10**6)
            clean = []
            for a in arrows:
                if (
                    not isinstance(a, list)
                    or len(a) != 4
                    or not all(isinstance(v, (int, float)) for v in a)
                ):
                    raise ApiError(400, "each arrow must be [x1, y1, x2, y2] in image pixels")
                x1, y1, x2, y2 = (round(v) for v in a)
                x1, x2 = (min(max(v, 0), w - 1) for v in (x1, x2))
                y1, y2 = (min(max(v, 0), h - 1) for v in (y1, y2))
                if abs(x2 - x1) + abs(y2 - y1) < 8:
                    raise ApiError(400, "arrow is too short")
                clean.append([x1, y1, x2, y2])
            if clean:
                step["arrows"] = clean
            else:
                step.pop("arrows", None)
            write_json(self.session / STEPS_FILE, doc)
        return {"ok": True, "id": step["id"], "arrows": clean}

    def set_options(self, body: dict[str, Any]) -> dict[str, Any]:
        """Guide-wide drawing options saved in steps.json (used by every build)."""
        with self.lock:
            doc = steps_mod.load_steps(self.session)
            if doc is None:
                raise ApiError(409, "steps.json does not exist yet; reload the page")
            if "marker" in body:
                if body["marker"] not in MARKERS:
                    raise ApiError(400, "marker must be 'box' or 'ring'")
                doc["marker"] = body["marker"]
            for key in ("spotlight", "auto_arrows"):
                if key in body:
                    if not isinstance(body[key], bool):
                        raise ApiError(400, f"{key} must be true or false")
                    doc[key] = body[key]
            write_json(self.session / STEPS_FILE, doc)
            return {
                "ok": True,
                "marker": doc.get("marker", "box"),
                "spotlight": bool(doc.get("spotlight", False)),
                "auto_arrows": bool(doc.get("auto_arrows", True)),
            }

    def reset_image(self, body: dict[str, Any]) -> dict[str, Any]:
        sid = self._sid(body.get("screenshot"))
        with self.lock:
            dst = steps_mod.work_path(self.session, sid)
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(steps_mod.raw_path(self.session, sid), dst)
        return {"ok": True, "screenshot": sid}

    # --------------------------------------------------------------- build
    def build(self, body: dict[str, Any]) -> dict[str, Any]:
        try:
            formats = parse_formats(str(body.get("formats") or "md,html,checklist"))
        except ValueError as exc:
            raise ApiError(400, str(exc)) from exc
        with self.lock:
            res = run_build(self.session, BuildOptions(formats=formats))
        return {"ok": True, **res.to_dict()}


def _ui_html() -> bytes:
    return resources.files("stepcap.edit").joinpath("ui.html").read_bytes()


def _favicon() -> bytes:
    return (resources.files("stepcap") / "assets" / "icon-32.png").read_bytes()


def make_handler(app: EditApp, allowed_hosts: set[str] | None):
    class Handler(BaseHTTPRequestHandler):
        server_version = "stepcap-edit"
        protocol_version = "HTTP/1.1"

        def log_message(self, fmt: str, *args: Any) -> None:  # quiet
            pass

        # ----------------------------------------------------------- helpers
        def _send(self, status: int, body: bytes, ctype: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            if ctype.startswith("text/html"):
                self.send_header(
                    "Content-Security-Policy",
                    "default-src 'self'; img-src 'self' data: blob:; style-src 'self' "
                    "'unsafe-inline'; script-src 'self' 'unsafe-inline'; connect-src 'self'; "
                    "frame-ancestors 'none'",
                )
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)

        def _json(self, status: int, data: Any) -> None:
            self._send(
                status,
                json.dumps(data, ensure_ascii=False).encode("utf-8"),
                "application/json; charset=utf-8",
            )

        def _host_ok(self) -> bool:
            if allowed_hosts is None:
                return True
            return (self.headers.get("Host") or "").lower() in allowed_hosts

        def _read_json(self) -> dict[str, Any]:
            ctype = (self.headers.get("Content-Type") or "").split(";")[0].strip().lower()
            if ctype != "application/json":
                raise ApiError(415, "Content-Type must be application/json")
            origin = self.headers.get("Origin")
            if (
                origin
                and allowed_hosts is not None
                and urlsplit(origin).netloc.lower() not in allowed_hosts
            ):
                raise ApiError(403, "cross-origin request refused")
            length = int(self.headers.get("Content-Length") or 0)
            if length > MAX_BODY:
                raise ApiError(413, "request too large")
            try:
                data = json.loads(self.rfile.read(length) or b"{}")
            except json.JSONDecodeError as exc:
                raise ApiError(400, f"invalid JSON: {exc}") from exc
            if not isinstance(data, dict):
                raise ApiError(400, "JSON body must be an object")
            return data

        # ----------------------------------------------------------- routes
        def do_GET(self) -> None:
            if not self._host_ok():
                return self._json(403, {"error": "unexpected Host header"})
            path = urlsplit(self.path).path
            try:
                if path in ("/", "/index.html"):
                    return self._send(200, _ui_html(), "text/html; charset=utf-8")
                if path == "/favicon.ico":
                    return self._send(200, _favicon(), "image/png")
                if path == "/api/steps":
                    return self._json(200, app.get_steps())
                if path.startswith("/api/image/"):
                    sid = path.rsplit("/", 1)[-1]
                    return self._send(200, app.image_bytes(sid), "image/png")
                if path in ("/guide.html", "/checklist.html"):
                    name = GUIDE_HTML if path == "/guide.html" else CHECKLIST_HTML
                    page = app.session / name
                    if not page.exists():
                        raise ApiError(404, f"{name} not built yet - press Build")
                    return self._send(200, page.read_bytes(), "text/html; charset=utf-8")
                raise ApiError(404, "not found")
            except ApiError as exc:
                return self._json(exc.status, {"error": str(exc)})
            except SessionError as exc:
                return self._json(500, {"error": str(exc)})

        do_HEAD = do_GET

        def do_POST(self) -> None:
            if not self._host_ok():
                return self._json(403, {"error": "unexpected Host header"})
            routes = {
                "/api/steps": app.save_steps,
                "/api/blur": app.blur,
                "/api/box": app.set_box,
                "/api/arrows": app.set_arrows,
                "/api/options": app.set_options,
                "/api/reset-image": app.reset_image,
                "/api/build": app.build,
            }
            path = urlsplit(self.path).path
            try:
                if path not in routes:
                    raise ApiError(404, "not found")
                return self._json(200, routes[path](self._read_json()))
            except ApiError as exc:
                return self._json(exc.status, {"error": str(exc)})
            except (SessionError, ValueError, OSError) as exc:
                return self._json(500, {"error": str(exc)})
            except Exception as exc:  # report instead of dropping the connection
                return self._json(500, {"error": f"{type(exc).__name__}: {exc}"})

    return Handler


def allowed_hosts_for(host: str, port: int) -> set[str] | None:
    if host in ("127.0.0.1", "localhost", "::1"):
        return {f"127.0.0.1:{port}", f"localhost:{port}", f"[::1]:{port}"}
    return None  # explicit non-local bind: the user opted out of the Host check


def create_server(session: Path, host: str = "127.0.0.1", port: int = 8765) -> ThreadingHTTPServer:
    app = EditApp(session)
    server = ThreadingHTTPServer((host, port), make_handler(app, None))
    real_port = server.server_address[1]
    server.RequestHandlerClass = make_handler(app, allowed_hosts_for(host, real_port))
    server.daemon_threads = True
    return server


def serve(
    session: Path, host: str = "127.0.0.1", port: int = 8765, open_browser: bool = True
) -> int:
    if host not in ("127.0.0.1", "localhost", "::1"):
        print(
            f"WARNING: binding to {host}. The editor has no authentication: anyone who can "
            "reach this address can see your screenshots and change the guide.",
            file=sys.stderr,
        )
    server = create_server(session, host, port)
    real_port = server.server_address[1]
    shown = "127.0.0.1" if host in ("0.0.0.0", "::") else host
    url = f"http://{shown}:{real_port}/"
    print(f"stepcap edit: {url}  (Ctrl+C to stop)", file=sys.stderr)
    if open_browser:
        threading.Thread(target=webbrowser.open, args=(url,), daemon=True).start()
    try:
        # Ctrl+C is the normal way to stop the editor: exit quietly with status 0.
        with contextlib.suppress(KeyboardInterrupt):
            server.serve_forever()
    finally:
        server.server_close()
    return 0
