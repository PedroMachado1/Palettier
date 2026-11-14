"""
palettier.targets — Theme generators and updaters for Starship, Ptyxis, Firefox, and GNOME.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

from palettier.palette import adjust_lightness, hex_to_rgb, map_hex_to_gnome_accent, mix
from palettier.wallpaper import gsettings_get, gsettings_set

_PACKAGE_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _PACKAGE_DIR.parent
FIREFOX_THEME = _REPO_ROOT / "firefox-userChrome.css"
STARSHIP_TOML = Path.home() / ".config" / "starship.toml"
PTYXIS_PALETTES_DIR = Path.home() / ".local" / "share" / "org.gnome.Ptyxis" / "palettes"


def _write_text_if_changed(path: Path, content: str) -> bool:
    """Write text to disk only when content differs from the existing file."""
    try:
        if path.exists() and path.read_text(encoding="utf-8") == content:
            return False
    except Exception:
        pass
    path.write_text(content, encoding="utf-8")
    return True


def sync_gnome_accent_color(accent: str) -> bool:
    """
    Update GNOME 47+ native accent-color only if it differs from the current value.
    Always calls `gsettings get` before `gsettings set`.
    """
    gnome_color = map_hex_to_gnome_accent(accent)
    current_accent = gsettings_get("org.gnome.desktop.interface", "accent-color")
    if current_accent is None or current_accent == gnome_color:
        return False
    return gsettings_set("org.gnome.desktop.interface", "accent-color", gnome_color)


def update_starship_theme(
    accent: str,
    tint: float,
    starship_toml: Path | None = None,
) -> bool:
    """Update the Starship prompt palette in ~/.config/starship.toml."""
    target = starship_toml or STARSHIP_TOML
    if not target.exists():
        return False
    try:
        bg_toolbar = mix("#14171d", accent, tint * 1.1)
        bg_tab_active = mix("#1f242e", accent, min(tint * 1.3, 0.25))

        c_orange = accent
        c_yellow = adjust_lightness(accent, 0.14)
        c_aqua = mix(accent, "#38bdf8", 0.45)
        c_blue = mix(accent, "#818cf8", 0.35)
        c_purple = mix(accent, "#c084fc", 0.45)

        palette_block = f"""[palettes.palettier]
color_fg0 = '#ffffff'
color_bg1 = '{bg_toolbar}'
color_bg3 = '{bg_tab_active}'
color_blue = '{c_blue}'
color_aqua = '{c_aqua}'
color_green = '#3dd68c'
color_orange = '{c_orange}'
color_purple = '{c_purple}'
color_red = '#ff5449'
color_yellow = '{c_yellow}'"""

        content = target.read_text(encoding="utf-8")

        if re.search(r"^\s*palette\s*=", content, re.MULTILINE):
            content = re.sub(r"palette\s*=\s*['\"].*?['\"]", "palette = 'palettier'", content)
        else:
            content = "palette = 'palettier'\n" + content

        # Remove any existing [palettes.palettier] section(s) cleanly and idempotently
        content = re.sub(r"\n*\[palettes\.palettier\][\s\S]*?(?=\n\[|$)", "", content)
        content = content.rstrip() + "\n\n" + palette_block + "\n"

        _write_text_if_changed(target, content)
        return True
    except Exception as e:
        print(f"[!] Error updating starship.toml: {e}")
        return False


def get_ptyxis_palette_paths(palettes_dir: Path | None = None) -> list[Path]:
    """Return native and Flatpak Ptyxis palette file paths managed by Palettier."""
    base_dir = palettes_dir or PTYXIS_PALETTES_DIR
    paths = [base_dir / "palettier.palette"]
    if palettes_dir is None:
        paths.extend([
            Path.home() / ".var" / "app" / "org.gnome.Ptyxis" / "data" / "ptyxis" / "palettes" / "palettier.palette",
            Path.home() / ".var" / "app" / "org.gnome.Ptyxis" / "data" / "org.gnome.Ptyxis" / "palettes" / "palettier.palette",
            Path.home() / ".var" / "app" / "app.devsuite.Ptyxis" / "data" / "ptyxis" / "palettes" / "palettier.palette",
        ])
    return paths


def update_ptyxis_theme(
    accent: str,
    tint: float,
    palettes_dir: Path | None = None,
) -> bool:
    """Update the Ptyxis terminal emulator palette and active profile."""
    try:
        target_dir = palettes_dir or PTYXIS_PALETTES_DIR
        target_dir.mkdir(parents=True, exist_ok=True)
        bg_window = mix("#0f1115", accent, tint)
        fg = "#f4f6fa"
        light_accent = adjust_lightness(accent, 0.12)

        palette_content = f"""[Palette]
