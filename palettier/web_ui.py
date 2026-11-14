"""
palettier.web_ui — Zero-dependency local Material Design 3 Web Settings UI.

Used as a clean fallback when GTK 4 / Libadwaita is unavailable, or directly
via `palettier --web-ui`. Binds strictly to 127.0.0.1 on an ephemeral port.
"""

from __future__ import annotations

import html
import json
import os
import threading
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from palettier import __version__
from palettier.config import (
    TARGET_KEYS,
    PalettierConfig,
    get_config_path,
    load_config,
    reset_config,
    save_config,
)
from palettier.icons import VALID_ICON_MODES, render_html_preview
from palettier.palette import build_m3_scheme
from palettier.service import get_service_status, set_service_enabled, uninstall_all
from palettier.sync import update_theme
from palettier.wallpaper import extract_wallpaper_colors, get_current_wallpaper_path, gsettings_get


def build_state_payload(config_path: Path | None = None) -> dict[str, Any]:
    """Collect current config, wallpaper info, M3 scheme, and service status."""
    cfg = load_config(config_path=config_path)
    wp = get_current_wallpaper_path()
    if cfg.accent_override:
        accent = cfg.accent_override
        tint = cfg.surface_tint if cfg.surface_tint is not None else 0.10
    else:
        accent, tint, wp = extract_wallpaper_colors(wp, forced_tint=cfg.surface_tint)

    color_scheme = gsettings_get("org.gnome.desktop.interface", "color-scheme")
    is_dark = "dark" in (color_scheme or "prefer-dark").lower()
    scheme = build_m3_scheme(accent, is_dark=is_dark)

    return {
        "version": __version__,
        "config_path": str(config_path or get_config_path()),
        "config": cfg.to_dict(),
        "wallpaper": str(wp) if wp else None,
        "wallpaper_name": wp.name if wp else "None detected",
        "accent": accent,
        "surface_tint": tint,
        "scheme": scheme,
        "service": get_service_status(),
    }


