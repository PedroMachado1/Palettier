"""
palettier.palette — Material Design 3 Color Engine (CAM16 / HCT & Tonal Palettes).

Pure-Python implementation (no external dependencies) based on the official
Material Design 3 color specifications (https://m3.material.io/styles/color/).

Derives perceptually uniform tonal palettes (Hue, Chroma, Tone) and generates
semantic Material Design 3 color tokens for Dark and Light themes, plus icon
tinting lookup tables (LUTs).
"""

from __future__ import annotations

import colorsys
import math
from dataclasses import dataclass

# ==============================================================================
# 1. COLOR SPACE CONVERSIONS (sRGB <-> Linear RGB <-> XYZ <-> L*a*b*)
# ==============================================================================

_D65_WHITE = (95.047, 100.0, 108.883)


def hex_to_rgb(hex_str: str) -> tuple[int, int, int]:
    """Convert a hex color string (#RRGGBB or #RGB) to an RGB tuple (0-255)."""
    s = hex_str.strip().lstrip("#")
    if len(s) == 3:
        s = "".join(c * 2 for c in s)
    if len(s) != 6:
        raise ValueError(f"Invalid hexadecimal color: {hex_str!r}")
    return (int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16))


def rgb_to_hex(r: float, g: float, b: float) -> str:
    """Convert RGB components (0-255) into a #rrggbb hex string."""
    ri = max(0, min(255, int(round(r))))
    gi = max(0, min(255, int(round(g))))
    bi = max(0, min(255, int(round(b))))
    return f"#{ri:02x}{gi:02x}{bi:02x}"


def mix(hex1: str, hex2: str, weight: float) -> str:
    """Blend two hex colors based on weight (0.0 = hex1, 1.0 = hex2)."""
    r1, g1, b1 = hex_to_rgb(hex1)
    r2, g2, b2 = hex_to_rgb(hex2)
    r = r1 * (1.0 - weight) + r2 * weight
    g = g1 * (1.0 - weight) + g2 * weight
    b = b1 * (1.0 - weight) + b2 * weight
    return rgb_to_hex(r, g, b)


def adjust_lightness(hex_str: str, delta: float) -> str:
    """Adjust relative lightness in HSL space (-1.0 to +1.0)."""
    r, g, b = (c / 255.0 for c in hex_to_rgb(hex_str))
    h, l, s = colorsys.rgb_to_hls(r, g, b)
    l = max(0.0, min(1.0, l + delta))
    nr, ng, nb = colorsys.hls_to_rgb(h, l, s)
    return rgb_to_hex(nr * 255, ng * 255, nb * 255)


def map_hex_to_gnome_accent(hex_str: str) -> str:
    """Map a hex color to the closest native GNOME 47+ accent-color keyword."""
    r, g, b = (c / 255.0 for c in hex_to_rgb(hex_str))
    h, _l, s = colorsys.rgb_to_hls(r, g, b)
    if s < 0.18:
        return "slate"
    deg = (h * 360.0) % 360
    if deg < 18 or deg >= 345:
        return "red"
    if deg < 45:
        return "orange"
    if deg < 70:
        return "yellow"
    if deg < 165:
        return "green"
    if deg < 195:
        return "teal"
    if deg < 260:
        return "blue"
    if deg < 305:
        return "purple"
    return "pink"


def _srgb_channel_to_linear(u8: int) -> float:
    norm = max(0.0, min(255.0, float(u8))) / 255.0
    if norm <= 0.040449936:
        return (norm / 12.92) * 100.0
    return (((norm + 0.055) / 1.055) ** 2.4) * 100.0


def _linear_to_srgb_channel(lin: float) -> int:
    norm = lin / 100.0
    if norm <= 0.0:
        return 0
    if norm >= 1.0:
        return 255
    if norm <= 0.0031308:
        comp = norm * 12.92
    else:
        comp = 1.055 * (norm ** (1.0 / 2.4)) - 0.055
    return max(0, min(255, int(round(comp * 255.0))))


