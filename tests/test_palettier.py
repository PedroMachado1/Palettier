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
from palettier.palette import contrast_ratio, map_hex_to_gnome_accent
from palettier.service import SERVICE_NAME, install_user_service, uninstall_all
from palettier.state import get_state_file_path, load_saved_state, save_state
from palettier.targets import (
    compute_gtk_palette_tokens,
    generate_firefox_userchrome_css,
    generate_gtk3_css,
    generate_gtk4_css,
    remove_gtk_theme,
    revert_flatpak_gtk_overrides,
    sync_flatpak_gtk_overrides,
    update_firefox_theme,
    update_gtk_theme,
    update_ptyxis_theme,
    update_starship_theme,
)
from palettier.wallpaper import extract_wallpaper_candidates, extract_wallpaper_colors


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

    def test_gtk_themes_contrast_and_user_css_preservation(self):
        for seed in ("#3584e4", "#e01b24", "#2ec27e", "#f6d32d"):
            for is_dark in (True, False):
                tokens = compute_gtk_palette_tokens(seed, 0.15, is_dark=is_dark)
                self.assertGreaterEqual(contrast_ratio(tokens["accent_bg_color"], tokens["accent_fg_color"]), 4.5)
                self.assertGreaterEqual(contrast_ratio(tokens["window_bg_color"], tokens["window_fg_color"]), 7.0)

        t_zero = compute_gtk_palette_tokens("#e01b24", 0.0, is_dark=True)
        t_high = compute_gtk_palette_tokens("#e01b24", 0.25, is_dark=True)
        self.assertNotEqual(t_zero["window_bg_color"], t_high["window_bg_color"])

        css4 = generate_gtk4_css("#3584e4", 0.12, is_dark=True)
        self.assertIn("@define-color accent_bg_color", css4)
        self.assertIn("--accent-bg-color:", css4)
        self.assertIn("--window-bg-color:", css4)

        css3 = generate_gtk3_css("#3584e4", 0.12, is_dark=False)
        self.assertIn("@define-color theme_selected_bg_color", css3)
        self.assertNotIn(":root {", css3)

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            gtk4 = root / "gtk-4.0"
            gtk3 = root / "gtk-3.0"
            gtk4.mkdir(parents=True)
            user_rule = "window { border-radius: 12px; }\n"
            (gtk4 / "gtk.css").write_text(user_rule, encoding="utf-8")

            self.assertTrue(update_gtk_theme("#3584e4", 0.12, is_dark=True, gtk4_dir=gtk4, gtk3_dir=gtk3))
            self.assertTrue((gtk4 / "palettier.css").is_file())
            self.assertTrue((gtk3 / "palettier.css").is_file())
            gtk4_css_txt = (gtk4 / "gtk.css").read_text(encoding="utf-8")
            self.assertTrue(gtk4_css_txt.startswith("/* BEGIN PALETTIER"))
            self.assertIn('@import url("palettier.css");', gtk4_css_txt)
            self.assertIn(user_rule.strip(), gtk4_css_txt)

            # Second update remains idempotent without duplicating markers or user rules
            self.assertTrue(update_gtk_theme("#e01b24", 0.15, is_dark=False, gtk4_dir=gtk4, gtk3_dir=gtk3))
            gtk4_css_txt2 = (gtk4 / "gtk.css").read_text(encoding="utf-8")
            self.assertEqual(gtk4_css_txt2.count("BEGIN PALETTIER"), 1)
            self.assertEqual(gtk4_css_txt2.count("border-radius: 12px;"), 1)

            # Cleanup removes palettier.css, deletes empty gtk-3.0/gtk.css, preserves user CSS in gtk-4.0/gtk.css
            remove_gtk_theme(gtk4_dir=gtk4, gtk3_dir=gtk3, revert_flatpak=False)
            self.assertFalse((gtk4 / "palettier.css").exists())
            self.assertFalse((gtk3 / "palettier.css").exists())
            self.assertFalse((gtk3 / "gtk.css").exists())
            self.assertEqual((gtk4 / "gtk.css").read_text(encoding="utf-8"), user_rule)

    def test_flatpak_gtk_override_sync_and_revert(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            marker = root / "state" / "flatpak-gtk-overrides.json"
            global_ov = root / "data" / "flatpak" / "overrides" / "global"
            global_ov.parent.mkdir(parents=True)
            global_ov.write_text("[Context]\nfilesystems=xdg-documents;\n", encoding="utf-8")

            calls: list[list[str]] = []

            def fake_run(cmd, **_kwargs):
                calls.append(cmd)
                res = mock.Mock()
                res.returncode = 0
                if "--show" in cmd:
                    res.stdout = "[Context]\nfilesystems=xdg-documents;\n"
                else:
                    res.stdout = ""
                return res

            with mock.patch("palettier.targets.shutil.which", return_value="/usr/bin/flatpak"), \
                 mock.patch("palettier.targets.subprocess.run", side_effect=fake_run):
                self.assertTrue(sync_flatpak_gtk_overrides(marker_path=marker))

            self.assertTrue(marker.is_file())
            marker_data = marker.read_text(encoding="utf-8")
            self.assertIn("xdg-config/gtk-4.0:ro", marker_data)
            self.assertIn("xdg-config/gtk-3.0:ro", marker_data)
            self.assertTrue(any("--filesystem=xdg-config/gtk-4.0:ro" in c for c in calls))
            self.assertTrue(any("--filesystem=xdg-config/gtk-3.0:ro" in c for c in calls))

            # Simulate Flatpak having updated the global override file and revert cleanly
            global_ov.write_text(
                "[Context]\nfilesystems=xdg-documents;xdg-config/gtk-4.0:ro;xdg-config/gtk-3.0:ro;\n",
                encoding="utf-8",
            )
            self.assertTrue(revert_flatpak_gtk_overrides(marker_path=marker, global_override_path=global_ov))
            self.assertFalse(marker.exists())
            ov_txt = global_ov.read_text(encoding="utf-8")
            self.assertIn("xdg-documents", ov_txt)
            self.assertNotIn("gtk-4.0", ov_txt)
            self.assertNotIn("gtk-3.0", ov_txt)

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

    def test_extract_wallpaper_candidates_multicolor_png_and_svg(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)

            # Multi-color PNG with 4 distinct vibrant quadrants
            multi_png = root / "multi.png"
            img = Image.new("RGB", (120, 120))
            for y in range(120):
                for x in range(120):
                    if x < 60 and y < 60:
                        img.putpixel((x, y), (45, 130, 225))
                    elif x >= 60 and y < 60:
                        img.putpixel((x, y), (46, 194, 126))
                    elif x < 60 and y >= 60:
                        img.putpixel((x, y), (224, 55, 65))
                    else:
                        img.putpixel((x, y), (235, 165, 45))
            img.save(multi_png)

            candidates, _tint, resolved = extract_wallpaper_candidates(multi_png, max_colors=5)
            primary, _, _ = extract_wallpaper_colors(multi_png)
            self.assertEqual(resolved, multi_png)
            self.assertGreaterEqual(len(candidates), 3)
            self.assertLessEqual(len(candidates), 5)
            self.assertEqual(candidates[0], primary)
            self.assertEqual(len(set(candidates)), len(candidates))

            # Multi-color SVG
            multi_svg = root / "multi.svg"
            multi_svg.write_text(
                '<svg xmlns="http://www.w3.org/2000/svg">'
                '<rect fill="#3584e4"/><rect fill="#2ec27e"/><rect fill="#e01b24"/><rect fill="#f5c211"/>'
                "</svg>",
                encoding="utf-8",
            )
            svg_candidates, _, svg_resolved = extract_wallpaper_candidates(multi_svg, max_colors=4)
            self.assertEqual(svg_resolved, multi_svg)
            self.assertGreaterEqual(len(svg_candidates), 3)
            self.assertEqual(svg_candidates[0], extract_wallpaper_colors(multi_svg)[0])

            # Monochrome fallback and missing file fallback
            gray_png = root / "gray.png"
            Image.new("RGB", (40, 40), (110, 110, 110)).save(gray_png)
            gray_cands, _, _ = extract_wallpaper_candidates(gray_png)
            self.assertEqual(gray_cands, ["#4a8fe7"])

            missing_cands, _, missing_wp = extract_wallpaper_candidates(root / "missing.png")
            self.assertEqual(missing_cands, ["#3584e4"])
            self.assertIsNone(missing_wp)

    def test_service_install_and_uninstall_all(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            svc_dir = root / "systemd"
            starship = root / "starship.toml"
            starship.write_text('format = "$all"\n', encoding="utf-8")
            pal_dir = root / "palettes"
            ff_profile = root / "ff"
            ff_profile.mkdir()
            gtk4_dir = root / "gtk-4.0"
            gtk3_dir = root / "gtk-3.0"
            state_file = root / "palettier.state"
            state_file.write_text("{}", encoding="utf-8")

            update_starship_theme("#3584e4", 0.10, starship_toml=starship)
            update_ptyxis_theme("#3584e4", 0.10, palettes_dir=pal_dir)
            update_firefox_theme("#3584e4", 0.10, profile_dirs=[ff_profile], reference_path=root / "ref.css")
            update_gtk_theme("#3584e4", 0.10, is_dark=True, gtk4_dir=gtk4_dir, gtk3_dir=gtk3_dir)

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
                    gtk4_dir=gtk4_dir,
                    gtk3_dir=gtk3_dir,
                )

            self.assertFalse(svc_file.exists())
            self.assertFalse((pal_dir / "palettier.palette").exists())
            self.assertFalse((ff_profile / "chrome" / "userChrome.css").exists())
            self.assertFalse((gtk4_dir / "palettier.css").exists())
            self.assertFalse((gtk3_dir / "palettier.css").exists())
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