def render_web_ui_html(state: dict[str, Any]) -> str:
    """Render the self-contained Material Design 3 Web Settings page."""
    scheme = state["scheme"]
    state_json = json.dumps(state, ensure_ascii=False)
    wp_name = html.escape(str(state.get("wallpaper_name") or "None detected"))
    cfg_path = html.escape(str(state.get("config_path") or ""))

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Palettier Settings</title>
<style>
  :root {{
    --bg: {scheme["surface"]};
    --card: {scheme["surfaceContainer"]};
    --card-hi: {scheme["surfaceContainerHigh"]};
    --text: {scheme["onSurface"]};
    --muted: {scheme["onSurfaceVariant"]};
    --primary: {scheme["primary"]};
    --on-primary: {scheme["onPrimary"]};
    --primary-cont: {scheme["primaryContainer"]};
    --on-primary-cont: {scheme["onPrimaryContainer"]};
    --border: {scheme["outlineVariant"]};
    --error: {scheme["error"]};
  }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0;
    padding: 28px 18px 64px;
    font-family: Inter, "Cantarell", system-ui, -apple-system, sans-serif;
    background: var(--bg);
    color: var(--text);
    line-height: 1.5;
  }}
  .container {{ max-width: 780px; margin: 0 auto; }}
  header {{
    display: flex; flex-wrap: wrap; justify-content: space-between;
    align-items: center; gap: 16px; margin-bottom: 24px;
  }}
  .title-wrap h1 {{ margin: 0; font-size: 1.75rem; letter-spacing: -0.02em; }}
  .title-wrap p {{ margin: 4px 0 0; color: var(--muted); font-size: 0.92rem; }}
  .pill {{
    display: inline-flex; align-items: center; gap: 8px;
    padding: 6px 14px; border-radius: 999px;
    background: var(--primary-cont); color: var(--on-primary-cont);
    font-size: 0.85rem; font-weight: 600;
  }}
  .card {{
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 20px;
    padding: 20px 22px;
    margin-bottom: 18px;
  }}
  .card h2 {{
    margin: 0 0 14px;
    font-size: 1.05rem;
    font-weight: 650;
  }}
  .swatches {{
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(120px, 1fr));
    gap: 10px;
    margin-top: 12px;
  }}
  .swatch {{
    display: flex; align-items: center; gap: 10px;
    background: var(--card-hi);
    border: 1px solid var(--border);
    border-radius: 14px;
    padding: 8px 10px;
    font-size: 0.8rem;
  }}
  .dot {{
    width: 24px; height: 24px; border-radius: 50%; flex-shrink: 0;
    border: 1px solid var(--border);
  }}
  .row {{
    display: flex; justify-content: space-between; align-items: center;
    gap: 16px; padding: 12px 0;
    border-top: 1px solid var(--border);
  }}
  .row:first-of-type {{ border-top: none; padding-top: 4px; }}
  .row-label strong {{ display: block; font-size: 0.96rem; }}
  .row-label span {{ color: var(--muted); font-size: 0.84rem; }}
  select, input[type="text"], input[type="color"] {{
    background: var(--card-hi);
    color: var(--text);
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 7px 12px;
    font-size: 0.9rem;
  }}
  input[type="range"] {{ width: 170px; accent-color: var(--primary); }}
  input[type="checkbox"] {{
    width: 20px; height: 20px; accent-color: var(--primary); cursor: pointer;
  }}
  .actions {{
    display: flex; flex-wrap: wrap; gap: 10px; margin-top: 18px;
  }}
  button {{
    border: none; border-radius: 999px; padding: 10px 18px;
    font-size: 0.92rem; font-weight: 600; cursor: pointer;
    transition: opacity 0.15s ease;
  }}
  button:hover {{ opacity: 0.9; }}
  .btn-primary {{ background: var(--primary); color: var(--on-primary); }}
  .btn-secondary {{
    background: var(--card-hi); color: var(--text);
    border: 1px solid var(--border);
  }}
  .btn-danger {{
    background: transparent; color: var(--error);
    border: 1px solid var(--error);
  }}
  #toast {{
    position: fixed; bottom: 20px; right: 20px;
    background: var(--card-hi); color: var(--text);
    border: 1px solid var(--primary);
    padding: 10px 16px; border-radius: 12px;
    font-size: 0.9rem; display: none;
    box-shadow: 0 8px 24px rgba(0, 0, 0, 0.25);
  }}
  code {{ font-family: ui-monospace, SFMono-Regular, monospace; font-size: 0.85em; }}
