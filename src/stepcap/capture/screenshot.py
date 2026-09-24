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

from PIL import Image

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
