"""
palettier.sync — Idempotent orchestration of all desktop theme targets.
"""

from __future__ import annotations

import os
from pathlib import Path

from palettier.config import PalettierConfig, load_config, normalize_hex_color
from palettier.icons import VALID_ICON_MODES, sync_m3_icon_pack
from palettier.palette import build_m3_scheme, map_hex_to_gnome_accent
from palettier.state import (
    collect_current_state,
    compute_file_sha256,
    is_state_unchanged,
    load_saved_state,
    save_state,
    wait_for_package_transaction,
)
from palettier.targets import (
    remove_gtk_theme,
    revert_flatpak_gtk_overrides,
    sync_flatpak_gtk_overrides,
    sync_gnome_accent_color,
    update_firefox_theme,
    update_gtk_theme,
    update_ptyxis_theme,
    update_starship_theme,
)
from palettier.wallpaper import extract_wallpaper_colors, gsettings_get, gsettings_set


def _resolve_effective_icon_mode(icon_mode: str | None, config: PalettierConfig) -> str:
    if icon_mode in VALID_ICON_MODES:
        return icon_mode
    env_mode = os.environ.get("PALETTIER_ICON_MODE", "").strip().lower()
    if env_mode in VALID_ICON_MODES:
        return env_mode
    if not config.targets.get("icons", True):
        return "off"
    return config.icon_mode if config.icon_mode in VALID_ICON_MODES else "system"


def _resolve_effective_icon_tint(icon_tint: float | None, config: PalettierConfig) -> float:
    if icon_tint is not None:
        return max(0.0, min(1.0, float(icon_tint)))
    raw_env = os.environ.get("PALETTIER_ICON_TINT", "").strip()
    if raw_env:
        try:
            return max(0.0, min(1.0, float(raw_env)))
        except ValueError:
            pass
    return config.icon_tint


def update_theme(
    wallpaper_path: Path | str | None = None,
    custom_accent: str | None = None,
    custom_tint: float | None = None,
    force: bool = False,
    icon_mode: str | None = None,
    icon_tint: float | None = None,
    config: PalettierConfig | None = None,
) -> bool:
    """
    Synchronize all enabled desktop themes idempotently:
    1. Wait for any active DNF/RPM package transaction to complete.
    2. Load user preferences from config.json and apply CLI/env overrides.
    3. Validate current state (wallpaper SHA-256 + `gsettings get` + config fingerprint)
       against `$XDG_RUNTIME_DIR/palettier.state` and skip redundant events.
    4. Apply required updates and persist the new state.
    """
    if not wait_for_package_transaction():
        return False

    cfg = config or load_config()
    effective_icon_mode = _resolve_effective_icon_mode(icon_mode, cfg)
    effective_icon_tint = _resolve_effective_icon_tint(icon_tint, cfg)
    effective_accent_override = normalize_hex_color(custom_accent) if custom_accent else cfg.accent_override
    effective_surface_tint = custom_tint if custom_tint is not None else cfg.surface_tint
    cfg_fingerprint = cfg.fingerprint()

    is_desktop_sync = (
        wallpaper_path is None
        and custom_accent is None
        and custom_tint is None
    )
    current_state = collect_current_state(wallpaper_path=wallpaper_path)

    if is_desktop_sync and not force:
        saved_state = load_saved_state()
        if is_state_unchanged(
            current_state,
            saved_state,
            icon_mode=effective_icon_mode,
            config_fingerprint=cfg_fingerprint,
        ):
            sha_preview = (current_state.get("wallpaper_sha256") or "")[:12]
            print(
                f"[=] State unchanged (color-scheme={current_state.get('color_scheme')}, "
                f"sha256={sha_preview}). Event skipped."
            )
            return False

    if effective_accent_override:
        accent = effective_accent_override
        tint = effective_surface_tint if effective_surface_tint is not None else 0.10
        active_wp = (
            Path(wallpaper_path)
            if wallpaper_path
            else (Path(current_state["wallpaper_path"]) if current_state.get("wallpaper_path") else None)
        )
    else:
        effective_wp_arg = wallpaper_path or current_state.get("wallpaper_path")
        accent, tint, active_wp = extract_wallpaper_colors(
            effective_wp_arg,
            forced_tint=effective_surface_tint,
        )

    if not accent:
        print("[!] No valid color could be extracted.")
        return False

    updated_files: list[str] = []
    is_dark = "dark" in (current_state.get("color_scheme") or "prefer-dark").lower()
    gtk_scheme = build_m3_scheme(accent, is_dark=is_dark)

    if cfg.targets.get("starship", True) and update_starship_theme(accent, tint):
        updated_files.append("Terminal Prompt (starship.toml)")

    if cfg.targets.get("ptyxis", True) and update_ptyxis_theme(accent, tint):
        updated_files.append("Terminal Emulator (Ptyxis palettier.palette)")

    if cfg.targets.get("firefox", True) and update_firefox_theme(accent, tint):
        updated_files.append("Firefox Browser (userChrome.css)")

    if cfg.targets.get("gnome_accent", True) and sync_gnome_accent_color(accent):
        updated_files.append(f"GNOME Desktop Native Accent ({map_hex_to_gnome_accent(accent)})")

    if cfg.targets.get("gtk", True):
        if update_gtk_theme(accent, tint, is_dark=is_dark, scheme=gtk_scheme):
            updated_files.append("GTK 3 & 4 Apps (palettier.css)")
        if cfg.targets.get("gtk_flatpak", True):
            if sync_flatpak_gtk_overrides():
                updated_files.append("Flatpak GTK Override (gtk-3.0/gtk-4.0:ro)")
        elif revert_flatpak_gtk_overrides():
            updated_files.append("Flatpak GTK Override (reverted)")
    elif remove_gtk_theme(revert_flatpak=True):
        updated_files.append("GTK 3 & 4 Apps (removed)")

    icons_updated, icon_m3_scheme, active_icon_slot = sync_m3_icon_pack(
        accent_hex=accent,
        is_dark=is_dark,
        mode=effective_icon_mode,
        gsettings_get_fn=gsettings_get,
        gsettings_set_fn=gsettings_set,
        tint_strength=effective_icon_tint,
    )
    m3_scheme = icon_m3_scheme or gtk_scheme
    if icons_updated and active_icon_slot:
        updated_files.append(f"Material 3 Icon Pack ({active_icon_slot}, mode={effective_icon_mode})")

    if is_desktop_sync:
        state_payload = {
            "wallpaper_sha256": current_state.get("wallpaper_sha256") or compute_file_sha256(active_wp),
            "color_scheme": current_state.get("color_scheme"),
            "accent_color": accent,
            "icon_mode": effective_icon_mode,
            "icon_tint": effective_icon_tint,
            "icon_theme": active_icon_slot,
            "config_fingerprint": cfg_fingerprint,
            "m3_primary": m3_scheme.get("primary"),
            "picture_uri": current_state.get("picture_uri"),
            "picture_uri_dark": current_state.get("picture_uri_dark"),
            "wallpaper_path": str(active_wp) if active_wp else current_state.get("wallpaper_path"),
        }
        save_state(state_payload)

    if updated_files:
        print("[✓] Themes synchronized successfully!")
        if active_wp:
            print(f"    - Wallpaper:       {active_wp}")
        print(f"    - Accent Color:    {accent} (M3 Primary: {m3_scheme.get('primary')})")
        print(f"    - Tint Intensity:  {tint * 100:.1f}%")
        for fname in updated_files:
            print(f"    - Updated:         {fname}")
        return True

    return False