Name=Palettier
Primary=true
UseSystemAccent=true
Background={bg_window}
Foreground={fg}
Cursor={accent}
CursorForeground=#ffffff
TitlebarBackground={bg_window}
TitlebarForeground={fg}
Color0={bg_window}
Color1=#f87171
Color2=#3dd68c
Color3=#fbbf24
Color4={accent}
Color5=#c084fc
Color6=#38bdf8
Color7={fg}
Color8=#475569
Color9=#ef4444
Color10=#22c55e
Color11=#eab308
Color12={light_accent}
Color13=#a855f7
Color14=#06b6d4
Color15=#ffffff
"""
        _write_text_if_changed(target_dir / "palettier.palette", palette_content)

        if palettes_dir is None:
            flatpak_dirs = [
                Path.home() / ".var" / "app" / "org.gnome.Ptyxis" / "data" / "ptyxis" / "palettes",
                Path.home() / ".var" / "app" / "org.gnome.Ptyxis" / "data" / "org.gnome.Ptyxis" / "palettes",
                Path.home() / ".var" / "app" / "app.devsuite.Ptyxis" / "data" / "ptyxis" / "palettes",
            ]
            for fdir in flatpak_dirs:
                if fdir.parent.exists():
                    fdir.mkdir(parents=True, exist_ok=True)
                    _write_text_if_changed(fdir / "palettier.palette", palette_content)

        try:
            import gi

            gi.require_version("Gio", "2.0")
            from gi.repository import Gio

            ptyxis = Gio.Settings.new("org.gnome.Ptyxis")
            target_palette_id = "palettier"

            profile_uuids = set()
            default_uuid = ptyxis.get_string("default-profile-uuid")
            if default_uuid:
                profile_uuids.add(default_uuid)
            try:
                for u in ptyxis.get_strv("profile-uuids"):
                    profile_uuids.add(u)
            except Exception:
                pass

            for u in profile_uuids:
                try:
                    profile = Gio.Settings.new_with_path(
                        "org.gnome.Ptyxis.Profile",
                        f"/org/gnome/Ptyxis/Profiles/{u}/",
                    )
                    if profile.get_string("palette") != target_palette_id:
                        profile.set_string("palette", target_palette_id)
                except Exception:
                    pass
        except Exception:
            pass

        return True
    except Exception as e:
        print(f"[!] Error updating Ptyxis palette: {e}")
        return False


def get_firefox_profile_dirs(base_dirs: list[Path] | None = None) -> list[Path]:
    """Locate all active Firefox profile directories."""
    profiles: list[Path] = []
    search_dirs = base_dirs or [
        Path.home() / ".config" / "mozilla" / "firefox",
        Path.home() / ".mozilla" / "firefox",
    ]
    for bdir in search_dirs:
        if not bdir.exists():
            continue
        pini = bdir / "profiles.ini"
        if pini.exists():
            try:
                import configparser

                config = configparser.ConfigParser()
                config.read(pini)
                for sec in config.sections():
                    path = config.get(sec, "Path", fallback=None)
                    if path:
                        is_rel = config.get(sec, "IsRelative", fallback="1")
                        p_dir = bdir / path if is_rel == "1" else Path(path)
                        if p_dir.is_dir() and p_dir not in profiles:
                            profiles.append(p_dir)
            except Exception:
                pass
        for sub in bdir.iterdir():
            if sub.is_dir() and (sub / "prefs.js").exists() and sub not in profiles:
                profiles.append(sub)
    return profiles


def generate_firefox_userchrome_css(accent: str, tint: float) -> str:
    """Generate Firefox userChrome.css supporting horizontal tabs, sidebar, and vertical tabs."""
    r, g, b = hex_to_rgb(accent)
    bg_frame = mix("#0e1014", accent, tint * 0.8)
    bg_toolbar = mix("#15181e", accent, tint * 1.1)
    bg_tab_active = mix("#1d212a", accent, min(tint * 1.3, 0.25))
    bg_tab_hover = mix("#252a35", accent, tint * 1.1)
    bg_urlbar = mix("#0a0c0f", accent, tint * 0.7)
    accent_light = adjust_lightness(accent, 0.12)

    return f"""/* Palettier — Dynamic Firefox Theme (Extracted from Wallpaper) */
/* Automatically generated by Palettier — DO NOT EDIT MANUALLY */

