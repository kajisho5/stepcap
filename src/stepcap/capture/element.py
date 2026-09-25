"""Name, role and exact rectangle of the UI element under the pointer (best effort).

- macOS:   Accessibility API (AXUIElementCopyElementAtPosition) via pyobjc, which
           pynput already installs. Needs the Accessibility permission that
           recording needs anyway.
- Windows: UI Automation (IUIAutomation::ElementFromPoint) via comtypes.
- Linux:   not supported yet (AT-SPI is not pip-installable) -> None.

Lookups run on one worker thread with a short timeout, so a slow or hung
application never stalls recording, and they never raise. Password fields never
report a name. Rectangles are in the same global coordinates as the input hooks
(macOS points, Windows physical pixels with per-monitor DPI awareness).
"""

from __future__ import annotations

import contextlib
import queue
import re
import sys
import threading
from dataclasses import dataclass
from typing import Any

MAX_NAME = 80
LOOKUP_TIMEOUT_S = 0.25


@dataclass
class ElementInfo:
    name: str | None = None
    role: str | None = None  # button, link, checkbox, radio, tab, menu-item, text-field, ...
    rect: tuple[float, float, float, float] | None = None  # x, y, w, h (global)
    secure: bool = False

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {}
        if self.name and not self.secure:
            d["name"] = self.name
        if self.role:
            d["role"] = "password-field" if self.secure else self.role
        if self.rect:
            d["rect"] = [round(v) for v in self.rect]
        return d


def clean_name(name: Any) -> str | None:
    if not isinstance(name, str):
        return None
    name = re.sub(r"\s+", " ", name).strip()
    if not name:
        return None
    return name if len(name) <= MAX_NAME else name[: MAX_NAME - 1].rstrip() + "…"


# --------------------------------------------------------------------- macOS
_MAC_ROLES = {
    "AXButton": "button",
    "AXMenuButton": "button",
    "AXPopUpButton": "dropdown",
    "AXComboBox": "combo-box",
    "AXCheckBox": "checkbox",
    "AXRadioButton": "radio",
    "AXLink": "link",
    "AXMenuItem": "menu-item",
    "AXMenuBarItem": "menu-item",
    "AXTextField": "text-field",
    "AXTextArea": "text-field",
    "AXSearchField": "text-field",
    "AXTab": "tab",
    "AXRow": "list-item",
    "AXCell": "list-item",
    "AXOutlineRow": "list-item",
    "AXSlider": "slider",
    "AXIncrementor": "stepper",
    "AXDisclosureTriangle": "disclosure",
    "AXStaticText": "text",
    "AXImage": "image",
}
# roles that are usually *inside* the thing the user meant (the label of a button)
_INNER = {"text", "image", None}


def _mac_point(value: Any, kind: str) -> tuple[float, float] | None:
    import HIServices as HI  # pyobjc-framework-ApplicationServices

    const = HI.kAXValueCGPointType if kind == "point" else HI.kAXValueCGSizeType
    with contextlib.suppress(Exception):
        res = HI.AXValueGetValue(value, const, None)
        if isinstance(res, tuple) and len(res) == 2 and res[0]:
            res = res[1]
        if kind == "point" and hasattr(res, "x"):
            return float(res.x), float(res.y)
        if kind == "size" and hasattr(res, "width"):
            return float(res.width), float(res.height)
    # fallback: "<AXValue ... {value = x:10.000000 y:20.000000 type = kAXValueCGPointType}>"
    keys = ("x", "y") if kind == "point" else ("w", "h")
    m = re.search(rf"{keys[0]}:(-?[\d.]+)\s+{keys[1]}:(-?[\d.]+)", str(value))
    return (float(m.group(1)), float(m.group(2))) if m else None


def _mac_lookup(x: float, y: float, focused: bool) -> ElementInfo | None:
    import HIServices as HI

    system = HI.AXUIElementCreateSystemWide()
    HI.AXUIElementSetMessagingTimeout(system, LOOKUP_TIMEOUT_S)

    def attr(el: Any, name: str) -> Any:
        err, value = HI.AXUIElementCopyAttributeValue(el, name, None)
        return value if err == 0 else None

    if focused:
        el = attr(system, "AXFocusedUIElement")
    else:
        err, el = HI.AXUIElementCopyElementAtPosition(system, float(x), float(y), None)
        if err != 0:
            el = None
    if el is None:
        return None

    def describe(el: Any) -> ElementInfo:
        raw_role = attr(el, "AXRole")
        subrole = attr(el, "AXSubrole")
        role = _MAC_ROLES.get(str(raw_role)) if raw_role else None
        if subrole == "AXTabButton":
            role = "tab"
        secure = subrole == "AXSecureTextField"
        name = None
        for key in ("AXTitle", "AXDescription", "AXPlaceholderValue", "AXHelp"):
            name = clean_name(attr(el, key))
            if name:
                break
        if name is None and role in ("text", None):
            name = clean_name(attr(el, "AXValue")) if not secure else None
        if name is None:
            label = attr(el, "AXTitleUIElement")
            if label is not None:
                name = clean_name(attr(label, "AXValue")) or clean_name(attr(label, "AXTitle"))
        rect = None
        pos, size = attr(el, "AXPosition"), attr(el, "AXSize")
        if pos is not None and size is not None:
            p, s = _mac_point(pos, "point"), _mac_point(size, "size")
            if p and s and s[0] > 0 and s[1] > 0:
                rect = (p[0], p[1], s[0], s[1])
        return ElementInfo(name=name, role=role, rect=rect, secure=secure)

    info = describe(el)
    parent = el
    for _ in range(2):  # the label inside a button -> the button
        if info.role not in _INNER:
            break
        parent = attr(parent, "AXParent")
        if parent is None:
            break
        up = describe(parent)
        if up.role in _INNER or up.role is None:
            continue
        info = ElementInfo(
            name=up.name or info.name, role=up.role, rect=up.rect or info.rect, secure=up.secure
        )
    return info


