"""
palettier.targets — Theme generators and updaters for Starship, Ptyxis, Firefox, GTK, and GNOME.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

from palettier.palette import adjust_lightness, build_m3_scheme, hex_to_rgb, map_hex_to_gnome_accent, mix
from palettier.wallpaper import gsettings_get, gsettings_set

STARSHIP_TOML = Path.home() / ".config" / "starship.toml"
PTYXIS_PALETTES_DIR = Path.home() / ".local" / "share" / "org.gnome.Ptyxis" / "palettes"


def get_firefox_reference_path() -> Path:
    """Return XDG state path for the generated Firefox userChrome.css reference copy."""
    xdg_state = os.environ.get("XDG_STATE_HOME")
    base = Path(xdg_state) if xdg_state else (Path.home() / ".local" / "state")
    return base / "palettier" / "firefox-userChrome.css"


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

    ref = reference_path or get_firefox_reference_path()
    if ref:
        try:
            ref.parent.mkdir(parents=True, exist_ok=True)
            _write_text_if_changed(ref, css_content)
        except Exception as e:
            print(f"[!] Error saving reference copy {ref}: {e}")

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


_GTK_BEGIN_MARKER = "/* BEGIN PALETTIER — Managed automatically by Palettier. Do not edit this block. */"
_GTK_END_MARKER = "/* END PALETTIER */"
_GTK_IMPORT_BLOCK = f'{_GTK_BEGIN_MARKER}\n@import url("palettier.css");\n{_GTK_END_MARKER}'
_GTK_BLOCK_RE = re.compile(
    r"\n?/\* BEGIN PALETTIER[^\n]*\*/[\s\S]*?/\* END PALETTIER \*/\n?",
    re.MULTILINE,
)
_FLATPAK_GTK_FILESYSTEMS = ("xdg-config/gtk-4.0:ro", "xdg-config/gtk-3.0:ro")


def get_gtk_config_dirs() -> tuple[Path, Path]:
    """Return XDG config directories for GTK 4 and GTK 3 (~/.config/gtk-4.0, gtk-3.0)."""
    xdg_config = os.environ.get("XDG_CONFIG_HOME")
    base = Path(xdg_config) if xdg_config else (Path.home() / ".config")
    return base / "gtk-4.0", base / "gtk-3.0"


def get_flatpak_gtk_marker_path() -> Path:
    """Return XDG state path tracking Flatpak overrides managed by Palettier."""
    xdg_state = os.environ.get("XDG_STATE_HOME")
    base = Path(xdg_state) if xdg_state else (Path.home() / ".local" / "state")
    return base / "palettier" / "flatpak-gtk-overrides.json"


def _get_flatpak_global_override_path() -> Path:
    xdg_data = os.environ.get("XDG_DATA_HOME")
    base = Path(xdg_data) if xdg_data else (Path.home() / ".local" / "share")
    return base / "flatpak" / "overrides" / "global"


def compute_gtk_palette_tokens(
    accent: str,
    tint: float,
    is_dark: bool = True,
    scheme: dict[str, str] | None = None,
) -> dict[str, str]:
    """
    Derive Material Design 3 accent and tinted surface tokens for GTK 3 and GTK 4 / Libadwaita.
    """
    m3 = scheme or build_m3_scheme(accent, is_dark=is_dark)
    clamped_tint = max(0.0, min(0.5, float(tint)))

    accent_bg = m3["primary"]
    accent_fg = m3["onPrimary"]
    accent_color = m3["primary"]
    destructive_bg = m3["error"]
    destructive_fg = m3["onError"]
    destructive_color = m3["error"]

    if is_dark:
        window_bg = mix(m3["surfaceContainerLow"], accent, min(clamped_tint * 0.45, 0.14))
        view_bg = mix(m3["surfaceContainerLowest"], accent, min(clamped_tint * 0.35, 0.10))
        headerbar_bg = mix(m3["surfaceContainer"], accent, min(clamped_tint * 0.55, 0.16))
        headerbar_backdrop = mix(m3["surfaceContainerLow"], accent, min(clamped_tint * 0.40, 0.12))
        sidebar_bg = mix(m3["surfaceContainer"], accent, min(clamped_tint * 0.50, 0.15))
        secondary_sidebar_bg = mix(m3["surfaceContainerLow"], accent, min(clamped_tint * 0.45, 0.14))
        card_bg = mix(m3["surfaceContainerHigh"], accent, min(clamped_tint * 0.45, 0.14))
        dialog_bg = mix(m3["surfaceContainerHigh"], accent, min(clamped_tint * 0.45, 0.14))
        popover_bg = mix(m3["surfaceContainerHigh"], accent, min(clamped_tint * 0.45, 0.14))
        headerbar_border = "rgba(255, 255, 255, 0.08)"
        sidebar_border = "rgba(255, 255, 255, 0.07)"
        shade_color = "rgba(0, 0, 0, 0.36)"
        card_shade = "rgba(0, 0, 0, 0.36)"
        scrollbar_outline = "rgba(0, 0, 0, 0.5)"
    else:
        window_bg = mix(m3["surface"], accent, min(clamped_tint * 0.25, 0.08))
        view_bg = mix(m3["surfaceContainerLowest"], accent, min(clamped_tint * 0.15, 0.05))
        headerbar_bg = mix(m3["surfaceContainerLow"], accent, min(clamped_tint * 0.30, 0.10))
        headerbar_backdrop = mix(m3["surface"], accent, min(clamped_tint * 0.22, 0.07))
        sidebar_bg = mix(m3["surfaceContainer"], accent, min(clamped_tint * 0.30, 0.10))
        secondary_sidebar_bg = mix(m3["surfaceContainerLow"], accent, min(clamped_tint * 0.25, 0.08))
        card_bg = mix(m3["surfaceContainerLowest"], accent, min(clamped_tint * 0.18, 0.06))
        dialog_bg = mix(m3["surfaceContainerLow"], accent, min(clamped_tint * 0.20, 0.07))
        popover_bg = mix(m3["surfaceContainerLowest"], accent, min(clamped_tint * 0.18, 0.06))
        headerbar_border = "rgba(0, 0, 0, 0.12)"
        sidebar_border = "rgba(0, 0, 0, 0.08)"
        shade_color = "rgba(0, 0, 0, 0.07)"
        card_shade = "rgba(0, 0, 0, 0.08)"
        scrollbar_outline = "rgba(255, 255, 255, 0.5)"

    fg = m3["onSurface"]
    fg_muted = m3["onSurfaceVariant"]
    border_hex = mix(m3["outlineVariant"], accent, min(clamped_tint * 0.30, 0.10))
    insensitive_bg = mix(window_bg, fg, 0.05)
    insensitive_fg = mix(fg, window_bg, 0.45)

    return {
        "mode": m3["mode"],
        "accent_color": accent_color,
        "accent_bg_color": accent_bg,
        "accent_fg_color": accent_fg,
        "destructive_color": destructive_color,
        "destructive_bg_color": destructive_bg,
        "destructive_fg_color": destructive_fg,
        "window_bg_color": window_bg,
        "window_fg_color": fg,
        "view_bg_color": view_bg,
        "view_fg_color": fg,
        "headerbar_bg_color": headerbar_bg,
        "headerbar_fg_color": fg,
        "headerbar_border_color": headerbar_border,
        "headerbar_backdrop_color": headerbar_backdrop,
        "headerbar_shade_color": shade_color,
        "sidebar_bg_color": sidebar_bg,
        "sidebar_fg_color": fg,
        "sidebar_backdrop_color": headerbar_backdrop,
        "sidebar_border_color": sidebar_border,
        "sidebar_shade_color": shade_color,
        "secondary_sidebar_bg_color": secondary_sidebar_bg,
        "secondary_sidebar_fg_color": fg,
        "secondary_sidebar_backdrop_color": window_bg,
        "secondary_sidebar_shade_color": shade_color,
        "card_bg_color": card_bg,
        "card_fg_color": fg,
        "card_shade_color": card_shade,
        "dialog_bg_color": dialog_bg,
        "dialog_fg_color": fg,
        "popover_bg_color": popover_bg,
        "popover_fg_color": fg,
        "popover_shade_color": shade_color,
        "thumbnail_bg_color": card_bg,
        "thumbnail_fg_color": fg,
        "shade_color": shade_color,
        "scrollbar_outline_color": scrollbar_outline,
        "border_hex": border_hex,
        "fg_muted": fg_muted,
        "insensitive_bg_color": insensitive_bg,
        "insensitive_fg_color": insensitive_fg,
    }


def generate_gtk4_css(
    accent: str,
    tint: float,
    is_dark: bool = True,
    scheme: dict[str, str] | None = None,
) -> str:
    """Generate Material Design 3 CSS for GTK 4 and Libadwaita (1.0 through 1.6+)."""
    t = compute_gtk_palette_tokens(accent, tint, is_dark=is_dark, scheme=scheme)
    return f"""/* Palettier — Dynamic GTK 4 / Libadwaita Material Design 3 Theme ({t['mode']}) */
