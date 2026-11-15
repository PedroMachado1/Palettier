"""
palettier.service — Systemd user service management and complete uninstallation.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

from palettier.icons import uninstall_m3_icon_pack
from palettier.state import get_state_file_path
from palettier.targets import (
    STARSHIP_TOML,
    get_firefox_profile_dirs,
    get_firefox_reference_path,
    get_ptyxis_palette_paths,
    remove_gtk_theme,
)
from palettier.wallpaper import gsettings_get, gsettings_set

SERVICE_NAME = "palettier.service"
_REPO_ROOT = Path(__file__).resolve().parent.parent


def _get_systemd_user_dir() -> Path:
    xdg_config = os.environ.get("XDG_CONFIG_HOME")
    base = Path(xdg_config) if xdg_config else (Path.home() / ".config")
    return base / "systemd" / "user"


def get_service_status(service_dir: Path | None = None) -> dict[str, bool]:
    """Return installation, enabled, and active status for palettier.service."""
    target_dir = service_dir or _get_systemd_user_dir()
    installed = (target_dir / SERVICE_NAME).is_file()
    enabled = False
    active = False

    if shutil.which("systemctl"):
        try:
            res_en = subprocess.run(
                ["systemctl", "--user", "is-enabled", SERVICE_NAME],
                capture_output=True,
                text=True,
                check=False,
                timeout=3,
            )
            enabled = res_en.returncode == 0 and res_en.stdout.strip() == "enabled"
        except Exception:
            pass
        try:
            res_act = subprocess.run(
                ["systemctl", "--user", "is-active", SERVICE_NAME],
                capture_output=True,
                text=True,
                check=False,
                timeout=3,
            )
            active = res_act.returncode == 0 and res_act.stdout.strip() == "active"
        except Exception:
            pass

    return {"installed": installed, "enabled": enabled, "active": active}


def set_service_enabled(enabled: bool, service_dir: Path | None = None) -> bool:
    """Enable/start or disable/stop palettier.service via systemctl --user."""
    if enabled:
        target_dir = service_dir or _get_systemd_user_dir()
        if not (target_dir / SERVICE_NAME).is_file():
            install_user_service(service_dir=target_dir)
        if not shutil.which("systemctl"):
            return False
        subprocess.run(["systemctl", "--user", "daemon-reload"], check=False, capture_output=True)
        res = subprocess.run(
            ["systemctl", "--user", "enable", "--now", SERVICE_NAME],
            check=False,
            capture_output=True,
        )
        return res.returncode == 0

    if not shutil.which("systemctl"):
        return False
    res_stop = subprocess.run(["systemctl", "--user", "stop", SERVICE_NAME], check=False, capture_output=True)
    res_dis = subprocess.run(["systemctl", "--user", "disable", SERVICE_NAME], check=False, capture_output=True)
    return res_stop.returncode == 0 or res_dis.returncode == 0


def install_user_service(service_dir: Path | None = None) -> Path:
    """Create the systemd --user unit file for automatic startup on login."""
    target_dir = service_dir or _get_systemd_user_dir()
    target_dir.mkdir(parents=True, exist_ok=True)
    service_file = target_dir / SERVICE_NAME

    python_exec = sys.executable
    env_pythonpath = ""
    if (_REPO_ROOT / "pyproject.toml").is_file() and (_REPO_ROOT / "palettier" / "__init__.py").is_file():
        env_pythonpath = f'Environment="PYTHONPATH={_REPO_ROOT}"\n'

    service_content = f"""[Unit]
Description=Palettier Theme Synchronizer (Terminal, Firefox, GNOME, Icons)
After=graphical-session.target
StartLimitIntervalSec=60
StartLimitBurst=3

[Service]
Type=simple
Environment=PYTHONUNBUFFERED=1
{env_pythonpath}ExecStart="{python_exec}" -u -m palettier --watch
Restart=on-failure
RestartSec=3