def rgb_to_xyz(r: int, g: int, b: int) -> tuple[float, float, float]:
    lr = _srgb_channel_to_linear(r)
    lg = _srgb_channel_to_linear(g)
    lb = _srgb_channel_to_linear(b)
    x = 0.41233895 * lr + 0.35762064 * lg + 0.18051042 * lb
    y = 0.2126 * lr + 0.7152 * lg + 0.0722 * lb
    z = 0.01932141 * lr + 0.11916382 * lg + 0.95034478 * lb
    return (x, y, z)


def xyz_to_linear_rgb(x: float, y: float, z: float) -> tuple[float, float, float]:
    lr = 3.2413774792388685 * x - 1.5376652402851851 * y - 0.49885366846268053 * z
    lg = -0.9691452513005321 * x + 1.8758853451067872 * y + 0.04156585616912061 * z
    lb = 0.05562093689691305 * x - 0.20395524564742123 * y + 1.0571799111220335 * z
    return (lr, lg, lb)


def _lab_f(t: float) -> float:
    e = 216.0 / 24389.0  # (6/29)^3
    kappa = 24389.0 / 27.0  # (29/3)^3
    if t > e:
        return t ** (1.0 / 3.0)
    return (kappa * t + 16.0) / 116.0


def _lab_inv_f(ft: float) -> float:
    e = 216.0 / 24389.0
    kappa = 24389.0 / 27.0
    ft3 = ft * ft * ft
    if ft3 > e:
        return ft3
    return (116.0 * ft - 16.0) / kappa


def lstar_from_y(y: float) -> float:
    return 116.0 * _lab_f(y / 100.0) - 16.0


def y_from_lstar(lstar: float) -> float:
    return 100.0 * _lab_inv_f((lstar + 16.0) / 116.0)


def lstar_from_rgb(r: int, g: int, b: int) -> float:
    _, y, _ = rgb_to_xyz(r, g, b)
    return lstar_from_y(y)


def relative_luminance(hex_str: str) -> float:
    """Compute WCAG relative luminance (0.0 to 1.0)."""
    r, g, b = hex_to_rgb(hex_str)
    _, y, _ = rgb_to_xyz(r, g, b)
    return max(0.0, min(1.0, y / 100.0))


def contrast_ratio(hex1: str, hex2: str) -> float:
    """Compute WCAG 2.1 contrast ratio between two hex colors (1.0 to 21.0)."""
    l1 = relative_luminance(hex1)
    l2 = relative_luminance(hex2)
    lighter = max(l1, l2)
    darker = min(l1, l2)
    return (lighter + 0.05) / (darker + 0.05)


# ==============================================================================
# 2. CAM16 COLOR APPEARANCE MODEL & HCT SOLVER (MATERIAL DESIGN 3)
# ==============================================================================

class _ViewingConditions:
    """Standard sRGB / D65 viewing conditions from Material Color Utilities."""

    def __init__(self) -> None:
        wx, wy, wz = _D65_WHITE
        background_lstar = 50.0
        adapting_luminance = (200.0 / math.pi) * y_from_lstar(background_lstar) / 100.0
        surround = 2.0

        rw = 0.401288 * wx + 0.650173 * wy - 0.051461 * wz
        gw = -0.250268 * wx + 1.204414 * wy + 0.045854 * wz
        bw = -0.002079 * wx + 0.048952 * wy + 0.953127 * wz

        f = 0.8 + surround / 10.0
        self.c = 0.69
        self.nc = 1.0

        d = f * (1.0 - (1.0 / 3.6) * math.exp((-adapting_luminance - 42.0) / 92.0))
        d = max(0.0, min(1.0, d))

        self.rgb_d = (
            d * (100.0 / rw) + 1.0 - d,
            d * (100.0 / gw) + 1.0 - d,
            d * (100.0 / bw) + 1.0 - d,
        )

        k = 1.0 / (5.0 * adapting_luminance + 1.0)
        k4 = k ** 4
        k4f = 1.0 - k4
        self.fl = k4 * adapting_luminance + 0.1 * k4f * k4f * ((5.0 * adapting_luminance) ** (1.0 / 3.0))
        self.n = y_from_lstar(background_lstar) / wy
        self.z = 1.48 + math.sqrt(self.n)
        self.nbb = 0.725 / (self.n ** 0.2)
        self.ncb = self.nbb

        r_af = (self.fl * self.rgb_d[0] * rw / 100.0) ** 0.42
        g_af = (self.fl * self.rgb_d[1] * gw / 100.0) ** 0.42
        b_af = (self.fl * self.rgb_d[2] * bw / 100.0) ** 0.42

        r_a = (400.0 * r_af) / (r_af + 27.13)
        g_a = (400.0 * g_af) / (g_af + 27.13)
        b_a = (400.0 * b_af) / (b_af + 27.13)

        self.aw = (2.0 * r_a + g_a + 0.05 * b_a) * self.nbb
        self.fl_root = self.fl ** 0.25