/* Automatically generated by Palettier — DO NOT EDIT MANUALLY */

@define-color accent_color {t['accent_color']};
@define-color accent_bg_color {t['accent_bg_color']};
@define-color accent_fg_color {t['accent_fg_color']};

@define-color destructive_color {t['destructive_color']};
@define-color destructive_bg_color {t['destructive_bg_color']};
@define-color destructive_fg_color {t['destructive_fg_color']};

@define-color window_bg_color {t['window_bg_color']};
@define-color window_fg_color {t['window_fg_color']};
@define-color view_bg_color {t['view_bg_color']};
@define-color view_fg_color {t['view_fg_color']};

@define-color headerbar_bg_color {t['headerbar_bg_color']};
@define-color headerbar_fg_color {t['headerbar_fg_color']};
@define-color headerbar_border_color {t['headerbar_border_color']};
@define-color headerbar_backdrop_color {t['headerbar_backdrop_color']};
@define-color headerbar_shade_color {t['headerbar_shade_color']};

@define-color sidebar_bg_color {t['sidebar_bg_color']};
@define-color sidebar_fg_color {t['sidebar_fg_color']};
@define-color sidebar_backdrop_color {t['sidebar_backdrop_color']};
@define-color sidebar_border_color {t['sidebar_border_color']};
@define-color sidebar_shade_color {t['sidebar_shade_color']};

