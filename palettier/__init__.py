"""Palettier — Dynamic Material Design 3 theme and icon pack synchronizer."""

from __future__ import annotations

__version__ = "2.0.0"
__app_name__ = "Palettier"

from palettier.icons import sync_m3_icon_pack, uninstall_m3_icon_pack
from palettier.palette import build_icon_tint_luts, build_m3_scheme
from palettier.sync import update_theme

__all__ = [
    "__app_name__",
    "__version__",
    "build_icon_tint_luts",
    "build_m3_scheme",
    "sync_m3_icon_pack",
    "uninstall_m3_icon_pack",
    "update_theme",
]
