"""Tests for persistent XDG config, target toggles, Web UI API, GUI fallback, and CLI flags."""

from __future__ import annotations

import contextlib
import io
import json
import os
import tempfile
import threading
import unittest
import urllib.request
from pathlib import Path
from unittest import mock

from PIL import Image

from palettier.cli import main as cli_main
from palettier.config import (
    TARGET_KEYS,
    PalettierConfig,
    get_config_path,
    load_config,
    normalize_hex_color,
    reset_config,
    save_config,
)
from palettier.gui import main as gui_main
from palettier.state import is_state_unchanged
from palettier.sync import update_theme
from palettier.targets import get_firefox_reference_path, update_firefox_theme
from palettier.web_ui import create_web_ui_server


class TestConfigAndSync(unittest.TestCase):
    def test_config_validation_normalization_and_roundtrip(self):
        self.assertEqual(normalize_hex_color("ABC"), "#aabbcc")
        self.assertEqual(normalize_hex_color(" #3584E4 "), "#3584e4")
        self.assertIsNone(normalize_hex_color("not-a-color"))

        cfg = PalettierConfig(
            icon_mode="INVALID",
            icon_tint=5.0,
            surface_tint=-1.0,
            accent_override="7aa2f7",
            targets={"starship": False, "unknown": False},
        )
        self.assertEqual(cfg.icon_mode, "system")
        self.assertEqual(cfg.icon_tint, 1.0)
        self.assertEqual(cfg.surface_tint, 0.0)
        self.assertEqual(cfg.accent_override, "#7aa2f7")
        self.assertFalse(cfg.targets["starship"])
        self.assertTrue(cfg.targets["firefox"])
        self.assertEqual(set(cfg.targets.keys()), set(TARGET_KEYS))

        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": tmp}):
                path = get_config_path()
                self.assertEqual(path, Path(tmp) / "palettier" / "config.json")
                save_config(cfg)
                loaded = load_config()
                self.assertEqual(loaded.to_dict(), cfg.to_dict())

                # Invalid JSON should safely recover to defaults
                path.write_text("{broken json", encoding="utf-8")
                recovered = load_config()
                self.assertEqual(recovered.icon_mode, "system")
                self.assertIsNone(recovered.accent_override)

                reset = reset_config()
                self.assertEqual(reset.icon_mode, "system")
                self.assertTrue(all(reset.targets.values()))

    def test_config_fingerprint_invalidates_cached_state(self):
        cfg_a = PalettierConfig(icon_tint=0.90)
        cfg_b = PalettierConfig(icon_tint=0.45)
        self.assertNotEqual(cfg_a.fingerprint(), cfg_b.fingerprint())

        current = {
            "wallpaper_sha256": "abc123",
            "color_scheme": "prefer-dark",
            "picture_uri": "file:///wall.png",
            "picture_uri_dark": "file:///wall.png",
            "icon_mode": "system",
        }
        saved = {**current, "accent_color": "#3584e4", "config_fingerprint": cfg_a.fingerprint()}
        self.assertTrue(
            is_state_unchanged(current, saved, icon_mode="system", config_fingerprint=cfg_a.fingerprint())
        )
        self.assertFalse(
            is_state_unchanged(current, saved, icon_mode="system", config_fingerprint=cfg_b.fingerprint())
        )

    def test_firefox_reference_css_writes_to_xdg_state_home(self):
        with tempfile.TemporaryDirectory() as tmp:
            pdir = Path(tmp) / "profile"
            pdir.mkdir()
            with mock.patch.dict(os.environ, {"XDG_STATE_HOME": tmp}):
                ref = get_firefox_reference_path()
                self.assertEqual(ref, Path(tmp) / "palettier" / "firefox-userChrome.css")
                self.assertTrue(update_firefox_theme("#3584e4", 0.10, profile_dirs=[pdir]))
                self.assertTrue(ref.is_file())
                self.assertIn("Palettier", ref.read_text(encoding="utf-8"))

    def test_update_theme_respects_targets_and_precedence(self):
        with tempfile.TemporaryDirectory() as tmp:
            img = Path(tmp) / "wall.png"
            Image.new("RGB", (32, 32), (40, 110, 220)).save(img)

            cfg = PalettierConfig(
                icon_mode="places",
                icon_tint=0.55,
                surface_tint=0.14,
                accent_override="#2ec27e",
                targets={
                    "icons": False,
                    "gnome_accent": False,
                    "ptyxis": True,
                    "starship": False,
                    "firefox": True,
                },
            )

            with mock.patch("palettier.sync.wait_for_package_transaction", return_value=True), \
                 mock.patch("palettier.sync.collect_current_state", return_value={"color_scheme": "prefer-dark"}), \
                 mock.patch("palettier.sync.update_starship_theme") as m_star, \
                 mock.patch("palettier.sync.update_ptyxis_theme", return_value=True) as m_ptyx, \
                 mock.patch("palettier.sync.update_firefox_theme", return_value=True) as m_ff, \
                 mock.patch("palettier.sync.sync_gnome_accent_color") as m_acc, \
                 mock.patch("palettier.sync.sync_m3_icon_pack", return_value=(False, {"primary": "#2ec27e"}, None)) as m_icons, \
                 mock.patch("builtins.print"):
                updated = update_theme(wallpaper_path=img, config=cfg)

            self.assertTrue(updated)
            m_star.assert_not_called()
            m_acc.assert_not_called()
            m_ptyx.assert_called_once_with("#2ec27e", 0.14)
            m_ff.assert_called_once_with("#2ec27e", 0.14)
            # targets.icons=False forces icon mode 'off'
            self.assertEqual(m_icons.call_args.kwargs["mode"], "off")
            self.assertEqual(m_icons.call_args.kwargs["tint_strength"], 0.55)

            # CLI overrides must win over env and config.json
            with mock.patch.dict(os.environ, {"PALETTIER_ICON_MODE": "places", "PALETTIER_ICON_TINT": "0.25"}), \
                 mock.patch("palettier.sync.wait_for_package_transaction", return_value=True), \
                 mock.patch("palettier.sync.collect_current_state", return_value={"color_scheme": "prefer-dark"}), \
                 mock.patch("palettier.sync.update_starship_theme", return_value=True), \
                 mock.patch("palettier.sync.update_ptyxis_theme", return_value=True), \
                 mock.patch("palettier.sync.update_firefox_theme", return_value=True), \
                 mock.patch("palettier.sync.sync_gnome_accent_color", return_value=True), \
                 mock.patch("palettier.sync.sync_m3_icon_pack", return_value=(True, {"primary": "#e01b24"}, "Palettier-M3-A")) as m_icons2, \
                 mock.patch("builtins.print"):
                update_theme(
                    wallpaper_path=img,
                    custom_accent="#e01b24",
                    icon_mode="squircle",
                    icon_tint=0.80,
                    config=PalettierConfig(icon_mode="system", icon_tint=0.90),
                )
            self.assertEqual(m_icons2.call_args.kwargs["mode"], "squircle")
            self.assertEqual(m_icons2.call_args.kwargs["tint_strength"], 0.80)