</style>
</head>
<body>
<div class="container">
  <header>
    <div class="title-wrap">
      <h1>Palettier Settings</h1>
      <p>Wallpaper: <code>{wp_name}</code> · Config: <code>{cfg_path}</code></p>
    </div>
    <div class="pill">v{html.escape(__version__)} · <span id="accent-badge">{html.escape(state["accent"])}</span></div>
  </header>

  <section class="card">
    <h2>Active Material Design 3 Palette</h2>
    <div class="swatches" id="swatches"></div>
  </section>

  <section class="card">
    <h2>Color &amp; Extraction</h2>
    <div class="row">
      <div class="row-label">
        <strong>Automatic Accent from Wallpaper</strong>
        <span>Disable to pick a fixed custom #HEX accent color</span>
      </div>
      <input type="checkbox" id="auto-accent">
    </div>
    <div class="row" id="custom-accent-row">
      <div class="row-label">
        <strong>Custom Accent Color</strong>
        <span>Hexadecimal seed color for Material Design 3</span>
      </div>
      <div style="display:flex;gap:8px;align-items:center;">
        <input type="color" id="accent-picker">
        <input type="text" id="accent-hex" style="width:96px" placeholder="#3584e4">
      </div>
    </div>
    <div class="row">
      <div class="row-label">
        <strong>Surface Tint Intensity</strong>
        <span>Tint applied to terminal and browser surfaces (<span id="surface-tint-val">auto</span>)</span>
      </div>
      <div style="display:flex;gap:10px;align-items:center;">
        <label style="font-size:0.84rem;color:var(--muted)"><input type="checkbox" id="auto-surface-tint"> Auto</label>
        <input type="range" id="surface-tint" min="0" max="0.30" step="0.01">
      </div>
    </div>
  </section>

  <section class="card">
    <h2>Material Design 3 Icon Pack</h2>
    <div class="row">
      <div class="row-label">
        <strong>Icon Generation Mode</strong>
        <span><code>system</code> tints all installed app icons while keeping original shapes</span>
      </div>
      <select id="icon-mode">
        <option value="system">system (M3 places + tinted apps)</option>
        <option value="places">places (folders &amp; mimetypes only)</option>
        <option value="squircle">squircle (uniform Material You squircles)</option>
        <option value="off">off (disabled)</option>
      </select>
    </div>
    <div class="row">
      <div class="row-label">
        <strong>App Icon Tonal Filter Strength</strong>
        <span>Blend strength for installed application icons (<span id="icon-tint-val">90%</span>)</span>
      </div>
      <input type="range" id="icon-tint" min="0" max="1" step="0.05">
    </div>
  </section>

  <section class="card">
    <h2>Desktop Integrations</h2>
    <div class="row">
      <div class="row-label"><strong>Material 3 Icon Theme</strong><span>GNOME Shell, Nautilus &amp; AppImages</span></div>
      <input type="checkbox" id="t-icons">
    </div>
    <div class="row">
      <div class="row-label"><strong>GNOME 47+ Native Accent</strong><span>org.gnome.desktop.interface accent-color</span></div>
      <input type="checkbox" id="t-gnome_accent">
    </div>
    <div class="row">
      <div class="row-label"><strong>Ptyxis Terminal</strong><span>Dynamic palettier.palette theme</span></div>
      <input type="checkbox" id="t-ptyxis">
    </div>
    <div class="row">
      <div class="row-label"><strong>Starship Prompt</strong><span>~/.config/starship.toml palette</span></div>
      <input type="checkbox" id="t-starship">
    </div>
    <div class="row">
      <div class="row-label"><strong>Firefox Browser</strong><span>userChrome.css (horizontal &amp; vertical tabs)</span></div>
      <input type="checkbox" id="t-firefox">
    </div>
  </section>

  <section class="card">
    <h2>Background Service &amp; Actions</h2>
    <div class="row">
      <div class="row-label">
        <strong>Auto-Sync Daemon (<code>palettier.service</code>)</strong>
        <span id="service-desc">Checking systemd user service...</span>
      </div>
      <input type="checkbox" id="service-enabled">
    </div>
    <div class="actions">
      <button class="btn-primary" id="btn-apply">Save &amp; Apply Theme</button>
      <button class="btn-secondary" id="btn-preview">Open Icon Preview</button>
      <button class="btn-secondary" id="btn-reset">Reset Defaults</button>
      <button class="btn-danger" id="btn-uninstall">Uninstall Palettier</button>
    </div>
  </section>
</div>
<div id="toast"></div>

<script>
const INITIAL_STATE = {state_json};

function showToast(msg) {{
  const el = document.getElementById('toast');
  el.textContent = msg;
  el.style.display = 'block';
  clearTimeout(window._toastTimer);
  window._toastTimer = setTimeout(() => {{ el.style.display = 'none'; }}, 3200);
}}