_VC = _ViewingConditions()


def rgb_to_hct(r: int, g: int, b: int) -> tuple[float, float, float]:
    """Convert RGB (0-255) to HCT (hue: 0-360, chroma: >=0, tone: 0-100)."""
    x, y, z = rgb_to_xyz(r, g, b)
    tone = lstar_from_y(y)

    rc = 0.401288 * x + 0.650173 * y - 0.051461 * z
    gc = -0.250268 * x + 1.204414 * y + 0.045854 * z
    bc = -0.002079 * x + 0.048952 * y + 0.953127 * z

    rd = _VC.rgb_d[0] * rc
    gd = _VC.rgb_d[1] * gc
    bd = _VC.rgb_d[2] * bc

    def _adapt(val: float) -> float:
        af = (_VC.fl * abs(val) / 100.0) ** 0.42
        sign = -1.0 if val < 0 else 1.0
        return sign * (400.0 * af) / (af + 27.13)

    ra = _adapt(rd)
    ga = _adapt(gd)
    ba = _adapt(bd)

    a = (11.0 * ra - 12.0 * ga + ba) / 11.0
    b_comp = (ra + ga - 2.0 * ba) / 9.0
    u = (20.0 * ra + 20.0 * ga + 21.0 * ba) / 20.0
    p2 = (40.0 * ra + 20.0 * ga + ba) / 20.0

    atan_rad = math.atan2(b_comp, a)
    hue = math.degrees(atan_rad) % 360.0

    ac = p2 * _VC.nbb
    j = 100.0 * ((max(0.0, ac) / _VC.aw) ** (_VC.c * _VC.z))
    et = 0.25 * (math.cos(math.radians(hue) + 2.0) + 3.8)
    t = (50000.0 / 13.0 * _VC.nc * _VC.ncb * et * math.hypot(a, b_comp)) / (u + 0.305)
    alpha = (1.64 - (0.29 ** _VC.n)) ** 0.73 * (t ** 0.9)
    chroma = alpha * math.sqrt(max(0.0, j) / 100.0)

    return (hue, chroma, tone)


def hex_to_hct(hex_str: str) -> tuple[float, float, float]:
    """Convert a hex color string to HCT."""
    r, g, b = hex_to_rgb(hex_str)
    return rgb_to_hct(r, g, b)


