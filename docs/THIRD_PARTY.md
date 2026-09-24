# Third-party software

stepcap is MIT licensed. It depends on the packages below at runtime. None of
them is AGPL. Versions are minimums from `pyproject.toml`.

| Package | Why | License |
|---|---|---|
| [Pillow](https://python-pillow.github.io/) ≥ 10.1 | image annotation, encoding, simulate screens; bundled font (`ImageFont.load_default(size=…)`) | MIT-CMU (HPND) |
| [mss](https://github.com/BoboTiG/python-mss) ≥ 9.0 | fast multi-monitor screenshots | MIT |
| [pynput](https://github.com/moses-palmer/pynput) ≥ 1.7.7 | global mouse / keyboard hooks | **LGPL-3.0** |

### Transitive (installed by pynput, platform dependent)

| Package | Platform | License |
|---|---|---|
| six | all | MIT |
| python-xlib | Linux | LGPL-2.1+ |
| evdev | Linux | BSD-3-Clause |
| pyobjc-framework-Quartz / -ApplicationServices (+ pyobjc-core, -Cocoa) | macOS | MIT |

### LGPL note (pynput, python-xlib)

stepcap uses pynput and python-xlib as unmodified, separately installed Python
packages that are imported at runtime, so users can replace them with any
compatible version (e.g. `pip install pynput==<other>`). The PyInstaller
binaries attached to GitHub Releases bundle them unmodified; their source is
available from PyPI and the upstream repositories linked above, and the
LGPL-3.0 text is included in the binary release notes. If you need a build
without bundled LGPL code, install from PyPI instead.

### Development / optional (not shipped)

| Package | Why | License |
|---|---|---|
| pytest | tests | MIT |
| ruff | lint / format | MIT |
| playwright (extra `demo`) | screenshots of the edit UI for the README | Apache-2.0 |
| PyInstaller (CI only) | single-file binaries | GPL-2.0 with bootloader exception (bundled apps may use any license) |
