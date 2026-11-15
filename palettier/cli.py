"""
palettier.cli — Command-line interface for Palettier.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from palettier import __version__
from palettier.config import TARGET_KEYS, get_config_path, load_config, normalize_hex_color
from palettier.gui import main as gui_main
from palettier.icons import get_default_icon_mode, get_icon_tint_strength, render_html_preview, VALID_ICON_MODES
from palettier.palette import build_m3_scheme, map_hex_to_gnome_accent
from palettier.service import install_user_service, uninstall_all, uninstall_user_service
from palettier.sync import update_theme
from palettier.wallpaper import (
    extract_wallpaper_candidates,
    extract_wallpaper_colors,
    get_current_wallpaper_path,
    gsettings_get,
)
from palettier.watch import watch_mode


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="palettier",
        description="Palettier — Synchronize desktop themes and Material Design 3 icons from your wallpaper.",
    )
    parser.add_argument(
        "--version",
        "-V",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    parser.add_argument(
        "--gui",
        "-g",
        action="store_true",
        help="Open the graphical settings interface (GTK 4 / Libadwaita or local Web UI fallback).",
    )
    parser.add_argument(
        "--web-ui",
        action="store_true",
        help="Open the local Web Settings UI directly in your browser.",
    )
    parser.add_argument(
        "--no-browser",
        action="store_true",
        help="Do not automatically open a browser window when launching --web-ui.",
    )
    parser.add_argument(
        "--watch",
        "-w",
        action="store_true",
        help="Monitor wallpaper and color-scheme changes in real time.",
    )
    parser.add_argument(
        "--image",
        "-i",
        type=str,
        default=None,
        help="Path to a specific wallpaper image file.",
    )
    parser.add_argument(
        "--accent",
        "-a",
        type=str,
        default=None,
        help="Override the extracted accent color (#HEX).",
    )
    parser.add_argument(
        "--tint",
        "-t",
        type=float,
        default=None,
        help="Override surface tint intensity (e.g., 0.10).",
    )
    parser.add_argument(
        "--force",
        "-f",
        action="store_true",
        help="Force theme reapplication even when cached state is unchanged.",
    )
    parser.add_argument(
        "--icon-mode",
        choices=VALID_ICON_MODES,
        default=None,
        help="M3 icon pack mode: system/full (default: M3 places + tinted app icons), places, squircle, or off.",
    )
    parser.add_argument(
        "--icon-tint",
        type=float,
        default=None,
        help="Material Design 3 tonal filter strength for app icons (0.0 to 1.0, default: 0.90).",
    )
    parser.add_argument(
        "--no-icons",
        action="store_true",
        help="Disable Material Design 3 icon pack generation (shortcut for --icon-mode off).",
    )
    parser.add_argument(
        "--preview-icons",
        nargs="?",
        const="icons-preview.html",
        default=None,
        help="Generate an HTML preview page for the M3 palette and icon pack.",
    )
    parser.add_argument(
        "--install-service",
        action="store_true",
        help="Install and configure the systemd --user service.",
    )
    parser.add_argument(
        "--uninstall-service",
        action="store_true",
        help="Stop, disable, and remove the systemd --user service.",
    )
    parser.add_argument(
        "--uninstall",
        action="store_true",
        help="Complete uninstallation: remove service, themes, palettes, and restore defaults.",
    )
    parser.add_argument(
        "--info",
        action="store_true",
        help="Display detected wallpaper, configuration, accent color, and Material Design 3 palette details.",
    )
    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)

    cfg = load_config()
    resolved_icon_mode = "off" if args.no_icons else args.icon_mode
    effective_icon_mode = (
        resolved_icon_mode
        or (os.environ.get("PALETTIER_ICON_MODE", "").strip().lower() in VALID_ICON_MODES and os.environ["PALETTIER_ICON_MODE"].strip().lower())
        or (cfg.icon_mode if cfg.targets.get("icons", True) else "off")
        or get_default_icon_mode()
    )
    effective_icon_tint = (
        max(0.0, min(1.0, args.icon_tint))
        if args.icon_tint is not None
        else (get_icon_tint_strength() if os.environ.get("PALETTIER_ICON_TINT") else cfg.icon_tint)
    )
    effective_accent_arg = normalize_hex_color(args.accent) if args.accent else cfg.accent_override
    effective_tint_arg = args.tint if args.tint is not None else cfg.surface_tint

    if args.uninstall:
        uninstall_all()
    elif args.uninstall_service:
        uninstall_user_service()
    elif args.install_service:
        install_user_service()
    elif args.gui or args.web_ui:
        rc = gui_main(force_web_ui=bool(args.web_ui), open_browser=not args.no_browser)
        if rc:
            raise SystemExit(rc)
    elif args.preview_icons:
        wp = Path(args.image) if args.image else get_current_wallpaper_path()
        if effective_accent_arg:
            accent = effective_accent_arg
        else:
            accent, _, _ = extract_wallpaper_colors(wp, forced_tint=effective_tint_arg)
        color_scheme = gsettings_get("org.gnome.desktop.interface", "color-scheme")
        is_dark = "dark" in (color_scheme or "prefer-dark").lower()
        scheme = build_m3_scheme(accent, is_dark=is_dark)
        out_path = Path(args.preview_icons)
        out_path.write_text(
            render_html_preview(scheme, mode=effective_icon_mode, tint_strength=effective_icon_tint),
            encoding="utf-8",
        )
        print(f"[✓] Material Design 3 preview saved to: {out_path}")
    elif args.info:
        wp = Path(args.image) if args.image else get_current_wallpaper_path()
        candidates, extracted_tint, active_wp = extract_wallpaper_candidates(
            wp,
            forced_tint=effective_tint_arg,
            max_colors=6,
        )
        if effective_accent_arg:
            accent = effective_accent_arg
            tint = effective_tint_arg if effective_tint_arg is not None else extracted_tint
        else:
            accent = candidates[0]
            tint = extracted_tint
        gnome_acc = map_hex_to_gnome_accent(accent)
        color_scheme = gsettings_get("org.gnome.desktop.interface", "color-scheme")
        is_dark = "dark" in (color_scheme or "prefer-dark").lower()
        scheme = build_m3_scheme(accent, is_dark=is_dark)
        enabled_targets = [k for k in TARGET_KEYS if cfg.targets.get(k, True)]
        print("=== Palettier Info ===")
        print(f"Config file:         {get_config_path()}")
        print(f"Enabled targets:     {', '.join(enabled_targets) if enabled_targets else 'none'}")
        print(f"Detected wallpaper:  {active_wp}")
        print(f"Extracted colors:    {', '.join(candidates)}")
        print(f"Accent color:        {accent}")
        print(f"GNOME 47+ accent:    {gnome_acc}")
        print(f"Tint intensity:      {tint * 100:.1f}%")
        print(f"M3 icon mode:        {effective_icon_mode} (tint={effective_icon_tint:.2f}, {scheme['mode']})")
        print(f"M3 Primary:          {scheme['primary']} (OnPrimary: {scheme['onPrimary']})")
        print(f"M3 PrimaryContainer: {scheme['primaryContainer']} (OnContainer: {scheme['onPrimaryContainer']})")
        print(f"M3 Secondary:        {scheme['secondary']} | Tertiary: {scheme['tertiary']}")
        print(
            f"M3 Folder Tones:     back={scheme['iconFolderBack']}, "
            f"front={scheme['iconFolderFrontBottom']}, glyph={scheme['iconFolderGlyph']}"
        )
    elif args.watch:
        if resolved_icon_mode:
            os.environ["PALETTIER_ICON_MODE"] = resolved_icon_mode
        if args.icon_tint is not None:
            os.environ["PALETTIER_ICON_TINT"] = str(max(0.0, min(1.0, args.icon_tint)))
        watch_mode()
    else:
        update_theme(
            wallpaper_path=args.image,
            custom_accent=args.accent,
            custom_tint=args.tint,
            force=args.force,
            icon_mode=resolved_icon_mode,
            icon_tint=args.icon_tint,
        )
        print("\nTip: Open the graphical settings interface anytime with:")
        print("  palettier --gui")
        print("\nTo watch for wallpaper changes automatically, run:")
        print("  palettier --watch")
        print("\nTo install as a systemd user startup service:")
        print("  palettier --install-service")
        print("\nTo completely uninstall and restore application defaults:")
        print("  palettier --uninstall")
