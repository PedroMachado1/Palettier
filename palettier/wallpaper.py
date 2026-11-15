"""
palettier.wallpaper — Wallpaper discovery, GSettings helpers, and color extraction.
"""

from __future__ import annotations

import colorsys
import re
import subprocess
import urllib.parse
from pathlib import Path

from palettier.palette import hex_to_rgb


def uri_to_path(uri: str) -> Path | None:
    """Convert a 'file://...' URI or local path string to a Path object."""
    if not uri:
        return None
    uri = uri.strip("'\" \t\r\n")
    if not uri or uri.lower() == "nothing" or uri == "''":
        return None
    if uri.startswith("file://"):
        raw = urllib.parse.unquote(uri[7:])
        p = Path(raw)
        return p if p.exists() else Path(raw)
    return Path(uri)


def resolve_wallpaper_path(path: Path | None) -> Path | None:
    """Resolve symlinks and GNOME timed slideshow XML wallpaper descriptors."""
    if not path or not path.exists():
        return path

    if path.suffix.lower() == ".xml":
        try:
            content = path.read_text(encoding="utf-8", errors="ignore")
            matches = re.findall(r"<file>(.*?)</file>", content)
            for m in matches:
                candidate = Path(m.strip())
                if candidate.exists():
                    return candidate
        except Exception:
            pass

    return path.resolve() if path.is_symlink() else path


def _parse_gsettings_value(raw: str) -> str:
    """Normalize `gsettings get` stdout by stripping outer quotes."""
    val = raw.strip()
    if len(val) >= 2 and val[0] == val[-1] and val[0] in ("'", '"'):
        val = val[1:-1]
    return val


def gsettings_get(schema: str, key: str, timeout: float = 3.0) -> str | None:
    """Read the current GSettings value. Returns None if unavailable or on error."""
    try:
        res = subprocess.run(
            ["gsettings", "get", schema, key],
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout,
        )
        if res.returncode == 0:
            return _parse_gsettings_value(res.stdout)
        return None
    except FileNotFoundError:
        try:
            import gi

            gi.require_version("Gio", "2.0")
            from gi.repository import Gio

            settings = Gio.Settings.new(schema)
            return settings.get_string(key)
        except Exception:
            return None
    except Exception:
        return None


def gsettings_set(schema: str, key: str, value: str, timeout: float = 3.0) -> bool:
    """Write a GSettings string key, returning True on success."""
    try:
        res = subprocess.run(
            ["gsettings", "set", schema, key, value],
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout,
        )
        return res.returncode == 0
    except FileNotFoundError:
        try:
            import gi

            gi.require_version("Gio", "2.0")
            from gi.repository import Gio

            settings = Gio.Settings.new(schema)
            return bool(settings.set_string(key, value))
        except Exception:
            return False
    except Exception:
        return False


def get_current_wallpaper_path() -> Path | None:
    """
    Detect the active desktop wallpaper on GNOME (Dark/Light) and fallback sources.
    Prioritizes `gsettings get` and falls back to ~/.config/background, ~/.fehbg,
    and common user wallpaper directories.
    """
    color_scheme = gsettings_get("org.gnome.desktop.interface", "color-scheme")
    is_dark = "dark" in (color_scheme or "prefer-dark").lower()
    keys = ["picture-uri-dark", "picture-uri"] if is_dark else ["picture-uri", "picture-uri-dark"]
    for k in keys:
        uri = gsettings_get("org.gnome.desktop.background", k)
        if uri:
            p = uri_to_path(uri)
            if p and p.exists():
                return resolve_wallpaper_path(p)

    gnome_bg = Path.home() / ".config" / "background"
    if gnome_bg.exists():
        return resolve_wallpaper_path(gnome_bg)

    fehbg = Path.home() / ".fehbg"
    if fehbg.exists():
        try:
            txt = fehbg.read_text(encoding="utf-8", errors="ignore")
            m = re.search(r"'(.*?)'", txt) or re.search(r'"(.*?)"', txt)
            if m:
                p = Path(m.group(1))
                if p.exists():
                    return resolve_wallpaper_path(p)
        except Exception:
            pass

    common_dirs = [
        Path.home() / "Pictures" / "Wallpapers",
        Path.home() / "Imagens" / "Wallpapers",
        Path.home() / "Pictures",
        Path.home() / "Imagens",
    ]
    for cdir in common_dirs:
        if cdir.is_dir():
            images = [
                f
                for f in cdir.iterdir()
                if f.is_file() and f.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp", ".bmp", ".svg")
            ]
            if images:
                latest = max(images, key=lambda f: f.stat().st_mtime)
                return resolve_wallpaper_path(latest)

    return None


def _normalize_candidate_hex(r: int, g: int, b: int, h: float, l: float, s: float) -> str:
    """Normalize lightness into a balanced accent range and return #rrggbb."""
    if 0.44 <= l <= 0.62:
        return f"#{r:02x}{g:02x}{b:02x}"
    target_l = max(0.44, min(0.62, l))
    nr, ng, nb = colorsys.hls_to_rgb(h, target_l, s)
    return f"#{int(round(nr * 255)):02x}{int(round(ng * 255)):02x}{int(round(nb * 255)):02x}"


def _color_distance_sq(hex1: str, hex2: str) -> int:
    r1, g1, b1 = hex_to_rgb(hex1)
    r2, g2, b2 = hex_to_rgb(hex2)
    return (r1 - r2) ** 2 + (g1 - g2) ** 2 + (b1 - b2) ** 2