@define-color secondary_sidebar_bg_color {t['secondary_sidebar_bg_color']};
@define-color secondary_sidebar_fg_color {t['secondary_sidebar_fg_color']};
@define-color secondary_sidebar_backdrop_color {t['secondary_sidebar_backdrop_color']};
@define-color secondary_sidebar_shade_color {t['secondary_sidebar_shade_color']};

@define-color card_bg_color {t['card_bg_color']};
@define-color card_fg_color {t['card_fg_color']};
@define-color card_shade_color {t['card_shade_color']};

@define-color dialog_bg_color {t['dialog_bg_color']};
@define-color dialog_fg_color {t['dialog_fg_color']};

@define-color popover_bg_color {t['popover_bg_color']};
@define-color popover_fg_color {t['popover_fg_color']};
@define-color popover_shade_color {t['popover_shade_color']};

@define-color thumbnail_bg_color {t['thumbnail_bg_color']};
@define-color thumbnail_fg_color {t['thumbnail_fg_color']};
@define-color shade_color {t['shade_color']};
@define-color scrollbar_outline_color {t['scrollbar_outline_color']};

/* Libadwaita 1.6+ CSS custom properties */
:root {{
  --accent-color: {t['accent_color']};
  --accent-bg-color: {t['accent_bg_color']};
  --accent-fg-color: {t['accent_fg_color']};
  --destructive-color: {t['destructive_color']};
  --destructive-bg-color: {t['destructive_bg_color']};
  --destructive-fg-color: {t['destructive_fg_color']};
  --window-bg-color: {t['window_bg_color']};
  --window-fg-color: {t['window_fg_color']};
  --view-bg-color: {t['view_bg_color']};
  --view-fg-color: {t['view_fg_color']};
  --headerbar-bg-color: {t['headerbar_bg_color']};
  --headerbar-fg-color: {t['headerbar_fg_color']};
  --headerbar-border-color: {t['headerbar_border_color']};
  --headerbar-backdrop-color: {t['headerbar_backdrop_color']};
  --sidebar-bg-color: {t['sidebar_bg_color']};
  --sidebar-fg-color: {t['sidebar_fg_color']};
  --sidebar-backdrop-color: {t['sidebar_backdrop_color']};
  --sidebar-border-color: {t['sidebar_border_color']};
  --secondary-sidebar-bg-color: {t['secondary_sidebar_bg_color']};
  --secondary-sidebar-fg-color: {t['secondary_sidebar_fg_color']};
  --card-bg-color: {t['card_bg_color']};
  --card-fg-color: {t['card_fg_color']};
  --dialog-bg-color: {t['dialog_bg_color']};
  --dialog-fg-color: {t['dialog_fg_color']};
  --popover-bg-color: {t['popover_bg_color']};
  --popover-fg-color: {t['popover_fg_color']};
  --thumbnail-bg-color: {t['thumbnail_bg_color']};
  --thumbnail-fg-color: {t['thumbnail_fg_color']};
}}
"""


def generate_gtk3_css(
    accent: str,
    tint: float,
    is_dark: bool = True,
    scheme: dict[str, str] | None = None,
) -> str:
    """Generate Material Design 3 CSS for GTK 3 (adw-gtk3 and standard Adwaita themes)."""
    t = compute_gtk_palette_tokens(accent, tint, is_dark=is_dark, scheme=scheme)
    return f"""/* Palettier — Dynamic GTK 3 Material Design 3 Theme ({t['mode']}) */