:root {{
  /* Base & Accent Colors */
  --accent-color: {accent} !important;
  --accent-color-light: {accent_light} !important;
  --focus-outline-color: {accent} !important;

  /* Window Titlebar / Header */
  --lwt-accent-color: {bg_frame} !important;
  --lwt-accent-color-inactive: {bg_frame} !important;

  /* Navigation & Toolbars */
  --toolbar-bgcolor: {bg_toolbar} !important;
  --toolbar-color: #f4f6fa !important;

  /* Address Bar (URL Bar) */
  --toolbar-field-background-color: {bg_urlbar} !important;
  --toolbar-field-color: #f4f6fa !important;
  --toolbar-field-focus-background-color: {bg_urlbar} !important;
  --toolbar-field-focus-color: #ffffff !important;
  --toolbar-field-focus-border-color: {accent} !important;

  /* Tabs */
  --tab-selected-bgcolor: {bg_tab_active} !important;
  --tab-selected-textcolor: #ffffff !important;
  --lwt-selected-tab-background-color: {bg_tab_active} !important;
  --lwt-tab-line-color: {accent} !important;

  /* Sidebar & Vertical Tabs */
  --lwt-sidebar-background-color: {bg_frame} !important;
  --lwt-sidebar-text-color: #f4f6fa !important;
  --sidebar-background-color: {bg_frame} !important;
  --sidebar-text-color: #f4f6fa !important;
}}

/* Top Toolbox & Tabs Area */
#navigator-toolbox {{
  background-color: {bg_frame} !important;
  border-bottom: 1px solid rgba(255, 255, 255, 0.06) !important;
}}

#TabsToolbar {{
  background-color: {bg_frame} !important;
}}

/* Navigation Bar */
#nav-bar {{
  background-color: {bg_toolbar} !important;
  box-shadow: none !important;
}}

/* Bookmarks Toolbar */
#PersonalToolbar {{
  background-color: {bg_toolbar} !important;
  color: #f4f6fa !important;
}}

/* URL Bar */
#urlbar-background {{
  background-color: {bg_urlbar} !important;
  border: 1px solid rgba(255, 255, 255, 0.08) !important;
  border-radius: 8px !important;
}}

#urlbar[focused="true"] > #urlbar-background {{
  border-color: {accent} !important;
  box-shadow: 0 0 0 2px rgba({r}, {g}, {b}, 0.25) !important;
}}

/* Active Tabs (Horizontal & Vertical) */
.tabbrowser-tab[selected] .tab-background {{
  background-color: {bg_tab_active} !important;
  border-radius: 8px !important;
  box-shadow: inset 0 0 0 1px rgba({r}, {g}, {b}, 0.35) !important;
}}

/* Active Tab Line Indicator */
.tab-line[selected="true"] {{
  background-color: {accent} !important;
}}

/* Hovered Tabs */
.tabbrowser-tab:hover:not([selected]) .tab-background {{
  background-color: {bg_tab_hover} !important;
  border-radius: 8px !important;
}}

/* Toolbar Buttons Hover */
toolbarbutton.bookmark-item:hover,
.toolbarbutton-1:hover {{
  background-color: rgba({r}, {g}, {b}, 0.15) !important;
}}

/* Sidebar & Vertical Tabs Support */
#sidebar-box,
#sidebar-main,
#vertical-tabs {{
  background-color: {bg_frame} !important;
  border-right: 1px solid rgba(255, 255, 255, 0.06) !important;
}}

#vertical-tabs .tabbrowser-tab[selected] .tab-background {{
  box-shadow: inset 3px 0 0 0 {accent} !important;
}}
"""


def update_firefox_theme(
    accent: str,
    tint: float,
    profile_dirs: list[Path] | None = None,
    reference_path: Path | None = None,
) -> bool:
    """Update userChrome.css and user.js across all Firefox profiles."""
    dirs = profile_dirs if profile_dirs is not None else get_firefox_profile_dirs()
    if not dirs:
        return False

    css_content = generate_firefox_userchrome_css(accent, tint)
    success = False

    ref = reference_path or FIREFOX_THEME
    if ref and ref.parent.is_dir() and os.access(ref.parent, os.W_OK):
        try:
            _write_text_if_changed(ref, css_content)
        except Exception as e:
            print(f"[!] Error saving local reference copy {ref}: {e}")

    for pdir in dirs:
        try:
            user_js = pdir / "user.js"
            pref_line = 'user_pref("toolkit.legacyUserProfileCustomizations.stylesheets", true);'
            if user_js.exists():
                txt = user_js.read_text(encoding="utf-8")
                if "toolkit.legacyUserProfileCustomizations.stylesheets" not in txt:
                    user_js.write_text(txt.rstrip() + "\n" + pref_line + "\n", encoding="utf-8")
            else:
                user_js.write_text(pref_line + "\n", encoding="utf-8")

            chrome_dir = pdir / "chrome"
            chrome_dir.mkdir(parents=True, exist_ok=True)
            _write_text_if_changed(chrome_dir / "userChrome.css", css_content)
            success = True
        except Exception as e:
            print(f"[!] Error updating Firefox in {pdir}: {e}")

    return success