# --------------------------------------------------------------------- Windows
_UIA_ROLES = {
    50000: "button",
    50002: "checkbox",
    50003: "combo-box",
    50004: "text-field",
    50005: "link",
    50006: "image",
    50007: "list-item",
    50011: "menu-item",
    50013: "radio",
    50015: "slider",
    50019: "tab",
    50020: "text",
    50024: "list-item",  # tree item
    50029: "list-item",  # data item
    50031: "button",  # split button
    50035: "header",
}
_uia_local = threading.local()  # COM objects belong to the thread (apartment) that made them
UIA_TIMEOUT_MS = 500  # a hung application must not stall the caller for long


def _uia_client() -> Any:
    """(UIAutomationClient module, IUIAutomation) for the calling thread."""
    client = getattr(_uia_local, "client", None)
    if client is None:
        import comtypes
        import comtypes.client

        with contextlib.suppress(OSError):
            comtypes.CoInitializeEx(comtypes.COINIT_APARTMENTTHREADED)
        comtypes.client.GetModule("UIAutomationCore.dll")
        from comtypes.gen import UIAutomationClient as UIA

        uia = comtypes.client.CreateObject(UIA.CUIAutomation, interface=UIA.IUIAutomation)
        with contextlib.suppress(Exception):  # IUIAutomation2: Windows 8+
            uia2 = uia.QueryInterface(UIA.IUIAutomation2)
            uia2.ConnectionTimeout = UIA_TIMEOUT_MS
            uia2.TransactionTimeout = UIA_TIMEOUT_MS
        client = _uia_local.client = (UIA, uia)
    return client


def _win_lookup(x: float, y: float, focused: bool) -> ElementInfo | None:
    UIA, uia = _uia_client()
    el = uia.GetFocusedElement() if focused else uia.ElementFromPoint(UIA.tagPOINT(int(x), int(y)))
    if el is None:
        return None

    def describe(el: Any) -> ElementInfo:
        role = _UIA_ROLES.get(int(el.CurrentControlType))
        secure = bool(el.CurrentIsPassword)
        name = None if secure else clean_name(el.CurrentName)
        r = el.CurrentBoundingRectangle
        rect = None
        if r.right > r.left and r.bottom > r.top:
            rect = (float(r.left), float(r.top), float(r.right - r.left), float(r.bottom - r.top))
        return ElementInfo(name=name, role=role, rect=rect, secure=secure)

    info = describe(el)
    if info.role in _INNER:
        walker = uia.ControlViewWalker
        parent = el
        for _ in range(2):
            parent = walker.GetParentElement(parent)
            if parent is None:
                break
            up = describe(parent)
            if up.role not in _INNER:
                info = ElementInfo(up.name or info.name, up.role, up.rect or info.rect, up.secure)
                break
    return info


# --------------------------------------------------------------------- public
def backend() -> str | None:
    if sys.platform == "darwin":
        return "macos-ax"
    if sys.platform == "win32":
        try:
            import comtypes.client  # noqa: F401
        except ImportError:
            return None
        return "windows-uia"
    return None


def lookup_now(x: float, y: float, focused: bool = False) -> ElementInfo | None:
    """Synchronous lookup on the calling thread; never raises."""
    try:
        if sys.platform == "darwin":
            return _mac_lookup(x, y, focused)
        if sys.platform == "win32":
            return _win_lookup(x, y, focused)
    except Exception:
        return None
    return None


class ElementLookup:
    """Serialises lookups on one worker thread and gives up after ``timeout``.

    While a lookup is still running (an application not answering), new
    requests return None at once instead of piling up.
    """

    def __init__(self, timeout: float = LOOKUP_TIMEOUT_S, fn=lookup_now) -> None:
        self.timeout = timeout
        self.fn = fn
        self._req: queue.Queue = queue.Queue()
        self._busy = threading.Event()
        self._seq = 0
        self._results: dict[int, ElementInfo | None] = {}
        self._done = threading.Condition()
        self.enabled = backend() is not None or fn is not lookup_now
        if self.enabled:
            threading.Thread(target=self._worker, name="stepcap-element", daemon=True).start()

    def _worker(self) -> None:
        while True:
            seq, x, y, focused = self._req.get()
            self._busy.set()
            try:
                res = self.fn(x, y, focused)
            except Exception:
                res = None
            finally:
                self._busy.clear()
            with self._done:
                self._results[seq] = res
                self._done.notify_all()

    def __call__(self, x: float, y: float, focused: bool = False) -> ElementInfo | None:
        if not self.enabled or self._busy.is_set():
            return None
        with self._done:
            self._seq += 1
            seq = self._seq
            self._results.clear()
        self._req.put((seq, x, y, focused))
        with self._done:
            self._done.wait_for(lambda: seq in self._results, timeout=self.timeout)
            return self._results.pop(seq, None)