[Install]
WantedBy=default.target
"""
    service_file.write_text(service_content, encoding="utf-8")

    print(f"[✓] Service unit created at: {service_file}")
    if os.environ.get("PALETTIER_QUIET_SERVICE_HINT") != "1":
        print("\nTo enable and start the service now, run:")
        print("  systemctl --user daemon-reload")
        print(f"  systemctl --user enable --now {SERVICE_NAME}")
    return service_file


def uninstall_user_service(service_dir: Path | None = None) -> None:
    """Stop, disable, and remove the Palettier systemd --user service."""
    print("[*] Stopping and removing user systemd service...")
    if shutil.which("systemctl"):
        subprocess.run(["systemctl", "--user", "stop", SERVICE_NAME], check=False, capture_output=True)
        subprocess.run(["systemctl", "--user", "disable", SERVICE_NAME], check=False, capture_output=True)

    target_dir = service_dir or _get_systemd_user_dir()
    sfile = target_dir / SERVICE_NAME
    if sfile.exists() or sfile.is_symlink():
        try:
            sfile.unlink(missing_ok=True)
            print(f"  [✓] Removed: {sfile}")
        except Exception as e:
            print(f"  [!] Failed to remove {sfile}: {e}")

    if shutil.which("systemctl"):
        subprocess.run(["systemctl", "--user", "daemon-reload"], check=False, capture_output=True)
        subprocess.run(["systemctl", "--user", "reset-failed"], check=False, capture_output=True)
    print("[✓] Systemd service removed successfully.")


def uninstall_all(
    service_dir: Path | None = None,
    starship_toml: Path | None = None,
    palettes_dir: Path | None = None,
    firefox_profiles: list[Path] | None = None,
    state_file: Path | None = None,
    gtk4_dir: Path | None = None,
    gtk3_dir: Path | None = None,
) -> None:
    """
    Completely uninstall Palettier:
    1. Stop and remove the systemd user service.
    2. Remove generated Ptyxis palettes and restore profiles to 'gnome'.
    3. Remove Palettier palette sections from starship.toml.
    4. Remove dynamic userChrome.css from Firefox profiles and XDG state reference.
    5. Remove GTK 3/4 CSS themes and Flatpak overrides managed by Palettier.
    6. Remove Material Design 3 icon slots and restore the previous icon theme.
    """
    print("==================================================")
    print("       Palettier — Complete Uninstallation        ")
    print("==================================================")

    print("\n[1/6] Stopping and removing systemd service...")
    uninstall_user_service(service_dir=service_dir)

    try:
        (state_file or get_state_file_path()).unlink(missing_ok=True)
    except Exception:
        pass

    try:
        ref_css = get_firefox_reference_path()
        if ref_css.exists():
            ref_css.unlink(missing_ok=True)
        if ref_css.parent.is_dir() and not any(ref_css.parent.iterdir()):
            ref_css.parent.rmdir()
    except Exception:
        pass

    print("\n[2/6] Restoring Ptyxis terminal palettes...")
    for pf in get_ptyxis_palette_paths(palettes_dir=palettes_dir):
        if pf.exists() or pf.is_symlink():
            try:
                pf.unlink(missing_ok=True)
                print(f"  [✓] Removed palette: {pf}")
            except Exception as e:
                print(f"  [!] Failed to remove {pf}: {e}")

    try:
        import gi

        gi.require_version("Gio", "2.0")
        from gi.repository import Gio

        ptyxis = Gio.Settings.new("org.gnome.Ptyxis")
        default_uuid = ptyxis.get_string("default-profile-uuid")
        profile_uuids = {default_uuid} if default_uuid else set()
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
                if profile.get_string("palette") == "palettier":
                    profile.set_string("palette", "gnome")
                    print("  [✓] Restored Ptyxis profile palette to default 'gnome'")
            except Exception:
                pass
    except Exception:
        pass

    print("\n[3/6] Restoring ~/.config/starship.toml...")
    starship_path = starship_toml or STARSHIP_TOML
    if starship_path.exists():
        try:
            txt = starship_path.read_text(encoding="utf-8")
            new_txt = re.sub(r"\n*\[palettes\.palettier\][\s\S]*?(?=\n\[|$)", "", txt)
            new_txt = re.sub(r"^\s*palette\s*=\s*['\"]palettier['\"]\n?", "", new_txt, flags=re.MULTILINE)
            starship_path.write_text(new_txt.strip() + "\n" if new_txt.strip() else "", encoding="utf-8")
            print("  [✓] Removed Palettier palette sections from starship.toml")
        except Exception as e:
            print(f"  [!] Failed to clean starship.toml: {e}")

    print("\n[4/6] Restoring Firefox themes...")
    profiles = firefox_profiles if firefox_profiles is not None else get_firefox_profile_dirs()
    for pdir in profiles:
        chrome_file = pdir / "chrome" / "userChrome.css"
        if chrome_file.exists():
            try:
                txt = chrome_file.read_text(encoding="utf-8", errors="ignore")
                if "Palettier" in txt:
                    chrome_file.unlink(missing_ok=True)
                    print(f"  [✓] Removed userChrome.css in: {pdir.name}")
            except Exception as e:
                print(f"  [!] Failed to remove userChrome.css in {pdir}: {e}")

    print("\n[5/6] Restoring GTK 3/4 themes and Flatpak overrides...")
    removed_gtk = remove_gtk_theme(gtk4_dir=gtk4_dir, gtk3_dir=gtk3_dir, revert_flatpak=True)
    for rpath in removed_gtk:
        print(f"  [✓] Cleaned GTK file: {rpath}")

    print("\n[6/6] Removing Material Design 3 icon pack...")
    removed_icons = uninstall_m3_icon_pack(gsettings_get_fn=gsettings_get, gsettings_set_fn=gsettings_set)
    for rpath in removed_icons:
        print(f"  [✓] Removed: {rpath}")

    print("\n[✓] Uninstallation completed successfully! Applications have been restored to defaults.")