function renderState(st) {{
  const cfg = st.config;
  const swEl = document.getElementById('swatches');
  const keys = ['primary', 'primaryContainer', 'secondary', 'tertiary', 'surfaceContainerHigh', 'onSurface'];
  swEl.innerHTML = keys.map(k => `
    <div class="swatch">
      <div class="dot" style="background:${{st.scheme[k]}}"></div>
      <div><b>${{k}}</b><br><code>${{st.scheme[k]}}</code></div>
    </div>
  `).join('');

  document.getElementById('accent-badge').textContent = st.accent;
  const autoAccent = !cfg.accent_override;
  document.getElementById('auto-accent').checked = autoAccent;
  document.getElementById('custom-accent-row').style.opacity = autoAccent ? '0.5' : '1';
  const curColor = cfg.accent_override || st.accent || '#3584e4';
  document.getElementById('accent-picker').value = curColor;
  document.getElementById('accent-hex').value = curColor;

  const autoSurf = cfg.surface_tint === null || cfg.surface_tint === undefined;
  document.getElementById('auto-surface-tint').checked = autoSurf;
  const surfVal = autoSurf ? (st.surface_tint || 0.10) : cfg.surface_tint;
  document.getElementById('surface-tint').disabled = autoSurf;
  document.getElementById('surface-tint').value = surfVal;
  document.getElementById('surface-tint-val').textContent = autoSurf ? 'auto' : Math.round(surfVal * 100) + '%';

  document.getElementById('icon-mode').value = cfg.icon_mode === 'full' ? 'system' : cfg.icon_mode;
  document.getElementById('icon-tint').value = cfg.icon_tint;
  document.getElementById('icon-tint-val').textContent = Math.round(cfg.icon_tint * 100) + '%';

  for (const k of ['icons', 'gnome_accent', 'ptyxis', 'starship', 'firefox']) {{
    document.getElementById('t-' + k).checked = !!cfg.targets[k];
  }}

  const svc = st.service || {{}};
  document.getElementById('service-enabled').checked = !!svc.enabled;
  document.getElementById('service-desc').textContent = svc.active
    ? 'Running in background (active & watching)'
    : (svc.enabled ? 'Enabled at login (inactive)' : 'Disabled');
}}

function collectConfig() {{
  const autoAccent = document.getElementById('auto-accent').checked;
  const autoSurf = document.getElementById('auto-surface-tint').checked;
  return {{
    icon_mode: document.getElementById('icon-mode').value,
    icon_tint: parseFloat(document.getElementById('icon-tint').value),
    surface_tint: autoSurf ? null : parseFloat(document.getElementById('surface-tint').value),
    accent_override: autoAccent ? null : document.getElementById('accent-hex').value.trim(),
    targets: {{
      icons: document.getElementById('t-icons').checked,
      gnome_accent: document.getElementById('t-gnome_accent').checked,
      ptyxis: document.getElementById('t-ptyxis').checked,
      starship: document.getElementById('t-starship').checked,
      firefox: document.getElementById('t-firefox').checked,
    }},
  }};
}}

async function postJson(url, body) {{
  const res = await fetch(url, {{
    method: 'POST',
    headers: {{ 'Content-Type': 'application/json' }},
    body: JSON.stringify(body || {{}}),
  }});
  return await res.json();
}}

document.getElementById('accent-picker').addEventListener('input', e => {{
  document.getElementById('accent-hex').value = e.target.value;
  document.getElementById('auto-accent').checked = false;
  document.getElementById('custom-accent-row').style.opacity = '1';
}});
document.getElementById('auto-accent').addEventListener('change', e => {{
  document.getElementById('custom-accent-row').style.opacity = e.target.checked ? '0.5' : '1';
}});
document.getElementById('auto-surface-tint').addEventListener('change', e => {{
  const el = document.getElementById('surface-tint');
  el.disabled = e.target.checked;
  document.getElementById('surface-tint-val').textContent = e.target.checked ? 'auto' : Math.round(el.value * 100) + '%';
}});
document.getElementById('surface-tint').addEventListener('input', e => {{
  document.getElementById('surface-tint-val').textContent = Math.round(e.target.value * 100) + '%';
}});
document.getElementById('icon-tint').addEventListener('input', e => {{
  document.getElementById('icon-tint-val').textContent = Math.round(e.target.value * 100) + '%';
}});

document.getElementById('btn-apply').addEventListener('click', async () => {{
  const data = await postJson('/api/apply', collectConfig());
  renderState(data.state);
  showToast(data.applied ? 'Settings saved and theme applied!' : 'Settings saved (state already up to date).');
}});

document.getElementById('btn-preview').addEventListener('click', () => {{
  window.open('/preview', '_blank');
}});

document.getElementById('btn-reset').addEventListener('click', async () => {{
  const data = await postJson('/api/reset', {{}});
  renderState(data.state);
  showToast('Defaults restored.');
}});

document.getElementById('service-enabled').addEventListener('change', async e => {{
  const data = await postJson('/api/service', {{ enabled: e.target.checked }});
  renderState(data.state);
  showToast(e.target.checked ? 'Background service enabled.' : 'Background service stopped.');
}});

