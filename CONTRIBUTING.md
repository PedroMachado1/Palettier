# Contributing to Palettier

Thank you for your interest in contributing to **Palettier**!

## Setting Up a Development Environment

1. Clone the repository:
   ```bash
   git clone https://github.com/PedroMachado1/Palettier.git
   cd Palettier
   ```

2. Create a virtual environment (with `--system-site-packages` if you want to test the native GTK 4 / Libadwaita UI using your distro's `python3-gi` packages):
   ```bash
   python3 -m venv --system-site-packages .venv
   source .venv/bin/activate
   pip install -e .
   ```

3. Run the automated test suite:
   ```bash
   python3 -m unittest discover -s tests -v
   ```

4. Validate shell scripts:
   ```bash
   bash -n install.sh uninstall.sh
   ```

## Project Architecture

- `palettier/palette.py` — Pure-Python CAM16 / HCT Material Design 3 engine and tint LUTs.
- `palettier/wallpaper.py` — Wallpaper detection and quantization color extraction.
- `palettier/config.py` — Persistent XDG JSON configuration (`~/.config/palettier/config.json`).
- `palettier/targets.py` — Starship, Ptyxis, Firefox, and GNOME accent-color updaters.
- `palettier/icons.py` — Material Design 3 icon generator, app icon tonal filter, AppImage `.desktop` bridge, and A/B slot switcher.
- `palettier/sync.py` — Idempotent orchestration respecting config, env vars, and CLI flags.
- `palettier/watch.py` — Real-time GSettings, `Gio.FileMonitor`, and D-Bus power/unlock watcher.
- `palettier/gui.py` & `palettier/web_ui.py` — Native GTK 4 / Libadwaita settings UI with local HTTP Web UI fallback.
- `palettier/service.py` — Systemd user service management and clean uninstallation.
- `palettier/cli.py` — CLI entry point (`palettier`).

## Pull Request Guidelines

- Keep changes focused and add or update unit tests in `tests/` when changing behavior.
- Ensure all target updaters and tests avoid writing outside temporary directories or XDG paths (`XDG_CONFIG_HOME`, `XDG_DATA_HOME`, `XDG_STATE_HOME`, `XDG_RUNTIME_DIR`).
- Confirm `python3 -m unittest discover -s tests -v` passes before submitting your PR.