def _cam16_jch_to_xyz(j: float, chroma: float, hue: float) -> tuple[float, float, float]:
    """Convert CAM16 (J, C, H) to D65 XYZ."""
    alpha = 0.0 if (chroma == 0.0 or j == 0.0) else chroma / math.sqrt(j / 100.0)
    t = (alpha / ((1.64 - (0.29 ** _VC.n)) ** 0.73)) ** (1.0 / 0.9)
    h_rad = math.radians(hue)
    e_hue = 0.25 * (math.cos(h_rad + 2.0) + 3.8)
    ac = _VC.aw * ((j / 100.0) ** (1.0 / (_VC.c * _VC.z)))
    p1 = e_hue * (50000.0 / 13.0) * _VC.nc * _VC.ncb
    p2 = ac / _VC.nbb

    h_sin = math.sin(h_rad)
    h_cos = math.cos(h_rad)

    gamma = (23.0 * (p2 + 0.305) * t) / (23.0 * p1 + 11.0 * t * h_cos + 108.0 * t * h_sin)
    a = gamma * h_cos
    b = gamma * h_sin

    r_a = (460.0 * p2 + 451.0 * a + 288.0 * b) / 1403.0
    g_a = (460.0 * p2 - 891.0 * a - 261.0 * b) / 1403.0
    b_a = (460.0 * p2 - 220.0 * a - 6300.0 * b) / 1403.0

    def _inv_adapt(val_a: float, d_val: float) -> float:
        base = max(0.0, (27.13 * abs(val_a)) / (400.0 - abs(val_a)))
        sign = -1.0 if val_a < 0 else 1.0
        return sign * (100.0 / _VC.fl) * (base ** (1.0 / 0.42)) / d_val

    r_c = _inv_adapt(r_a, _VC.rgb_d[0])
    g_c = _inv_adapt(g_a, _VC.rgb_d[1])
    b_c = _inv_adapt(b_a, _VC.rgb_d[2])

    x = 1.86206786 * r_c - 1.01125463 * g_c + 0.14918677 * b_c
    y = 0.38752654 * r_c + 0.62144744 * g_c - 0.00897398 * b_c
    z = -0.01584150 * r_c - 0.03412294 * g_c + 1.04996444 * b_c
    return (x, y, z)


def _solve_j_for_tone(chroma: float, hue: float, target_y: float) -> tuple[float, float, float] | None:
    """Find CAM16 J yielding Y == target_y within valid linear RGB gamut [0..100]."""
    low_j = 0.0
    high_j = 100.0
    best_lin: tuple[float, float, float] | None = None
    best_diff = 1e9

    for _ in range(28):
        mid_j = 0.5 * (low_j + high_j)
        x, y, z = _cam16_jch_to_xyz(mid_j, chroma, hue)
        lr, lg, lb = xyz_to_linear_rgb(x, y, z)
        in_gamut = (-0.05 <= lr <= 100.05) and (-0.05 <= lg <= 100.05) and (-0.05 <= lb <= 100.05)

        if in_gamut:
            diff = abs(y - target_y)
            if diff < best_diff:
                best_diff = diff
                best_lin = (lr, lg, lb)
            if diff < 0.002:
                return best_lin

        if y < target_y:
            low_j = mid_j
        else:
            high_j = mid_j

    if best_lin is not None and best_diff <= 0.35:
        return best_lin
    return None


def hct_to_hex(hue: float, chroma: float, tone: float) -> str:
    """
    Resolve the sRGB color (#rrggbb) for (hue, chroma, tone) in HCT space,
    smoothly reducing chroma when the target falls outside the sRGB gamut.
    """
    tone = max(0.0, min(100.0, float(tone)))
    if tone < 0.0001:
        return "#000000"
    if tone > 99.9999:
        return "#ffffff"

    hue = hue % 360.0
    chroma = max(0.0, float(chroma))
    target_y = y_from_lstar(tone)

    candidate = _solve_j_for_tone(chroma, hue, target_y)
    if candidate is None and chroma > 0.0:
        lo_c = 0.0
        hi_c = chroma
        best_lin: tuple[float, float, float] | None = None
        for _ in range(24):
            mid_c = 0.5 * (lo_c + hi_c)
            res = _solve_j_for_tone(mid_c, hue, target_y)
            if res is not None:
                best_lin = res
                lo_c = mid_c
            else:
                hi_c = mid_c
        candidate = best_lin

    if candidate is None:
        gray = _linear_to_srgb_channel(target_y)
        return rgb_to_hex(gray, gray, gray)

    lr, lg, lb = candidate
    return rgb_to_hex(
        _linear_to_srgb_channel(lr),
        _linear_to_srgb_channel(lg),
        _linear_to_srgb_channel(lb),
    )


# ==============================================================================
# 3. TONAL PALETTES & COMPLETE MATERIAL DESIGN 3 SCHEME
# ==============================================================================

