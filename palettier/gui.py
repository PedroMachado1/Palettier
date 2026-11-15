"""
palettier.gui — Native GNOME Settings UI built with GTK 4 & Libadwaita.

Automatically falls back to `palettier.web_ui` when PyGObject / GTK 4 /
Libadwaita are not installed in the current environment.
"""

from __future__ import annotations

import os
import tempfile
import threading
import webbrowser
from pathlib import Path

from palettier.config import PalettierConfig, load_config, normalize_hex_color, reset_config, save_config
from palettier.icons import render_html_preview
from palettier.palette import build_m3_scheme
from palettier.service import get_service_status, set_service_enabled, uninstall_all
from palettier.sync import update_theme
from palettier.wallpaper import (
    extract_wallpaper_candidates,
    extract_wallpaper_colors,
    get_current_wallpaper_path,
    gsettings_get,
)
from palettier.web_ui import launch_web_ui

_ICON_MODE_OPTIONS = ["system", "places", "squircle", "off"]


def is_gtk_adwaita_available() -> bool:
    """Return True if PyGObject, GTK 4.0, and Libadwaita 1 are importable."""
    try:
        import gi

        gi.require_version("Gtk", "4.0")
        gi.require_version("Adw", "1")
        from gi.repository import Adw, Gtk  # noqa: F401

        return True
    except Exception:
        return False


