"""Farbraum-Umrechnungen (sRGB -> CIE Lab) für die Farbzuordnung.

Die Zuordnung Bildpixel -> LEGO-Farbe passiert in CIE Lab, weil dort
euklidische Abstände der wahrgenommenen Farbdifferenz näher kommen als
in RGB. Alle Funktionen arbeiten vektorisiert auf numpy-Arrays.
"""

from __future__ import annotations

import numpy as np

# D65-Weißpunkt (Tageslicht), wie für sRGB definiert.
_WHITE_D65 = np.array([0.95047, 1.00000, 1.08883], dtype=np.float64)

# sRGB (linear) -> XYZ
_RGB_TO_XYZ = np.array(
    [
        [0.4124564, 0.3575761, 0.1804375],
        [0.2126729, 0.7151522, 0.0721750],
        [0.0193339, 0.1191920, 0.9503041],
    ],
    dtype=np.float64,
)


def hex_to_rgb(value: str) -> tuple[int, int, int]:
    """'#A0A5A9' oder 'A0A5A9' -> (160, 165, 169)."""
    text = value.strip().lstrip("#")
    if len(text) != 6:
        raise ValueError(f"Ungültiger Hex-Farbwert: {value!r}")
    return tuple(int(text[i : i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]


def rgb_to_hex(rgb) -> str:
    r, g, b = (int(round(float(c))) for c in rgb)
    return f"#{r:02X}{g:02X}{b:02X}"


def srgb_to_linear(rgb: np.ndarray) -> np.ndarray:
    """sRGB 0..255 -> lineares RGB 0..1."""
    c = np.asarray(rgb, dtype=np.float64) / 255.0
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


def srgb_to_lab(rgb: np.ndarray) -> np.ndarray:
    """sRGB 0..255 (..., 3) -> CIE Lab (..., 3), D65."""
    linear = srgb_to_linear(rgb)
    xyz = linear @ _RGB_TO_XYZ.T / _WHITE_D65

    eps = 216.0 / 24389.0
    kappa = 24389.0 / 27.0
    f = np.where(xyz > eps, np.cbrt(xyz), (kappa * xyz + 16.0) / 116.0)

    fx, fy, fz = f[..., 0], f[..., 1], f[..., 2]
    return np.stack(
        [116.0 * fy - 16.0, 500.0 * (fx - fy), 200.0 * (fy - fz)], axis=-1
    )


def relative_luminance(rgb) -> float:
    """Relative Helligkeit 0..1 — entscheidet, ob Text auf der Farbe hell oder dunkel sein muss."""
    linear = srgb_to_linear(np.asarray(rgb, dtype=np.float64))
    return float(linear @ np.array([0.2126, 0.7152, 0.0722]))
