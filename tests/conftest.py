from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent / "fixtures"))

from make_events import make_events

from stepcap.capture.events import (
    EventProcessor,
    Monitor,
    ProcessorOptions,
    Shot,
    WindowInfo,
)
from stepcap.simulate import simulate


@pytest.fixture
def spec() -> dict:
    return make_events()


@pytest.fixture
def demo_session(tmp_path, spec) -> Path:
    out = tmp_path / "demo"
    simulate(spec, out)
    return out


class Harness:
    """EventProcessor wired to fake capture/window callbacks."""

    def __init__(self, monitors=None, **opts):
        self.monitors = monitors or [Monitor(1, 0, 0, 1920, 1080)]
        self.window = WindowInfo("Editor - Notes", "notes")
        self.events: list[dict] = []
        self.captures: list[tuple[float, float]] = []
        self.proc = EventProcessor(
            self.capture, lambda: self.window, self.events.append, ProcessorOptions(**opts)
        )

    def capture(self, x, y, ts):
        from stepcap.capture.events import pick_monitor

        self.captures.append((x, y))
        m = pick_monitor(self.monitors, x, y)
        n = len(self.captures)
        return Shot(
            id=f"{n:04d}", path=f"raw/{n:04d}.png", monitor=m, width=m.width, height=m.height
        )

    def click(self, t, x, y, button="left", hold=0.05):
        self.proc.on_mouse(t, x, y, button, True)
        self.proc.on_mouse(t + hold, x, y, button, False)

    def type(self, t, text, dt=0.05):
        for i, ch in enumerate(text):
            self.proc.on_key(t + i * dt, "space" if ch == " " else ch)

    def done(self):
        self.proc.tick(1e9)
        self.proc.flush()
        return self.events


@pytest.fixture
def harness():
    return Harness
