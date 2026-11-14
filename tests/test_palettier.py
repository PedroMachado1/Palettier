"""Tests for Palettier targets, state, service installer, and CLI."""

from __future__ import annotations

import contextlib
import io
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from PIL import Image

from palettier import __version__
from palettier.cli import main
from palettier.palette import map_hex_to_gnome_accent
from palettier.service import SERVICE_NAME, install_user_service, uninstall_all
from palettier.state import get_state_file_path, load_saved_state, save_state
from palettier.targets import (
    generate_firefox_userchrome_css,
    update_firefox_theme,
    update_ptyxis_theme,
    update_starship_theme,
)
from palettier.wallpaper import extract_wallpaper_colors


class TestPalettierTargetsAndCLI(unittest.TestCase):
    def test_starship_theme_update_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            starship = Path(tmp) / "starship.toml"
            starship.write_text('format = "$all"\npalette = "other"\n', encoding="utf-8")

            self.assertTrue(update_starship_theme("#3584e4", 0.10, starship_toml=starship))
            txt1 = starship.read_text(encoding="utf-8")
            self.assertIn("palette = 'palettier'", txt1)
            self.assertIn("[palettes.palettier]", txt1)

            # Second update should not duplicate [palettes.palettier]
            self.assertTrue(update_starship_theme("#e01b24", 0.12, starship_toml=starship))
            txt2 = starship.read_text(encoding="utf-8")
            self.assertEqual(txt2.count("[palettes.palettier]"), 1)
            self.assertIn("color_orange = '#e01b24'", txt2)

    def test_ptyxis_and_firefox_targets(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pal_dir = root / "ptyxis" / "palettes"
            self.assertTrue(update_ptyxis_theme("#3584e4", 0.10, palettes_dir=pal_dir))
            pal_file = pal_dir / "palettier.palette"
            self.assertTrue(pal_file.is_file())
            self.assertIn("Name=Palettier", pal_file.read_text(encoding="utf-8"))

            ff_profile = root / "ff_profile"
            ff_profile.mkdir()
            ref_css = root / "ref-userChrome.css"
            self.assertTrue(
                update_firefox_theme("#3584e4", 0.10, profile_dirs=[ff_profile], reference_path=ref_css)
            )
            self.assertIn("Palettier", (ff_profile / "chrome" / "userChrome.css").read_text(encoding="utf-8"))
            self.assertIn(
                'user_pref("toolkit.legacyUserProfileCustomizations.stylesheets", true);',
                (ff_profile / "user.js").read_text(encoding="utf-8"),
            )
            self.assertIn("Palettier", generate_firefox_userchrome_css("#3584e4", 0.10))

    def test_state_file_roundtrip_and_wallpaper_extraction(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with mock.patch.dict(os.environ, {"XDG_RUNTIME_DIR": str(root)}):
                state_path = get_state_file_path()
                self.assertEqual(state_path.name, "palettier.state")
                payload = {"accent_color": "#3584e4", "icon_mode": "system"}
                self.assertTrue(save_state(payload))
                self.assertEqual(load_saved_state(), payload)

            img_path = root / "wp.png"
            Image.new("RGB", (64, 64), (210, 45, 50)).save(img_path)
            accent, tint, resolved = extract_wallpaper_colors(img_path)
            self.assertEqual(resolved, img_path)
            self.assertTrue(accent.startswith("#"))
            self.assertEqual(map_hex_to_gnome_accent(accent), "red")
            self.assertGreaterEqual(tint, 0.08)

    def test_service_install_and_uninstall_all(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            svc_dir = root / "systemd"
            starship = root / "starship.toml"
            starship.write_text('format = "$all"\n', encoding="utf-8")
            pal_dir = root / "palettes"
            ff_profile = root / "ff"
            ff_profile.mkdir()
            state_file = root / "palettier.state"
            state_file.write_text("{}", encoding="utf-8")

            update_starship_theme("#3584e4", 0.10, starship_toml=starship)
            update_ptyxis_theme("#3584e4", 0.10, palettes_dir=pal_dir)
            update_firefox_theme("#3584e4", 0.10, profile_dirs=[ff_profile], reference_path=root / "ref.css")

            with mock.patch("builtins.print"):
                svc_file = install_user_service(service_dir=svc_dir)
            self.assertTrue(svc_file.is_file())
            self.assertEqual(svc_file.name, SERVICE_NAME)
            svc_txt = svc_file.read_text(encoding="utf-8")
            self.assertIn("Palettier Theme Synchronizer", svc_txt)
            self.assertIn("-m palettier --watch", svc_txt)

            with mock.patch("palettier.service.subprocess.run"), mock.patch(
                "palettier.service.get_ptyxis_palette_paths",
                return_value=[pal_dir / "palettier.palette"],
            ), mock.patch.dict(os.environ, {"XDG_DATA_HOME": str(root / "xdg")}), mock.patch("builtins.print"):
                uninstall_all(
                    service_dir=svc_dir,
                    starship_toml=starship,
                    palettes_dir=pal_dir,
                    firefox_profiles=[ff_profile],
                    state_file=state_file,
                )

            self.assertFalse(svc_file.exists())
            self.assertFalse((pal_dir / "palettier.palette").exists())
            self.assertFalse((ff_profile / "chrome" / "userChrome.css").exists())
            self.assertFalse(state_file.exists())
            self.assertNotIn("palettier", starship.read_text(encoding="utf-8"))

    def test_cli_info_preview_and_version(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            wp = root / "wall.png"
            Image.new("RGB", (32, 32), (30, 120, 220)).save(wp)
            preview = root / "preview.html"

            out_info = io.StringIO()
            with contextlib.redirect_stdout(out_info), mock.patch("palettier.cli.gsettings_get", return_value="prefer-dark"):
                main(["--info", "--image", str(wp)])
            self.assertIn("=== Palettier Info ===", out_info.getvalue())

            out_prev = io.StringIO()
            with contextlib.redirect_stdout(out_prev), mock.patch("palettier.cli.gsettings_get", return_value="prefer-dark"):
                main(["--preview-icons", str(preview), "--image", str(wp), "--icon-mode", "places"])
            self.assertTrue(preview.is_file())
            self.assertIn("Palettier Material Design 3 Icons", preview.read_text(encoding="utf-8"))

            out_ver = io.StringIO()
            with self.assertRaises(SystemExit) as cm, contextlib.redirect_stdout(out_ver):
                main(["--version"])
            self.assertEqual(cm.exception.code, 0)
            self.assertIn(__version__, out_ver.getvalue())


if __name__ == "__main__":
    unittest.main()