@dataclass(frozen=True)
class TonalPalette:
    """Material Design 3 tonal palette parameterized by Hue and Chroma in HCT space."""

    hue: float
    chroma: float

    def tone(self, t: float) -> str:
        return hct_to_hex(self.hue, self.chroma, t)


def build_m3_scheme(seed_hex: str, is_dark: bool = True) -> dict[str, str]:
    """
    Build a complete Material Design 3 Color Design Tokens dictionary
    (SchemeTonalSpot) from a wallpaper seed color.

    Returns standard M3 roles plus auxiliary tonal roles for desktop SVG icons.
    """
    hue, src_chroma, _ = hex_to_hct(seed_hex)

    # Avoid washed-out colors or hue noise on near-monochrome wallpapers
    if src_chroma < 8.0:
        primary_chroma = 20.0
        secondary_chroma = 12.0
        tertiary_chroma = 16.0
    else:
        primary_chroma = max(36.0, min(84.0, src_chroma))
        secondary_chroma = max(16.0, min(28.0, src_chroma * 0.42))
        tertiary_chroma = max(24.0, min(42.0, src_chroma * 0.65))

    primary_pal = TonalPalette(hue=hue, chroma=primary_chroma)
    secondary_pal = TonalPalette(hue=hue, chroma=secondary_chroma)
    tertiary_pal = TonalPalette(hue=(hue + 60.0) % 360.0, chroma=tertiary_chroma)
    neutral_pal = TonalPalette(hue=hue, chroma=6.0)
    neutral_var_pal = TonalPalette(hue=hue, chroma=8.0)
    error_pal = TonalPalette(hue=25.0, chroma=84.0)

    if is_dark:
        return {
            "seed": seed_hex.lower(),
            "mode": "dark",
            "hue": f"{hue:.1f}",
            # Primary
            "primary": primary_pal.tone(80),
            "onPrimary": primary_pal.tone(20),
            "primaryContainer": primary_pal.tone(30),
            "onPrimaryContainer": primary_pal.tone(90),
            # Secondary
            "secondary": secondary_pal.tone(80),
            "onSecondary": secondary_pal.tone(20),
            "secondaryContainer": secondary_pal.tone(30),
            "onSecondaryContainer": secondary_pal.tone(90),
            # Tertiary
            "tertiary": tertiary_pal.tone(80),
            "onTertiary": tertiary_pal.tone(20),
            "tertiaryContainer": tertiary_pal.tone(30),
            "onTertiaryContainer": tertiary_pal.tone(90),
            # Error
            "error": error_pal.tone(80),
            "onError": error_pal.tone(20),
            "errorContainer": error_pal.tone(30),
            "onErrorContainer": error_pal.tone(90),
            # Surfaces & Neutrals
            "surface": neutral_pal.tone(6),
            "surfaceDim": neutral_pal.tone(6),
            "surfaceBright": neutral_pal.tone(24),
            "surfaceContainerLowest": neutral_pal.tone(4),
            "surfaceContainerLow": neutral_pal.tone(10),
            "surfaceContainer": neutral_pal.tone(12),
            "surfaceContainerHigh": neutral_pal.tone(17),
            "surfaceContainerHighest": neutral_pal.tone(22),
            "onSurface": neutral_pal.tone(90),
            "onSurfaceVariant": neutral_var_pal.tone(80),
            "outline": neutral_var_pal.tone(60),
            "outlineVariant": neutral_var_pal.tone(30),
            # Fixed & Inverse
            "inverseSurface": neutral_pal.tone(90),
            "inverseOnSurface": neutral_pal.tone(20),
            "inversePrimary": primary_pal.tone(40),
            "primaryFixed": primary_pal.tone(90),
            "primaryFixedDim": primary_pal.tone(80),
            "onPrimaryFixed": primary_pal.tone(10),
            "onPrimaryFixedVariant": primary_pal.tone(30),
            # Icon-specific tonal roles
            "iconFolderBack": primary_pal.tone(46),
            "iconFolderFrontTop": primary_pal.tone(76),
            "iconFolderFrontBottom": primary_pal.tone(68),
            "iconFolderHighlight": primary_pal.tone(88),
            "iconFolderGlyph": primary_pal.tone(15),
            "iconFolderPaper": neutral_pal.tone(92),
            "iconDocBody": neutral_pal.tone(18),
            "iconDocFold": neutral_pal.tone(28),
            "iconDocStroke": neutral_var_pal.tone(34),
            "iconAppSurface": primary_pal.tone(26),
            "iconAppGlyph": primary_pal.tone(88),
        }

    return {
        "seed": seed_hex.lower(),
        "mode": "light",
        "hue": f"{hue:.1f}",
        # Primary
        "primary": primary_pal.tone(40),
        "onPrimary": primary_pal.tone(100),
        "primaryContainer": primary_pal.tone(90),
        "onPrimaryContainer": primary_pal.tone(10),
        # Secondary
        "secondary": secondary_pal.tone(40),
        "onSecondary": secondary_pal.tone(100),
        "secondaryContainer": secondary_pal.tone(90),
        "onSecondaryContainer": secondary_pal.tone(10),
        # Tertiary
        "tertiary": tertiary_pal.tone(40),
        "onTertiary": tertiary_pal.tone(100),
        "tertiaryContainer": tertiary_pal.tone(90),
        "onTertiaryContainer": tertiary_pal.tone(10),
        # Error
        "error": error_pal.tone(40),
        "onError": error_pal.tone(100),
        "errorContainer": error_pal.tone(90),
        "onErrorContainer": error_pal.tone(10),
        # Surfaces & Neutrals
        "surface": neutral_pal.tone(98),
        "surfaceDim": neutral_pal.tone(87),
        "surfaceBright": neutral_pal.tone(98),
        "surfaceContainerLowest": neutral_pal.tone(100),
        "surfaceContainerLow": neutral_pal.tone(96),
        "surfaceContainer": neutral_pal.tone(94),
        "surfaceContainerHigh": neutral_pal.tone(92),
        "surfaceContainerHighest": neutral_pal.tone(90),
        "onSurface": neutral_pal.tone(10),
        "onSurfaceVariant": neutral_var_pal.tone(30),
        "outline": neutral_var_pal.tone(50),
        "outlineVariant": neutral_var_pal.tone(80),
        # Fixed & Inverse
        "inverseSurface": neutral_pal.tone(20),
        "inverseOnSurface": neutral_pal.tone(95),
        "inversePrimary": primary_pal.tone(80),
        "primaryFixed": primary_pal.tone(90),
        "primaryFixedDim": primary_pal.tone(80),
        "onPrimaryFixed": primary_pal.tone(10),
        "onPrimaryFixedVariant": primary_pal.tone(30),
        # Icon-specific tonal roles
        "iconFolderBack": primary_pal.tone(32),
        "iconFolderFrontTop": primary_pal.tone(52),
        "iconFolderFrontBottom": primary_pal.tone(44),
        "iconFolderHighlight": primary_pal.tone(72),
        "iconFolderGlyph": primary_pal.tone(99),
        "iconFolderPaper": neutral_pal.tone(99),
        "iconDocBody": neutral_pal.tone(97),
        "iconDocFold": neutral_pal.tone(86),
        "iconDocStroke": neutral_var_pal.tone(76),
        "iconAppSurface": primary_pal.tone(88),
        "iconAppGlyph": primary_pal.tone(22),
    }