class TestWebUIAndCLI(unittest.TestCase):
    def _request(self, url: str, method: str = "GET", payload: dict | None = None) -> tuple[int, str]:
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        headers = {"Content-Type": "application/json"} if data is not None else {}
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, resp.read().decode("utf-8")

    def test_web_ui_http_endpoints(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            wp = root / "wall.png"
            Image.new("RGB", (32, 32), (80, 150, 220)).save(wp)
            cfg_path = root / "config.json"

            with mock.patch("palettier.web_ui.get_current_wallpaper_path", return_value=wp), \
                 mock.patch("palettier.web_ui.gsettings_get", return_value="prefer-dark"), \
                 mock.patch("palettier.web_ui.get_service_status", return_value={"installed": False, "enabled": False, "active": False}):
                server = create_web_ui_server(port=0, config_path=cfg_path)
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()
                base = f"http://127.0.0.1:{server.server_address[1]}"
                try:
                    status_html, body_html = self._request(f"{base}/")
                    self.assertEqual(status_html, 200)
                    self.assertIn("Palettier Settings", body_html)
                    self.assertIn('id="t-gtk"', body_html)
                    self.assertIn('id="t-gtk_flatpak"', body_html)

                    status_st, body_st = self._request(f"{base}/api/state")
                    self.assertEqual(status_st, 200)
                    st_data = json.loads(body_st)
                    self.assertEqual(st_data["wallpaper_name"], "wall.png")
                    self.assertIn("scheme", st_data)

                    status_prev, body_prev = self._request(f"{base}/preview")
                    self.assertEqual(status_prev, 200)
                    self.assertIn("Palettier Material Design 3 Icons", body_prev)

                    status_cfg, body_cfg = self._request(
                        f"{base}/api/config",
                        method="POST",
                        payload={
                            "icon_mode": "places",
                            "icon_tint": 0.65,
                            "accent_override": "#e01b24",
                            "targets": {"firefox": False, "gtk_flatpak": False},
                        },
                    )
                    self.assertEqual(status_cfg, 200)
                    cfg_resp = json.loads(body_cfg)
                    self.assertTrue(cfg_resp["ok"])
                    self.assertEqual(cfg_resp["state"]["config"]["icon_mode"], "places")
                    self.assertEqual(cfg_resp["state"]["config"]["accent_override"], "#e01b24")
                    self.assertFalse(cfg_resp["state"]["config"]["targets"]["firefox"])
                    self.assertFalse(cfg_resp["state"]["config"]["targets"]["gtk_flatpak"])
                    self.assertTrue(cfg_resp["state"]["config"]["targets"]["gtk"])
                    self.assertTrue(cfg_path.is_file())

                    status_rst, body_rst = self._request(f"{base}/api/reset", method="POST", payload={})
                    self.assertEqual(status_rst, 200)
                    rst_resp = json.loads(body_rst)
                    self.assertEqual(rst_resp["state"]["config"]["icon_mode"], "system")
                    self.assertIsNone(rst_resp["state"]["config"]["accent_override"])

                    status_bye, _ = self._request(f"{base}/api/shutdown", method="POST", payload={})
                    self.assertEqual(status_bye, 200)
                finally:
                    server.shutdown()
                    server.server_close()
                    thread.join(timeout=2)

    def test_gui_fallback_and_cli_integration(self):
        with mock.patch("palettier.gui.is_gtk_adwaita_available", return_value=False), \
             mock.patch("palettier.gui.launch_web_ui") as m_web, \
             mock.patch("builtins.print"):
            rc = gui_main(force_web_ui=False, open_browser=False)
            self.assertEqual(rc, 0)
            m_web.assert_called_once_with(port=0, open_browser=False)

        with mock.patch("palettier.cli.gui_main", return_value=0) as m_gui:
            cli_main(["--web-ui", "--no-browser"])
            m_gui.assert_called_once_with(force_web_ui=True, open_browser=False)

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            wp = root / "wp.png"
            Image.new("RGB", (24, 24), (20, 130, 210)).save(wp)
            with mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": tmp}):
                save_config(PalettierConfig(icon_mode="places", targets={"starship": False}))
                out = io.StringIO()
                with contextlib.redirect_stdout(out), \
                     mock.patch("palettier.cli.gsettings_get", return_value="prefer-dark"):
                    cli_main(["--info", "--image", str(wp)])
                txt = out.getvalue()
                self.assertIn("Config file:", txt)
                self.assertIn("Enabled targets:     icons, gnome_accent, gtk, gtk_flatpak, ptyxis, firefox", txt)
                self.assertIn("M3 icon mode:        places", txt)


if __name__ == "__main__":
    unittest.main()