def _select_distinct_candidates(scored: list[tuple[float, str, float]], max_colors: int) -> list[str]:
    """Pick up to `max_colors` distinct colors in descending score order."""
    if not scored:
        return []
    picked: list[str] = []
    min_dist_sq = 42 * 42

    for _score, hex_col, sat in scored:
        if len(picked) >= max_colors:
            break
        if picked and sat < 0.12:
            continue
        if all(_color_distance_sq(hex_col, existing) >= min_dist_sq for existing in picked):
            picked.append(hex_col)

    if len(picked) < max_colors:
        relaxed_dist_sq = 24 * 24
        for _score, hex_col, _sat in scored:
            if len(picked) >= max_colors:
                break
            if hex_col not in picked and all(
                _color_distance_sq(hex_col, existing) >= relaxed_dist_sq for existing in picked
            ):
                picked.append(hex_col)

    return picked


def extract_colors_from_svg(svg_path: Path, max_colors: int = 1) -> tuple[list[str], float]:
    """Extract primary and secondary accent candidates from a vector SVG wallpaper."""
    try:
        content = svg_path.read_text(encoding="utf-8", errors="ignore")
        hex_matches = re.findall(r"#(?:[0-9a-fA-F]{6})\b", content)
        if not hex_matches:
            return ["#3584e4"], 0.10

        scored: list[tuple[float, str, float]] = []
        for hex_code in set(hex_matches):
            r, g, b = hex_to_rgb(hex_code)
            _h, l, s = colorsys.rgb_to_hls(r / 255.0, g / 255.0, b / 255.0)
            if l < 0.12 or l > 0.90 or s < 0.15:
                continue
            score = (s ** 1.3) * max(0.2, 1.0 - abs(l - 0.54) * 1.8)
            scored.append((score, hex_code.lower(), s))

        if scored:
            scored.sort(key=lambda x: x[0], reverse=True)
            candidates = _select_distinct_candidates(scored, max(1, max_colors))
            return candidates or [scored[0][1]], 0.10
        return ["#3584e4"], 0.10
    except Exception:
        return ["#3584e4"], 0.10


def extract_wallpaper_candidates(
    wallpaper_path: Path | str | None = None,
    forced_tint: float | None = None,
    max_colors: int = 6,
) -> tuple[list[str], float, Path | None]:
    """
    Analyze the wallpaper image and extract up to `max_colors` distinct accent color
    candidates ordered by perceptual vibrancy and visual prominence.
    """
    wp = Path(wallpaper_path) if wallpaper_path else get_current_wallpaper_path()

    if not wp or not wp.exists():
        print("[!] No wallpaper found on the system. Using default accent (#3584e4).")
        return ["#3584e4"], forced_tint if forced_tint is not None else 0.10, None

    if wp.suffix.lower() == ".svg":
        candidates, tint = extract_colors_from_svg(wp, max_colors=max_colors)
        if forced_tint is not None:
            tint = forced_tint
        return candidates, tint, wp

    try:
        from PIL import Image

        with Image.open(wp) as img:
            img = img.convert("RGB")
            small = img.resize((120, 120), Image.Resampling.BILINEAR)
            quantized = small.quantize(colors=24, method=Image.Quantize.MEDIANCUT)
            palette = quantized.getpalette()[:72]
            color_counts = quantized.getcolors() or []

            scored_candidates = []
            total_saturation = 0.0
            valid_pixels = 0

            for count, idx in color_counts:
                r = palette[idx * 3]
                g = palette[idx * 3 + 1]
                b = palette[idx * 3 + 2]

                h, l, s = colorsys.rgb_to_hls(r / 255.0, g / 255.0, b / 255.0)
                total_saturation += s * count
                valid_pixels += count

                if l < 0.12 or l > 0.90:
                    continue

                lightness_penalty = abs(l - 0.54)
                lightness_multiplier = max(0.2, 1.0 - (lightness_penalty * 1.8))
                saturation_multiplier = s ** 1.4
                pop_multiplier = count ** 0.55

                score = pop_multiplier * saturation_multiplier * lightness_multiplier
                scored_candidates.append((score, r, g, b, h, l, s))

            avg_saturation = (total_saturation / valid_pixels) if valid_pixels > 0 else 0.5
            calculated_tint = max(0.08, min(0.14, round(0.06 + avg_saturation * 0.08, 2)))
            if forced_tint is not None:
                calculated_tint = forced_tint

            if not scored_candidates:
                return ["#3584e4"], calculated_tint, wp

            scored_candidates.sort(key=lambda x: x[0], reverse=True)
            best = scored_candidates[0]

            if best[6] < 0.15:
                return ["#4a8fe7"], calculated_tint, wp

            normalized: list[tuple[float, str, float]] = [
                (score, _normalize_candidate_hex(r, g, b, h, l, s), s)
                for score, r, g, b, h, l, s in scored_candidates
            ]
            candidates = _select_distinct_candidates(normalized, max(1, max_colors))
            return candidates or [normalized[0][1]], calculated_tint, wp

    except ImportError:
        print("[!] Pillow (PIL) library not found.")
        print("[!] Install image support via: pip install pillow (or python3-pil)")
        return ["#3584e4"], forced_tint if forced_tint is not None else 0.10, wp
    except Exception as e:
        print(f"[!] Error processing image {wp}: {e}")
        return ["#3584e4"], forced_tint if forced_tint is not None else 0.10, wp


def extract_wallpaper_colors(
    wallpaper_path: Path | str | None = None,
    forced_tint: float | None = None,
) -> tuple[str, float, Path | None]:
    """
    Analyze the wallpaper image and extract a vibrant accent color and
    recommended tint intensity for dark surfaces.
    """
    candidates, tint, wp = extract_wallpaper_candidates(
        wallpaper_path=wallpaper_path,
        forced_tint=forced_tint,
        max_colors=1,
    )
    return candidates[0], tint, wp