/* Automatically generated by Palettier — DO NOT EDIT MANUALLY */

@define-color accent_color {t['accent_color']};
@define-color accent_bg_color {t['accent_bg_color']};
@define-color accent_fg_color {t['accent_fg_color']};

@define-color destructive_color {t['destructive_color']};
@define-color destructive_bg_color {t['destructive_bg_color']};
@define-color destructive_fg_color {t['destructive_fg_color']};

@define-color window_bg_color {t['window_bg_color']};
@define-color window_fg_color {t['window_fg_color']};
@define-color view_bg_color {t['view_bg_color']};
@define-color view_fg_color {t['view_fg_color']};

@define-color headerbar_bg_color {t['headerbar_bg_color']};
@define-color headerbar_fg_color {t['headerbar_fg_color']};
@define-color headerbar_border_color {t['headerbar_border_color']};
@define-color headerbar_backdrop_color {t['headerbar_backdrop_color']};
@define-color headerbar_shade_color {t['headerbar_shade_color']};

@define-color sidebar_bg_color {t['sidebar_bg_color']};
@define-color sidebar_fg_color {t['sidebar_fg_color']};
@define-color sidebar_backdrop_color {t['sidebar_backdrop_color']};
@define-color sidebar_border_color {t['sidebar_border_color']};
@define-color sidebar_shade_color {t['sidebar_shade_color']};

@define-color secondary_sidebar_bg_color {t['secondary_sidebar_bg_color']};
@define-color secondary_sidebar_fg_color {t['secondary_sidebar_fg_color']};
@define-color secondary_sidebar_backdrop_color {t['secondary_sidebar_backdrop_color']};
@define-color secondary_sidebar_shade_color {t['secondary_sidebar_shade_color']};

@define-color card_bg_color {t['card_bg_color']};
@define-color card_fg_color {t['card_fg_color']};
@define-color card_shade_color {t['card_shade_color']};

@define-color dialog_bg_color {t['dialog_bg_color']};
@define-color dialog_fg_color {t['dialog_fg_color']};

@define-color popover_bg_color {t['popover_bg_color']};
@define-color popover_fg_color {t['popover_fg_color']};
@define-color popover_shade_color {t['popover_shade_color']};

@define-color thumbnail_bg_color {t['thumbnail_bg_color']};
@define-color thumbnail_fg_color {t['thumbnail_fg_color']};
@define-color shade_color {t['shade_color']};
@define-color scrollbar_outline_color {t['scrollbar_outline_color']};