def launch_gtk_gui() -> int:
    """Build and run the native GTK 4 + Libadwaita Palettier Settings app."""
    import gi

    gi.require_version("Gtk", "4.0")
    gi.require_version("Adw", "1")
    from gi.repository import Adw, Gdk, Gio, GLib, Gtk

    class PalettierWindow(Adw.ApplicationWindow):
        def __init__(self, app: Adw.Application) -> None:
            super().__init__(application=app, title="Palettier Settings")
            self.set_default_size(640, 740)
            self._cfg = load_config()
            self._loading = True
            self._wp_cache_key: tuple[str, int] | None = None
            self._wp_candidates: list[str] = []

            self._toast_overlay = Adw.ToastOverlay()
            toolbar_view = Adw.ToolbarView()

            header = Adw.HeaderBar()
            self._apply_btn = Gtk.Button(label="Apply")
            self._apply_btn.add_css_class("suggested-action")
            self._apply_btn.connect("clicked", self._on_apply_clicked)
            header.pack_end(self._apply_btn)

            preview_btn = Gtk.Button(icon_name="view-reveal-symbolic", tooltip_text="Open HTML Icon Preview")
            preview_btn.connect("clicked", self._on_preview_clicked)
            header.pack_start(preview_btn)

            toolbar_view.add_top_bar(header)

            page = Adw.PreferencesPage()
            toolbar_view.set_content(page)
            self._toast_overlay.set_child(toolbar_view)
            self.set_content(self._toast_overlay)

            # 1. Palette Summary Group
            self._summary_group = Adw.PreferencesGroup(title="Active Palette")
            self._wp_row = Adw.ActionRow(title="Wallpaper", subtitle="Detecting...")
            self._swatch_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
            self._swatch_box.set_valign(Gtk.Align.CENTER)
            self._wp_row.add_suffix(self._swatch_box)
            self._summary_group.add(self._wp_row)
            page.add(self._summary_group)

            # 2. Color and Extraction Group
            color_group = Adw.PreferencesGroup(
                title="Color and Extraction",
                description="Control how Palettier derives your Material Design 3 seed color.",
            )
            self._auto_accent_row = Adw.SwitchRow(
                title="Automatic Accent from Wallpaper",
                subtitle="Extract the dominant vibrant hue automatically",
            )
            self._auto_accent_row.connect("notify::active", self._on_setting_changed)
            color_group.add(self._auto_accent_row)

            self._extracted_row = Adw.ActionRow(
                title="Extracted Wallpaper Colors",
                subtitle="Click a swatch to pick an accent color from the wallpaper",
            )
            self._candidates_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
            self._candidates_box.set_valign(Gtk.Align.CENTER)
            self._extracted_row.add_suffix(self._candidates_box)
            color_group.add(self._extracted_row)

            self._custom_accent_row = Adw.ActionRow(
                title="Custom Accent Color",
                subtitle="Used when automatic extraction is disabled",
            )
            self._color_btn = Gtk.ColorDialogButton(dialog=Gtk.ColorDialog())
            self._color_btn.set_valign(Gtk.Align.CENTER)
            self._color_btn.connect("notify::rgba", self._on_color_picked)
            self._custom_accent_row.add_suffix(self._color_btn)
            color_group.add(self._custom_accent_row)

            self._auto_surface_row = Adw.SwitchRow(
                title="Automatic Surface Tint",
                subtitle="Adapt terminal and browser background tint to wallpaper saturation",
            )
            self._auto_surface_row.connect("notify::active", self._on_setting_changed)
            color_group.add(self._auto_surface_row)

            self._surface_row = Adw.ActionRow(title="Surface Tint Intensity")
            self._surface_scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0.0, 0.30, 0.01)
            self._surface_scale.set_size_request(180, -1)
            self._surface_scale.set_draw_value(True)
            self._surface_scale.set_valign(Gtk.Align.CENTER)
            self._surface_scale.connect("value-changed", self._on_setting_changed)
            self._surface_row.add_suffix(self._surface_scale)
            color_group.add(self._surface_row)
            page.add(color_group)

            # 3. Material Design 3 Icon Pack Group
            icon_group = Adw.PreferencesGroup(title="Material Design 3 Icon Pack")
            mode_model = Gtk.StringList.new(_ICON_MODE_OPTIONS)
            self._icon_mode_row = Adw.ComboRow(
                title="Icon Generation Mode",
                subtitle="system tints all installed apps; places tints folders and mimetypes only",
                model=mode_model,
            )
            self._icon_mode_row.connect("notify::selected", self._on_setting_changed)
            icon_group.add(self._icon_mode_row)

            self._icon_tint_row = Adw.ActionRow(
                title="App Icon Filter Strength",
                subtitle="Blend strength applied to installed application icons",
            )
            self._icon_tint_scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0.0, 1.0, 0.05)
            self._icon_tint_scale.set_size_request(180, -1)
            self._icon_tint_scale.set_draw_value(True)
            self._icon_tint_scale.set_valign(Gtk.Align.CENTER)
            self._icon_tint_scale.connect("value-changed", self._on_setting_changed)
            self._icon_tint_row.add_suffix(self._icon_tint_scale)
            icon_group.add(self._icon_tint_row)
            page.add(icon_group)

            # 4. Desktop Integrations Group
            targets_group = Adw.PreferencesGroup(
                title="Desktop Integrations",
                description="Choose which components Palettier synchronizes.",
            )
            self._target_rows: dict[str, Adw.SwitchRow] = {}
            target_labels = [
                ("icons", "Material 3 Icon Theme", "GNOME Shell, Nautilus, and AppImage bridge"),
                ("gnome_accent", "GNOME 47+ Native Accent", "Sync org.gnome.desktop.interface accent-color"),
                ("gtk", "GTK 3 and 4 Apps", "Apply Material 3 accent and surface colors via gtk.css"),
                ("gtk_flatpak", "GTK Flatpak Integration", "Grant read-only gtk-3.0/gtk-4.0 CSS access to Flatpak apps"),
                ("ptyxis", "Ptyxis Terminal", "Update palettier.palette and active profiles"),
                ("starship", "Starship Prompt", "Update ~/.config/starship.toml palette"),
                ("firefox", "Firefox Browser", "Generate userChrome.css for all profiles"),
            ]
            for key, title, sub in target_labels:
                row = Adw.SwitchRow(
                    title=GLib.markup_escape_text(title, -1),
                    subtitle=GLib.markup_escape_text(sub, -1),
                )
                row.connect("notify::active", self._on_setting_changed)
                targets_group.add(row)
                self._target_rows[key] = row
            page.add(targets_group)

            # 5. Service and Maintenance Group
            svc_group = Adw.PreferencesGroup(title="Background Service and Maintenance")
            self._service_row = Adw.SwitchRow(
                title="Auto-Sync Daemon (palettier.service)",
                subtitle="Watch wallpaper and dark/light mode changes automatically",
            )
            self._service_row.connect("notify::active", self._on_service_toggled)
            svc_group.add(self._service_row)

            reset_row = Adw.ActionRow(title="Reset Defaults", subtitle="Restore default Palettier settings")
            reset_btn = Gtk.Button(label="Reset")
            reset_btn.set_valign(Gtk.Align.CENTER)
            reset_btn.connect("clicked", self._on_reset_clicked)
            reset_row.add_suffix(reset_btn)
            svc_group.add(reset_row)

            uninstall_row = Adw.ActionRow(
                title="Uninstall Themes and Restore Apps",
                subtitle="Stop service, remove generated icons/palettes, and restore defaults",
            )
            uninst_btn = Gtk.Button(label="Uninstall")
            uninst_btn.add_css_class("destructive-action")
            uninst_btn.set_valign(Gtk.Align.CENTER)
            uninst_btn.connect("clicked", self._on_uninstall_clicked)
            uninstall_row.add_suffix(uninst_btn)
            svc_group.add(uninstall_row)
            page.add(svc_group)

            self._sync_widgets_from_config()
            self._refresh_palette_summary()
            self._loading = False

        def _toast(self, message: str) -> None:
            self._toast_overlay.add_toast(Adw.Toast.new(message))

        def _sync_widgets_from_config(self) -> None:
            self._loading = True
            cfg = self._cfg
            auto_accent = cfg.accent_override is None
            self._auto_accent_row.set_active(auto_accent)
            self._custom_accent_row.set_sensitive(not auto_accent)

            rgba = Gdk.RGBA()
            rgba.parse(cfg.accent_override or "#3584e4")
            self._color_btn.set_rgba(rgba)

            auto_surf = cfg.surface_tint is None
            self._auto_surface_row.set_active(auto_surf)
            self._surface_row.set_sensitive(not auto_surf)
            self._surface_scale.set_value(cfg.surface_tint if cfg.surface_tint is not None else 0.10)

            mode = "system" if cfg.icon_mode == "full" else cfg.icon_mode
            idx = _ICON_MODE_OPTIONS.index(mode) if mode in _ICON_MODE_OPTIONS else 0
            self._icon_mode_row.set_selected(idx)
            self._icon_tint_scale.set_value(cfg.icon_tint)

            for key, row in self._target_rows.items():
                row.set_active(bool(cfg.targets.get(key, True)))
            if "gtk_flatpak" in self._target_rows and "gtk" in self._target_rows:
                self._target_rows["gtk_flatpak"].set_sensitive(self._target_rows["gtk"].get_active())

            svc = get_service_status()
            self._service_row.set_active(bool(svc["enabled"]))
            self._loading = False

        def _collect_config_from_widgets(self) -> PalettierConfig:
            auto_accent = self._auto_accent_row.get_active()
            rgba = self._color_btn.get_rgba()
            picked_hex = "#{:02x}{:02x}{:02x}".format(
                int(round(rgba.red * 255)),
                int(round(rgba.green * 255)),
                int(round(rgba.blue * 255)),
            )
            auto_surf = self._auto_surface_row.get_active()
            mode_idx = self._icon_mode_row.get_selected()
            mode = _ICON_MODE_OPTIONS[mode_idx] if 0 <= mode_idx < len(_ICON_MODE_OPTIONS) else "system"

            return PalettierConfig(
                icon_mode=mode,
                icon_tint=self._icon_tint_scale.get_value(),
                surface_tint=None if auto_surf else self._surface_scale.get_value(),
                accent_override=None if auto_accent else normalize_hex_color(picked_hex),
                targets={k: row.get_active() for k, row in self._target_rows.items()},
            )

        def _refresh_palette_summary(self) -> None:
            wp = get_current_wallpaper_path()
            cache_key = (str(wp), wp.stat().st_mtime_ns) if wp and wp.exists() else None
            if cache_key != self._wp_cache_key or not self._wp_candidates:
                candidates, _, wp = extract_wallpaper_candidates(
                    wp,
                    forced_tint=self._cfg.surface_tint,
                    max_colors=6,
                )
                self._wp_candidates = candidates
                self._wp_cache_key = cache_key
            else:
                candidates = self._wp_candidates

            accent = self._cfg.accent_override or candidates[0]
            cs = gsettings_get("org.gnome.desktop.interface", "color-scheme")
            is_dark = "dark" in (cs or "prefer-dark").lower()
            scheme = build_m3_scheme(accent, is_dark=is_dark)

            wp_title = wp.name if wp else "No wallpaper detected"
            self._wp_row.set_title(GLib.markup_escape_text(wp_title, -1))
            self._wp_row.set_subtitle(f"Seed: {accent} · Mode: {scheme['mode']} · Primary: {scheme['primary']}")

            while (child := self._swatch_box.get_first_child()) is not None:
                self._swatch_box.remove(child)
            for token in ("primary", "secondary", "tertiary", "primaryContainer"):
                swatch = Gtk.DrawingArea()
                swatch.set_content_width(20)
                swatch.set_content_height(20)
                color_hex = scheme[token]

                def _draw(area, cr, w, h, col=color_hex):
                    c = Gdk.RGBA()
                    c.parse(col)
                    cr.arc(w / 2, h / 2, min(w, h) / 2 - 1, 0, 6.283185)
                    cr.set_source_rgba(c.red, c.green, c.blue, c.alpha)
                    cr.fill()

                swatch.set_draw_func(_draw)
                swatch.set_tooltip_text(f"{token}: {color_hex}")
                self._swatch_box.append(swatch)

            while (child := self._candidates_box.get_first_child()) is not None:
                self._candidates_box.remove(child)
            active_hex = accent.lower()
            ring_hex = "#ffffff" if is_dark else "#1f1f1f"
            for hex_col in candidates:
                is_selected = hex_col.lower() == active_hex
                btn = Gtk.Button()
                btn.add_css_class("flat")
                btn.add_css_class("circular")
                btn.set_valign(Gtk.Align.CENTER)
                btn.set_tooltip_text(f"Use {hex_col}" + (" (active)" if is_selected else ""))

                dot = Gtk.DrawingArea()
                dot.set_content_width(24)
                dot.set_content_height(24)

                def _draw_cand(area, cr, w, h, col=hex_col, selected=is_selected, rcol=ring_hex):
                    c = Gdk.RGBA()
                    c.parse(col)
                    cx, cy = w / 2.0, h / 2.0
                    radius = min(w, h) / 2.0 - 3.5
                    cr.arc(cx, cy, radius, 0, 6.283185)
                    cr.set_source_rgba(c.red, c.green, c.blue, c.alpha)
                    cr.fill()
                    if selected:
                        rc = Gdk.RGBA()
                        rc.parse(rcol)
                        cr.arc(cx, cy, radius + 2.0, 0, 6.283185)
                        cr.set_source_rgba(rc.red, rc.green, rc.blue, 0.9)
                        cr.set_line_width(2.0)
                        cr.stroke()

                dot.set_draw_func(_draw_cand)
                btn.set_child(dot)
                btn.connect("clicked", lambda _b, c=hex_col: self._on_candidate_clicked(c))
                self._candidates_box.append(btn)

        def _on_candidate_clicked(self, hex_col: str) -> None:
            self._loading = True
            self._auto_accent_row.set_active(False)
            rgba = Gdk.RGBA()
            rgba.parse(hex_col)
            self._color_btn.set_rgba(rgba)
            self._loading = False
            self._on_setting_changed()

        def _on_color_picked(self, *_args) -> None:
            if self._loading:
                return
            self._on_setting_changed()

        def _on_setting_changed(self, *_args) -> None:
            if self._loading:
                return
            self._custom_accent_row.set_sensitive(not self._auto_accent_row.get_active())
            self._surface_row.set_sensitive(not self._auto_surface_row.get_active())
            if "gtk_flatpak" in self._target_rows and "gtk" in self._target_rows:
                self._target_rows["gtk_flatpak"].set_sensitive(self._target_rows["gtk"].get_active())
            self._cfg = self._collect_config_from_widgets()
            save_config(self._cfg)
            self._refresh_palette_summary()

        def _on_apply_clicked(self, *_args) -> None:
            self._cfg = self._collect_config_from_widgets()
            save_config(self._cfg)
            self._apply_btn.set_sensitive(False)
            self._toast("Applying Material Design 3 theme...")

            def _worker() -> None:
                ok = update_theme(force=True, config=self._cfg)

                def _done() -> bool:
                    self._apply_btn.set_sensitive(True)
                    self._refresh_palette_summary()
                    self._toast("Theme applied successfully!" if ok else "Saved settings (no target files updated).")
                    return GLib.SOURCE_REMOVE

                GLib.idle_add(_done)

            threading.Thread(target=_worker, daemon=True).start()

        def _on_preview_clicked(self, *_args) -> None:
            wp = get_current_wallpaper_path()
            accent = self._cfg.accent_override or extract_wallpaper_colors(wp)[0]
            cs = gsettings_get("org.gnome.desktop.interface", "color-scheme")
            is_dark = "dark" in (cs or "prefer-dark").lower()
            scheme = build_m3_scheme(accent, is_dark=is_dark)
            mode = "system" if self._cfg.icon_mode == "off" else self._cfg.icon_mode
            html_doc = render_html_preview(scheme, mode=mode, tint_strength=self._cfg.icon_tint)
            out_path = Path(tempfile.gettempdir()) / f"palettier-preview-{os.getuid()}.html"
            out_path.write_text(html_doc, encoding="utf-8")
            webbrowser.open(out_path.as_uri())

        def _on_service_toggled(self, row, _pspec) -> None:
            if self._loading:
                return
            enabled = row.get_active()
            ok = set_service_enabled(enabled)
            if ok:
                self._toast("Background service enabled." if enabled else "Background service stopped.")
            else:
                self._toast("Could not update systemd user service.")

        def _on_reset_clicked(self, *_args) -> None:
            self._cfg = reset_config()
            self._sync_widgets_from_config()
            self._refresh_palette_summary()
            self._toast("Defaults restored.")

        def _on_uninstall_clicked(self, *_args) -> None:
            dialog = Adw.MessageDialog(
                transient_for=self,
                heading="Uninstall Palettier Themes?",
                body="This stops the background service, removes generated icon themes and palettes, and restores your original applications.",
            )
            dialog.add_response("cancel", "Cancel")
            dialog.add_response("uninstall", "Uninstall")
            dialog.set_response_appearance("uninstall", Adw.ResponseAppearance.DESTRUCTIVE)

            def _on_resp(_dlg, resp: str) -> None:
                if resp == "uninstall":
                    uninstall_all()
                    self._sync_widgets_from_config()
                    self._toast("Palettier themes uninstalled.")

            dialog.connect("response", _on_resp)
            dialog.present()

    app = Adw.Application(application_id="io.github.PedroMachado1.Palettier", flags=Gio.ApplicationFlags.FLAGS_NONE)

    def _on_activate(application: Adw.Application) -> None:
        win = application.get_active_window()
        if not win:
            win = PalettierWindow(application)
        win.present()

    app.connect("activate", _on_activate)
    return int(app.run([]))


def main(force_web_ui: bool = False, port: int = 0, open_browser: bool = True) -> int:
    """Launch the Palettier Settings GUI (GTK4/Libadwaita or Web UI fallback)."""
    if not force_web_ui and is_gtk_adwaita_available():
        return launch_gtk_gui()

    if not force_web_ui:
        print("[*] GTK 4 / Libadwaita not available. Starting local Web Settings UI...")
    launch_web_ui(port=port, open_browser=open_browser)
    return 0
