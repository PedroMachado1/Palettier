"""
palettier.config — Persistent XDG configuration management (~/.config/palettier/config.json).
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from palettier.icons import DEFAULT_ICON_TINT_STRENGTH, VALID_ICON_MODES

TARGET_KEYS = ("icons", "gnome_accent", "gtk", "gtk_flatpak", "ptyxis", "starship", "firefox")
_HEX_RE = re.compile(r"^#?(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")


def default_targets() -> dict[str, bool]:
    """Return default enabled state for all theme integration targets."""
    return {k: True for k in TARGET_KEYS}


def normalize_hex_color(value: str | None) -> str | None:
    """Validate and normalize a hex color string to #rrggbb, or return None."""
    if not value or not isinstance(value, str):
        return None
    s = value.strip()
    if not _HEX_RE.match(s):
        return None
    s = s.lstrip("#")
    if len(s) == 3:
        s = "".join(c * 2 for c in s)
    return f"#{s.lower()}"


@dataclass
class PalettierConfig:
    """User configuration persisted in $XDG_CONFIG_HOME/palettier/config.json."""

    icon_mode: str = "system"
    icon_tint: float = DEFAULT_ICON_TINT_STRENGTH
    surface_tint: float | None = None
    accent_override: str | None = None
    targets: dict[str, bool] = field(default_factory=default_targets)

    def __post_init__(self) -> None:
        mode = str(self.icon_mode or "system").strip().lower()
        self.icon_mode = mode if mode in VALID_ICON_MODES else "system"

        try:
            self.icon_tint = max(0.0, min(1.0, round(float(self.icon_tint), 4)))
        except (TypeError, ValueError):
            self.icon_tint = DEFAULT_ICON_TINT_STRENGTH

        if self.surface_tint is not None:
            try:
                self.surface_tint = max(0.0, min(0.5, round(float(self.surface_tint), 4)))
            except (TypeError, ValueError):
                self.surface_tint = None

        self.accent_override = normalize_hex_color(self.accent_override)

        normalized_targets = default_targets()
        if isinstance(self.targets, dict):
            for k in TARGET_KEYS:
                if k in self.targets:
                    normalized_targets[k] = bool(self.targets[k])
        self.targets = normalized_targets

    def to_dict(self) -> dict[str, Any]:
        """Serialize configuration to a JSON-compatible dictionary."""
        return {
            "version": 1,
            "icon_mode": self.icon_mode,
            "icon_tint": self.icon_tint,
            "surface_tint": self.surface_tint,
            "accent_override": self.accent_override,
            "targets": dict(self.targets),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> PalettierConfig:
        """Create a validated PalettierConfig from a dictionary."""
        if not isinstance(data, dict):
            return cls()
        return cls(
            icon_mode=data.get("icon_mode", "system"),
            icon_tint=data.get("icon_tint", DEFAULT_ICON_TINT_STRENGTH),
            surface_tint=data.get("surface_tint", None),
            accent_override=data.get("accent_override", None),
            targets=data.get("targets", default_targets()),
        )

    def fingerprint(self) -> str:
        """Return a stable hash representing settings that affect theme output."""
        payload = json.dumps(self.to_dict(), sort_keys=True)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def get_config_dir() -> Path:
    """Return Palettier's XDG config directory (~/.config/palettier)."""
    xdg_config = os.environ.get("XDG_CONFIG_HOME")
    base = Path(xdg_config) if xdg_config else (Path.home() / ".config")
    return base / "palettier"


def get_config_path() -> Path:
    """Return the path to Palettier's persistent config.json."""
    return get_config_dir() / "config.json"


def load_config(config_path: Path | None = None) -> PalettierConfig:
    """Load configuration from disk, returning defaults if missing or invalid."""
    path = config_path or get_config_path()
    if not path.is_file():
        return PalettierConfig()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return PalettierConfig.from_dict(raw)
    except Exception:
        return PalettierConfig()


def save_config(config: PalettierConfig, config_path: Path | None = None) -> Path:
    """Atomically write configuration to disk and return the file path."""
    path = config_path or get_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=".palettier-cfg.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(config.to_dict(), f, indent=2, ensure_ascii=False)
            f.write("\n")
        os.replace(tmp_name, path)
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise
    return path


def reset_config(config_path: Path | None = None) -> PalettierConfig:
    """Reset configuration to defaults on disk and return the default object."""
    cfg = PalettierConfig()
    save_config(cfg, config_path=config_path)
    return cfg