document.getElementById('btn-uninstall').addEventListener('click', async () => {{
  if (!confirm('Stop service, remove generated themes/icons, and restore app defaults?')) return;
  await postJson('/api/uninstall', {{}});
  showToast('Palettier themes uninstalled and defaults restored.');
}});

renderState(INITIAL_STATE);
</script>
</body>
</html>
"""


def create_web_ui_server(
    host: str = "127.0.0.1",
    port: int = 0,
    config_path: Path | None = None,
) -> ThreadingHTTPServer:
    """Create the local ThreadingHTTPServer for the Palettier Web UI."""

    class _Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: object) -> None:
            return

        def _send_json(self, payload: dict[str, Any], status: HTTPStatus = HTTPStatus.OK) -> None:
            raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def _send_html(self, body: str, status: HTTPStatus = HTTPStatus.OK) -> None:
            raw = body.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def _read_json_body(self) -> dict[str, Any]:
            length = int(self.headers.get("Content-Length", "0") or 0)
            if length <= 0:
                return {}
            raw = self.rfile.read(length)
            try:
                parsed = json.loads(raw.decode("utf-8"))
                return parsed if isinstance(parsed, dict) else {}
            except Exception:
                return {}

        def do_GET(self) -> None:
            if self.path == "/" or self.path.startswith("/?"):
                st = build_state_payload(config_path=config_path)
                self._send_html(render_web_ui_html(st))
            elif self.path == "/api/state":
                self._send_json(build_state_payload(config_path=config_path))
            elif self.path == "/preview":
                st = build_state_payload(config_path=config_path)
                cfg = PalettierConfig.from_dict(st["config"])
                mode = cfg.icon_mode if cfg.targets.get("icons", True) else "off"
                html_doc = render_html_preview(
                    st["scheme"],
                    mode="system" if mode == "off" else mode,
                    tint_strength=cfg.icon_tint,
                )
                self._send_html(html_doc)
            else:
                self._send_json({"error": "Not found"}, status=HTTPStatus.NOT_FOUND)

        def do_POST(self) -> None:
            if self.path == "/api/config":
                body = self._read_json_body()
                cfg = PalettierConfig.from_dict(body)
                save_config(cfg, config_path=config_path)
                self._send_json({"ok": True, "state": build_state_payload(config_path=config_path)})
            elif self.path == "/api/apply":
                body = self._read_json_body()
                cfg = PalettierConfig.from_dict(body)
                save_config(cfg, config_path=config_path)
                applied = update_theme(force=True, config=cfg)
                self._send_json(
                    {"ok": True, "applied": applied, "state": build_state_payload(config_path=config_path)}
                )
            elif self.path == "/api/service":
                body = self._read_json_body()
                ok = set_service_enabled(bool(body.get("enabled", False)))
                self._send_json({"ok": ok, "state": build_state_payload(config_path=config_path)})
            elif self.path == "/api/reset":
                reset_config(config_path=config_path)
                self._send_json({"ok": True, "state": build_state_payload(config_path=config_path)})
            elif self.path == "/api/uninstall":
                uninstall_all()
                self._send_json({"ok": True, "state": build_state_payload(config_path=config_path)})
            elif self.path == "/api/shutdown":
                self._send_json({"ok": True})
                threading.Thread(target=self.server.shutdown, daemon=True).start()
            else:
                self._send_json({"error": "Not found"}, status=HTTPStatus.NOT_FOUND)

    return ThreadingHTTPServer((host, port), _Handler)


def launch_web_ui(
    port: int = 0,
    open_browser: bool = True,
    config_path: Path | None = None,
) -> None:
    """Launch the local Palettier Web Settings UI until interrupted."""
    server = create_web_ui_server(port=port, config_path=config_path)
    actual_port = server.server_address[1]
    url = f"http://127.0.0.1:{actual_port}/"
    print(f"[*] Palettier Settings Web UI running at: {url}")
    print("[*] Press Ctrl+C to stop.")
    if open_browser and (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
        threading.Timer(0.25, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[*] Web UI stopped.")
    finally:
        server.server_close()