def _smoothstep(edge0: float, edge1: float, x: float) -> float:
    if x <= edge0:
        return 0.0
    if x >= edge1:
        return 1.0
    t = (x - edge0) / (edge1 - edge0)
    return t * t * (3.0 - 2.0 * t)


def build_icon_tint_luts(
    seed_hex: str,
) -> tuple[list[tuple[int, int, int]], list[tuple[int, int, int]]]:
    """
    Build two 256-entry RGB lookup tables (`lut_primary`, `lut_neutral`) that preserve
    perceptual luminance (CIE L* / Tone) in Material Design 3 HCT space.

    - `lut_primary`: applies the wallpaper's primary hue and chroma to chromatic regions,
      tapering smoothly near pure black and pure white to preserve contrast.
    - `lut_neutral`: applies subtle neutral tinting to originally gray/white/black regions.
    """
    hue, src_chroma, _ = hex_to_hct(seed_hex)
    if src_chroma < 8.0:
        primary_chroma = 24.0
        neutral_chroma = 8.0
    else:
        primary_chroma = max(38.0, min(72.0, src_chroma * 0.95))
        neutral_chroma = max(6.0, min(14.0, primary_chroma * 0.22))

    # 33 keyframes (step 8 + 255) for sub-20ms generation and accurate linear interpolation
    keyframes = list(range(0, 256, 8))
    if keyframes[-1] != 255:
        keyframes.append(255)

    p_keys: dict[int, tuple[int, int, int]] = {}
    n_keys: dict[int, tuple[int, int, int]] = {}

    for v in keyframes:
        tone = lstar_from_rgb(v, v, v)
        if tone <= 4.0 or tone >= 97.0:
            envelope = 0.0
        else:
            envelope = _smoothstep(4.0, 24.0, tone) * (1.0 - _smoothstep(72.0, 97.0, tone))

        if envelope <= 0.001:
            rgb = (v, v, v)
            p_keys[v] = rgb
            n_keys[v] = rgb
        else:
            c_p = primary_chroma * envelope
            c_n = neutral_chroma * _smoothstep(5.0, 22.0, tone) * (1.0 - _smoothstep(78.0, 97.0, tone))
            p_keys[v] = hex_to_rgb(hct_to_hex(hue, c_p, tone))
            n_keys[v] = hex_to_rgb(hct_to_hex(hue, c_n, tone))

    lut_primary: list[tuple[int, int, int]] = [(0, 0, 0)] * 256
    lut_neutral: list[tuple[int, int, int]] = [(0, 0, 0)] * 256

    for idx in range(len(keyframes) - 1):
        k0 = keyframes[idx]
        k1 = keyframes[idx + 1]
        span = float(k1 - k0)
        pr0, pg0, pb0 = p_keys[k0]
        pr1, pg1, pb1 = p_keys[k1]
        nr0, ng0, nb0 = n_keys[k0]
        nr1, ng1, nb1 = n_keys[k1]
        for v in range(k0, k1 + 1):
            t = (v - k0) / span
            lut_primary[v] = (
                int(round(pr0 + (pr1 - pr0) * t)),
                int(round(pg0 + (pg1 - pg0) * t)),
                int(round(pb0 + (pb1 - pb0) * t)),
            )
            lut_neutral[v] = (
                int(round(nr0 + (nr1 - nr0) * t)),
                int(round(ng0 + (ng1 - ng0) * t)),
                int(round(nb0 + (nb1 - nb0) * t)),
            )

    return lut_primary, lut_neutral