/* Standard GTK 3 theme color aliases */
@define-color theme_bg_color {t['window_bg_color']};
@define-color theme_fg_color {t['window_fg_color']};
@define-color theme_base_color {t['view_bg_color']};
@define-color theme_text_color {t['view_fg_color']};
@define-color theme_selected_bg_color {t['accent_bg_color']};
@define-color theme_selected_fg_color {t['accent_fg_color']};
@define-color theme_unfocused_bg_color {t['headerbar_backdrop_color']};
@define-color theme_unfocused_fg_color {t['fg_muted']};
@define-color theme_unfocused_base_color {t['view_bg_color']};
@define-color theme_unfocused_text_color {t['view_fg_color']};
@define-color theme_unfocused_selected_bg_color {t['accent_bg_color']};
@define-color theme_unfocused_selected_fg_color {t['accent_fg_color']};
@define-color borders {t['border_hex']};
@define-color unfocused_borders {t['border_hex']};
@define-color insensitive_bg_color {t['insensitive_bg_color']};
@define-color insensitive_fg_color {t['insensitive_fg_color']};
@define-color insensitive_base_color {t['view_bg_color']};
"""


def _ensure_managed_gtk_import(gtk_css: Path) -> bool:
    """Ensure `gtk.css` imports `palettier.css` at the top while preserving user rules."""
    gtk_css.parent.mkdir(parents=True, exist_ok=True)
    if not gtk_css.exists():
        gtk_css.write_text(_GTK_IMPORT_BLOCK + "\n", encoding="utf-8")
        return True

    existing = gtk_css.read_text(encoding="utf-8")
    if _GTK_BEGIN_MARKER in existing and _GTK_END_MARKER in existing:
        stripped = _GTK_BLOCK_RE.sub("", existing).lstrip("\n")
    else:
        stripped = existing.lstrip("\n")

    new_content = _GTK_IMPORT_BLOCK + ("\n\n" + stripped if stripped.strip() else "\n")
    if new_content == existing:
        return False
    gtk_css.write_text(new_content, encoding="utf-8")
    return True


def _strip_managed_gtk_import(gtk_css: Path) -> bool:
    """Remove Palettier's managed import block from `gtk.css`, preserving user rules."""
    if not gtk_css.exists():
        return False
    existing = gtk_css.read_text(encoding="utf-8")
    if _GTK_BEGIN_MARKER not in existing:
        return False
    cleaned = _GTK_BLOCK_RE.sub("\n", existing).strip()
    if not cleaned:
        gtk_css.unlink(missing_ok=True)
        return True
    new_content = cleaned + "\n"
    if new_content != existing:
        gtk_css.write_text(new_content, encoding="utf-8")
        return True
    return False


def _parse_flatpak_filesystems(show_output: str) -> set[str]:
    entries: set[str] = set()
    for line in show_output.splitlines():
        stripped = line.strip()
        if stripped.startswith("filesystems="):
            raw = stripped.split("=", 1)[1]
            for item in raw.split(";"):
                token = item.strip()
                if token:
                    entries.add(token)
    return entries


def _is_flatpak_fs_covered(existing: set[str], target_fs: str) -> bool:
    base = target_fs.split(":", 1)[0]
    return target_fs in existing or base in existing or f"{base}:rw" in existing


def sync_flatpak_gtk_overrides(marker_path: Path | None = None) -> bool:
    """
    Grant read-only Flatpak access to `xdg-config/gtk-4.0` and `xdg-config/gtk-3.0`
    idempotently, recording only entries added by Palettier for clean reversal.
    """
    flatpak_bin = shutil.which("flatpak")
    if not flatpak_bin:
        return False

    try:
        res = subprocess.run(
            [flatpak_bin, "override", "--user", "--show"],
            capture_output=True,
            text=True,
            check=False,
            timeout=3,
        )
        existing_fs = _parse_flatpak_filesystems(res.stdout) if res.returncode == 0 else set()
    except Exception:
        return False

    missing = [fs for fs in _FLATPAK_GTK_FILESYSTEMS if not _is_flatpak_fs_covered(existing_fs, fs)]
    if not missing:
        return False

    added: list[str] = []
    for fs in missing:
        try:
            ov_res = subprocess.run(
                [flatpak_bin, "override", "--user", f"--filesystem={fs}"],
                capture_output=True,
                text=True,
                check=False,
                timeout=3,
            )
            if ov_res.returncode == 0:
                added.append(fs)
        except Exception:
            pass

    if not added:
        return False

    mpath = marker_path or get_flatpak_gtk_marker_path()
    try:
        prev: list[str] = []
        if mpath.is_file():
            data = json.loads(mpath.read_text(encoding="utf-8"))
            if isinstance(data, dict) and isinstance(data.get("added_filesystems"), list):
                prev = [str(x) for x in data["added_filesystems"]]
        merged = sorted(set(prev) | set(added))
        mpath.parent.mkdir(parents=True, exist_ok=True)
        mpath.write_text(json.dumps({"added_filesystems": merged}, indent=2) + "\n", encoding="utf-8")
    except Exception:
        pass
    return True


