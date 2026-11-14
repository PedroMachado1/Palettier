"""
palettier.sync — Idempotent orchestration of all desktop theme targets.
"""

from __future__ import annotations

from pathlib import Path

from palettier.icons import VALID_ICON_MODES, get_default_icon_mode, sync_m3_icon_pack
from palettier.palette import map_hex_to_gnome_accent
from palettier.state import (
    collect_current_state,
    compute_file_sha256,
    is_state_unchanged,
    load_saved_state,
    save_state,
    wait_for_package_transaction,
)
from palettier.targets import (
    sync_gnome_accent_color,
    update_firefox_theme,
    update_ptyxis_theme,
    update_starship_theme,
)
from palettier.wallpaper import extract_wallpaper_colors, gsettings_get, gsettings_set


def update_theme(
    wallpaper_path: Path | str | None = None,
    custom_accent: str | None = None,
    custom_tint: float | None = None,
    force: bool = False,
    icon_mode: str | None = None,
) -> bool:
    """
    Synchronize all desktop themes idempotently:
    1. Wait for any active DNF/RPM package transaction to complete.
    2. Validate current state (wallpaper SHA-256 + `gsettings get`) against
       `$XDG_RUNTIME_DIR/palettier.state` and skip redundant events.
    3. Apply required updates and persist the new state.
    """
    if not wait_for_package_transaction():
        return False

    effective_icon_mode = icon_mode if icon_mode in VALID_ICON_MODES else get_default_icon_mode()

    is_desktop_sync = (
        wallpaper_path is None
        and custom_accent is None
        and custom_tint is None
    )
    current_state = collect_current_state(wallpaper_path=wallpaper_path)

    if is_desktop_sync and not force:
        saved_state = load_saved_state()
        if is_state_unchanged(current_state, saved_state, icon_mode=effective_icon_mode):
            sha_preview = (current_state.get("wallpaper_sha256") or "")[:12]
            print(
                f"[=] State unchanged (color-scheme={current_state.get('color_scheme')}, "
                f"sha256={sha_preview}). Event skipped."
            )
            return False

    if custom_accent:
        accent = custom_accent.lower()
        tint = custom_tint if custom_tint is not None else 0.10
        active_wp = (
            Path(wallpaper_path)
            if wallpaper_path
            else (Path(current_state["wallpaper_path"]) if current_state.get("wallpaper_path") else None)
        )
    else:
        effective_wp_arg = wallpaper_path or current_state.get("wallpaper_path")
        accent, tint, active_wp = extract_wallpaper_colors(effective_wp_arg, forced_tint=custom_tint)

    if not accent:
        print("[!] No valid color could be extracted.")
        return False

    updated_files: list[str] = []

    if update_starship_theme(accent, tint):
        updated_files.append("Terminal Prompt (starship.toml)")

    if update_ptyxis_theme(accent, tint):
        updated_files.append("Terminal Emulator (Ptyxis palettier.palette)")

    if update_firefox_theme(accent, tint):
        updated_files.append("Firefox Browser (userChrome.css)")

    if sync_gnome_accent_color(accent):
        updated_files.append(f"GNOME Desktop Native Accent ({map_hex_to_gnome_accent(accent)})")

    is_dark = "dark" in (current_state.get("color_scheme") or "prefer-dark").lower()
    icons_updated, m3_scheme, active_icon_slot = sync_m3_icon_pack(
        accent_hex=accent,
        is_dark=is_dark,
        mode=effective_icon_mode,
        gsettings_get_fn=gsettings_get,
        gsettings_set_fn=gsettings_set,
    )
    if icons_updated and active_icon_slot:
        updated_files.append(f"Material 3 Icon Pack ({active_icon_slot}, mode={effective_icon_mode})")

    if is_desktop_sync:
        state_payload = {
            "wallpaper_sha256": current_state.get("wallpaper_sha256") or compute_file_sha256(active_wp),
            "color_scheme": current_state.get("color_scheme"),
            "accent_color": accent,
            "icon_mode": effective_icon_mode,
            "icon_theme": active_icon_slot,
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