def recolor_rgb_m3(
    r: int,
    g: int,
    b: int,
    lut_primary: list[tuple[int, int, int]],
    lut_neutral: list[tuple[int, int, int]],
    strength: float = 0.90,
) -> tuple[int, int, int]:
    """
    Apply the Material Design 3 tonal filter to an RGB color (0-255), preserving
    its Rec.601 luminance (for exact parity with Pillow 'L') and tonal separation.
    """
    lum = max(0, min(255, int(round(0.299 * r + 0.587 * g + 0.114 * b))))
    mx = max(r, g, b)
    mn = min(r, g, b)
    sat_hsv = ((mx - mn) / mx) if mx > 0 else 0.0
    sat_w = min(1.0, sat_hsv * 1.8)

    pr, pg, pb = lut_primary[lum]
    nr, ng, nb = lut_neutral[lum]

    tr = nr + (pr - nr) * sat_w
    tg = ng + (pg - ng) * sat_w
    tb = nb + (pb - nb) * sat_w

    s = max(0.0, min(1.0, float(strength)))
    out_r = max(0, min(255, int(round(r + (tr - r) * s))))
    out_g = max(0, min(255, int(round(g + (tg - g) * s))))
    out_b = max(0, min(255, int(round(b + (tb - b) * s))))
    return (out_r, out_g, out_b)
