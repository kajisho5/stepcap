"""Screen grabbing (mss) and asynchronous saving.

``ScreenGrabber`` must be created and used from a single thread (mss handles
are not thread-safe). Encoding/saving is done by ``ShotWriter`` on its own
thread so a slow disk never delays the next click.
"""

from __future__ import annotations

import queue
import statistics
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image, ImageDraw, ImageStat

from stepcap.capture.events import Monitor, Shot, pick_monitor
from stepcap.session import RAW_DIR


def mss_monitors(sct) -> tuple[Monitor, list[Monitor]]:
    """Return (virtual desktop, physical monitors) from an mss instance."""
    mons = sct.monitors
    virtual = Monitor(0, mons[0]["left"], mons[0]["top"], mons[0]["width"], mons[0]["height"])
    physical = [
        Monitor(i, m["left"], m["top"], m["width"], m["height"]) for i, m in enumerate(mons) if i
    ]
    return virtual, physical or [virtual]


def mask_rects(
    img: Image.Image, mon: Monitor, rects: list[tuple[float, float, float, float]]
) -> Image.Image:
    """Paint over screen rectangles (stepcap's own recording bar) in a screenshot.

    ``rects`` are in screen coordinates like the monitor; the image may have more
    pixels than the monitor has points (Retina), so they are scaled. Each area is
    filled with the average colour of a thin ring around it (what the bar covers is
    usually the same window), so nothing of the bar stays readable and the patch
    blends in; at the screen edge only the sides that exist are used.
    """
    if not rects or not mon.width or not mon.height:
        return img
    sx, sy = img.width / mon.width, img.height / mon.height
    draw = None
    for rx, ry, rw, rh in rects:
        box = (
            max(0, round((rx - mon.left) * sx)),
            max(0, round((ry - mon.top) * sy)),
            min(img.width, round((rx + rw - mon.left) * sx)),
            min(img.height, round((ry + rh - mon.top) * sy)),
        )
        if box[2] <= box[0] or box[3] <= box[1]:
            continue  # the bar is on another monitor
        fill = _ring_colour(img, box, max(2, round(4 * sx)))
        draw = draw or ImageDraw.Draw(img)
        draw.rectangle((box[0], box[1], box[2] - 1, box[3] - 1), fill=fill)
    return img


def _ring_colour(img: Image.Image, box: tuple[int, int, int, int], ring: int) -> tuple:
    x0, y0, x1, y1 = box
    sides = [
        (x0, max(0, y0 - ring), x1, y0),  # above
        (x0, y1, x1, min(img.height, y1 + ring)),  # below
        (max(0, x0 - ring), y0, x0, y1),  # left
        (x1, y0, min(img.width, x1 + ring), y1),  # right
    ]
    total, count = [0.0, 0.0, 0.0], 0
    for side in sides:
        n = (side[2] - side[0]) * (side[3] - side[1])
        if n > 0:
            mean = ImageStat.Stat(img.crop(side)).mean
            total = [t + m * n for t, m in zip(total, mean[:3], strict=False)]
            count += n
    if not count:  # the bar covers the whole image
        return tuple(round(v) for v in ImageStat.Stat(img.crop(box)).mean[:3])
    return tuple(round(t / count) for t in total)


class ScreenGrabber:
    def __init__(self, mode: str = "active") -> None:
        import mss

        if mode not in ("active", "all"):
            raise ValueError("mode must be 'active' or 'all'")
        self.mode = mode
        self._sct = mss.mss()
        self.virtual, self.monitors = mss_monitors(self._sct)

    def grab(self, x: float, y: float) -> tuple[Image.Image, Monitor]:
        mon = self.virtual if self.mode == "all" else pick_monitor(self.monitors, x, y)
        raw = self._sct.grab(mon.to_dict())
        img = Image.frombytes("RGB", raw.size, raw.bgra, "raw", "BGRX")
        return img, mon

    def close(self) -> None:
        self._sct.close()


@dataclass
class LatencyStats:
    grab_ms: list[float] = field(default_factory=list)
    saved_ms: list[float] = field(default_factory=list)

    @staticmethod
    def _summary(values: list[float]) -> dict[str, float] | None:
        if not values:
            return None
        ordered = sorted(values)
        p95 = ordered[min(len(ordered) - 1, round(0.95 * (len(ordered) - 1)))]
        return {
            "p50": round(statistics.median(ordered), 1),
            "p95": round(p95, 1),
            "max": round(ordered[-1], 1),
        }

    def to_dict(self) -> dict[str, object]:
        return {
            "click_to_grab_ms": self._summary(self.grab_ms),
            "click_to_saved_ms": self._summary(self.saved_ms),
        }


class ShotWriter(threading.Thread):
    """Saves screenshots to SESSION_DIR/raw/NNNN.png in the background."""

    def __init__(self, session_dir: Path, stats: LatencyStats | None = None) -> None:
        super().__init__(name="stepcap-writer", daemon=True)
        self.dir = Path(session_dir) / RAW_DIR
        self.dir.mkdir(parents=True, exist_ok=True)
        self.q: queue.Queue = queue.Queue()
        self.stats = stats or LatencyStats()
        self.errors: list[str] = []
        self._n = 0

    def new_shot(self, img: Image.Image, mon: Monitor, event_ts: float) -> Shot:
        self._n += 1
        sid = f"{self._n:04d}"
        shot = Shot(
            id=sid, path=f"{RAW_DIR}/{sid}.png", monitor=mon, width=img.width, height=img.height
        )
        self.stats.grab_ms.append((time.monotonic() - event_ts) * 1000)
        self.q.put((shot, img, event_ts))
        return shot

    def run(self) -> None:
        while True:
            item = self.q.get()
            if item is None:
                return
            shot, img, event_ts = item
            try:
                # Fast, lossless: raw/ keeps originals; build converts to WebP/JPEG.
                img.save(self.dir.parent / shot.path, format="PNG", compress_level=1)
                self.stats.saved_ms.append((time.monotonic() - event_ts) * 1000)
            except Exception as exc:  # pragma: no cover - disk full etc.
                self.errors.append(f"{shot.path}: {exc}")

    def close(self) -> None:
        self.q.put(None)
        self.join()