def revert_flatpak_gtk_overrides(
    marker_path: Path | None = None,
    global_override_path: Path | None = None,
) -> bool:
    """Revert only the Flatpak global GTK filesystem overrides previously added by Palettier."""
    mpath = marker_path or get_flatpak_gtk_marker_path()
    if not mpath.is_file():
        return False

    try:
        data = json.loads(mpath.read_text(encoding="utf-8"))
        managed = [str(x) for x in data.get("added_filesystems", [])] if isinstance(data, dict) else []
    except Exception:
        managed = []

    reverted = False
    if managed:
        override_file = global_override_path or _get_flatpak_global_override_path()
        removed_via_file = False
        if override_file.is_file():
            try:
                import configparser

                cp = configparser.ConfigParser()
                cp.optionxform = str  # preserve case
                cp.read(override_file, encoding="utf-8")
                if cp.has_option("Context", "filesystems"):
                    raw = cp.get("Context", "filesystems")
                    items = [i.strip() for i in raw.split(";") if i.strip()]
                    new_items = [i for i in items if i not in managed]
                    if len(new_items) != len(items):
                        reverted = True
                    if new_items:
                        cp.set("Context", "filesystems", ";".join(new_items) + ";")
                    else:
                        cp.remove_option("Context", "filesystems")
                        if not cp.options("Context"):
                            cp.remove_section("Context")
                    if cp.sections():
                        with override_file.open("w", encoding="utf-8") as f:
                            cp.write(f, space_around_delimiters=False)
                    else:
                        override_file.unlink(missing_ok=True)
                    removed_via_file = True
            except Exception:
                removed_via_file = False

        if not removed_via_file:
            flatpak_bin = shutil.which("flatpak")
            if flatpak_bin:
                for fs in managed:
                    base = fs.split(":", 1)[0]
                    try:
                        res = subprocess.run(
                            [flatpak_bin, "override", "--user", f"--nofilesystem={base}"],
                            capture_output=True,
                            text=True,
                            check=False,
                            timeout=3,
                        )
                        if res.returncode == 0:
                            reverted = True
                    except Exception:
                        pass

    try:
        mpath.unlink(missing_ok=True)
        if mpath.parent.is_dir() and not any(mpath.parent.iterdir()):
            mpath.parent.rmdir()
    except OSError:
        pass
    return reverted


def update_gtk_theme(
    accent: str,
    tint: float,
    is_dark: bool = True,
    scheme: dict[str, str] | None = None,
    gtk4_dir: Path | None = None,
    gtk3_dir: Path | None = None,
) -> bool:
    """Write Material Design 3 `palettier.css` and non-destructive imports for GTK 4 and GTK 3."""
    try:
        default_gtk4, default_gtk3 = get_gtk_config_dirs()
        dir4 = gtk4_dir or default_gtk4
        dir3 = gtk3_dir or default_gtk3
        dir4.mkdir(parents=True, exist_ok=True)
        dir3.mkdir(parents=True, exist_ok=True)

        m3 = scheme or build_m3_scheme(accent, is_dark=is_dark)
        css4 = generate_gtk4_css(accent, tint, is_dark=is_dark, scheme=m3)
        css3 = generate_gtk3_css(accent, tint, is_dark=is_dark, scheme=m3)

        _write_text_if_changed(dir4 / "palettier.css", css4)
        _ensure_managed_gtk_import(dir4 / "gtk.css")
        _write_text_if_changed(dir3 / "palettier.css", css3)
        _ensure_managed_gtk_import(dir3 / "gtk.css")
        return True
    except Exception as e:
        print(f"[!] Error updating GTK themes: {e}")
        return False


def remove_gtk_theme(
    gtk4_dir: Path | None = None,
    gtk3_dir: Path | None = None,
    revert_flatpak: bool = True,
    marker_path: Path | None = None,
    global_override_path: Path | None = None,
) -> list[Path]:
    """Remove Palettier-managed GTK CSS files/imports and optionally revert Flatpak overrides."""
    default_gtk4, default_gtk3 = get_gtk_config_dirs()
    dir4 = gtk4_dir or default_gtk4
    dir3 = gtk3_dir or default_gtk3
    removed: list[Path] = []

    for gdir in (dir4, dir3):
        pal_css = gdir / "palettier.css"
        if pal_css.exists() or pal_css.is_symlink():
            try:
                pal_css.unlink(missing_ok=True)
                removed.append(pal_css)
            except OSError:
                pass
        gtk_css = gdir / "gtk.css"
        if _strip_managed_gtk_import(gtk_css):
            removed.append(gtk_css)

    if revert_flatpak:
        revert_flatpak_gtk_overrides(
            marker_path=marker_path,
            global_override_path=global_override_path,
        )

    return removed

