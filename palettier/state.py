"""
palettier.state — Idempotent runtime state cache and RPM/DNF transaction guard.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import shutil
import struct
import subprocess
import tempfile
import time
from pathlib import Path

from palettier.wallpaper import (
    get_current_wallpaper_path,
    gsettings_get,
    resolve_wallpaper_path,
    uri_to_path,
)

DEBOUNCE_SECONDS = 2.0
RPM_WAIT_POLL_SECONDS = 2.0
RPM_WAIT_TIMEOUT_SECONDS = 600.0
RPM_LOCK_PATHS = (
    Path("/var/lib/rpm/.rpm.lock"),
    Path("/usr/lib/sysimage/rpm/.rpm.lock"),
    Path("/run/dnf/rpm.lock"),
)
PACKAGE_MANAGER_PROCESS_NAMES = frozenset({"dnf", "dnf-3", "dnf5", "yum", "rpm"})


def get_state_file_path() -> Path:
    """Return the runtime state file path under $XDG_RUNTIME_DIR/palettier.state."""
    runtime_dir = os.environ.get("XDG_RUNTIME_DIR")
    if runtime_dir:
        return Path(runtime_dir) / "palettier.state"
    run_user = Path(f"/run/user/{os.getuid()}")
    if run_user.is_dir():
        return run_user / "palettier.state"
    return Path(tempfile.gettempdir()) / f"palettier-{os.getuid()}.state"


def compute_file_sha256(path: Path | None) -> str | None:
    """Compute the SHA-256 hex digest of a wallpaper file."""
    if not path:
        return None
    try:
        if not path.is_file():
            return None
        hasher = hashlib.sha256()
        with path.open("rb") as f:
            while chunk := f.read(65536):
                hasher.update(chunk)
        return hasher.hexdigest()
    except Exception:
        return None


def collect_current_state(wallpaper_path: Path | str | None = None) -> dict:
    """
    Collect current desktop state via `gsettings get` and compute the
    active wallpaper's SHA-256 hash.
    """
    color_scheme = gsettings_get("org.gnome.desktop.interface", "color-scheme")
    picture_uri = gsettings_get("org.gnome.desktop.background", "picture-uri")
    picture_uri_dark = gsettings_get("org.gnome.desktop.background", "picture-uri-dark")

    if wallpaper_path:
        active_wp = resolve_wallpaper_path(Path(wallpaper_path))
    else:
        active_wp = None
        is_dark = "dark" in (color_scheme or "prefer-dark").lower()
        ordered_uris = [picture_uri_dark, picture_uri] if is_dark else [picture_uri, picture_uri_dark]
        for uri in ordered_uris:
            if uri:
                p = uri_to_path(uri)
                if p and p.exists():
                    active_wp = resolve_wallpaper_path(p)
                    break
        if active_wp is None:
            active_wp = get_current_wallpaper_path()

    return {
        "wallpaper_sha256": compute_file_sha256(active_wp),
        "wallpaper_path": str(active_wp) if active_wp else None,
        "color_scheme": color_scheme,
        "picture_uri": picture_uri,
        "picture_uri_dark": picture_uri_dark,
    }


def load_saved_state(state_file: Path | None = None) -> dict | None:
    """Load the last applied state from $XDG_RUNTIME_DIR/palettier.state."""
    path = state_file or get_state_file_path()
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return data
    except Exception:
        pass
    return None


def save_state(state: dict, state_file: Path | None = None) -> bool:
    """Atomically save the applied state to $XDG_RUNTIME_DIR/palettier.state."""
    path = state_file or get_state_file_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(prefix=".palettier.", suffix=".tmp", dir=str(path.parent))
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(state, f, indent=2, ensure_ascii=False)
                f.write("\n")
            os.replace(tmp_name, path)
        except Exception:
            try:
                os.unlink(tmp_name)
            except OSError:
                pass
            raise
        return True
    except Exception as e:
        print(f"[!] Failed to save state to {path}: {e}")
        return False


def is_state_unchanged(
    current_state: dict,
    saved_state: dict | None,
    icon_mode: str | None = None,
) -> bool:
    """
    Compare current desktop state with the persisted `.state` payload.
    Returns True only if wallpaper SHA-256, color-scheme, URIs, and icon mode all match.
    """
    if not saved_state:
        return False
    if not current_state.get("wallpaper_sha256"):
        return False
    if not saved_state.get("accent_color"):
        return False
    if saved_state.get("wallpaper_sha256") != current_state.get("wallpaper_sha256"):
        return False
    if saved_state.get("color_scheme") != current_state.get("color_scheme"):
        return False
    if "picture_uri" in saved_state and saved_state.get("picture_uri") != current_state.get("picture_uri"):
        return False
    if "picture_uri_dark" in saved_state and saved_state.get("picture_uri_dark") != current_state.get("picture_uri_dark"):
        return False
    if icon_mode is not None and saved_state.get("icon_mode") != icon_mode:
        return False
    return True


def _is_file_locked(lock_path: Path) -> bool:
    """Check whether a lock file has an active lock via flock, fcntl(F_GETLK), or fuser."""
    if not lock_path.exists():
        return False

    try:
        with lock_path.open("rb") as f:
            fd = f.fileno()
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                fcntl.flock(fd, fcntl.LOCK_UN)
            except BlockingIOError:
                return True
            except OSError:
                pass

            try:
                flock_struct = struct.pack("hhlli", fcntl.F_WRLCK, os.SEEK_SET, 0, 0, 0)
                res = fcntl.fcntl(fd, fcntl.F_GETLK, flock_struct)
                l_type = struct.unpack("hhlli", res)[0]
                if l_type != fcntl.F_UNLCK:
                    return True
            except OSError:
                pass
    except OSError:
        pass

    fuser_bin = shutil.which("fuser")
    if fuser_bin:
        try:
            res = subprocess.run(
                [fuser_bin, str(lock_path)],
                capture_output=True,
                text=True,
                check=False,
                timeout=2,
            )
            if res.returncode == 0 and res.stdout.strip():
                return True
        except Exception:
            pass

    return False


def _has_active_package_manager_process() -> bool:
    """Check /proc for running dnf, dnf5, yum, or rpm processes."""
    proc_dir = Path("/proc")
    if not proc_dir.is_dir():
        return False

    own_pid = str(os.getpid())
    try:
        entries = list(proc_dir.iterdir())
    except OSError:
        return False

    for entry in entries:
        pid = entry.name
        if not pid.isdigit() or pid == own_pid:
            continue
        try:
            comm = (entry / "comm").read_text(encoding="utf-8", errors="ignore").strip()
            if comm in PACKAGE_MANAGER_PROCESS_NAMES:
                return True

            cmdline_raw = (entry / "cmdline").read_bytes()
            if cmdline_raw:
                args = [a.decode("utf-8", errors="ignore") for a in cmdline_raw.split(b"\x00") if a]
                for arg in args[:2]:
                    if Path(arg).name in PACKAGE_MANAGER_PROCESS_NAMES:
                        return True
        except OSError:
            continue

    return False


def is_package_transaction_active() -> bool:
    """Return True if an RPM/DNF package transaction is currently active."""
    for lock_path in RPM_LOCK_PATHS:
        if _is_file_locked(lock_path):
            return True
    return _has_active_package_manager_process()


def wait_for_package_transaction(
    poll_interval: float = RPM_WAIT_POLL_SECONDS,
    timeout: float = RPM_WAIT_TIMEOUT_SECONDS,
) -> bool:
    """
    Wait for any active RPM/DNF transaction to finish before evaluating state
    or applying changes. Returns False only on timeout.
    """
    if not is_package_transaction_active():
        return True

    print("[*] RPM/DNF transaction in progress. Waiting for completion before evaluating state...")
    deadline = time.monotonic() + timeout
    while is_package_transaction_active():
        if time.monotonic() >= deadline:
            print("[!] Timed out waiting for RPM/DNF transaction to finish.")
            return False
        time.sleep(poll_interval)

    print("[*] RPM/DNF transaction finished. Proceeding with state check...")
    return True
