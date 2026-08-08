"""Bild -> Mosaik: skalieren, auf die LEGO-Palette reduzieren, Ergebnis kapseln."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import numpy as np
from PIL import Image, ImageEnhance, ImageOps

from .color import hex_to_rgb, srgb_to_lab
from .palette import Palette

FitMode = Literal["cover", "contain", "stretch"]
DitherMode = Literal["none", "floyd-steinberg"]

# Kantenlänge eines Studs in Millimetern (LEGO-Raster: 8 mm).
STUD_MM = 8.0

# Auflösung der RGB-Nachschlagetabelle pro Kanal. 64 Stufen (Schrittweite 4)
# bleiben deutlich unter der Farbtoleranz des Auges und machen die
# Fehlerdiffusion um Größenordnungen schneller als eine Suche pro Pixel.
_LUT_BITS = 6
_LUT_LEVELS = 1 << _LUT_BITS
_LUT_STEP = 256 // _LUT_LEVELS


@dataclass(frozen=True)
class Mosaic:
    """Fertig gerastertes Mosaik.

    ``indices`` ist ein (height, width)-Array mit Indizes in ``palette``.
    """

    indices: np.ndarray
    palette: Palette

    @property
    def height(self) -> int:
        return int(self.indices.shape[0])

    @property
    def width(self) -> int:
        return int(self.indices.shape[1])

    @property
    def stud_count(self) -> int:
        return self.width * self.height

    @property
    def size_mm(self) -> tuple[float, float]:
        return (self.width * STUD_MM, self.height * STUD_MM)

    @property
    def size_cm(self) -> tuple[float, float]:
        w, h = self.size_mm
        return (w / 10.0, h / 10.0)

    @property
    def used_color_count(self) -> int:
        return int(np.unique(self.indices).size)

    def to_rgb_array(self) -> np.ndarray:
        """(height, width, 3) uint8 — das Mosaik als Bilddaten."""
        return self.palette.rgb.astype(np.uint8)[self.indices]

    def to_image(self) -> Image.Image:
        """Mosaik als Bild mit 1 Pixel pro Stud."""
        return Image.fromarray(self.to_rgb_array(), mode="RGB")


def _nearest_index_lut(palette: Palette) -> np.ndarray:
    """Nachschlagetabelle (LEVELS^3,) mit dem nächsten Palettenindex je RGB-Zelle.

    Die Zellmittelpunkte werden nach Lab konvertiert und gegen alle
    Palettenfarben verglichen; gerechnet wird blockweise, damit die
    Distanzmatrix klein bleibt.
    """
    axis = np.arange(_LUT_LEVELS, dtype=np.float64) * _LUT_STEP + _LUT_STEP / 2.0
    grid = np.stack(np.meshgrid(axis, axis, axis, indexing="ij"), axis=-1)
    cells = grid.reshape(-1, 3)

    palette_lab = palette.lab
    result = np.empty(cells.shape[0], dtype=np.int32)
    block = 8192
    for start in range(0, cells.shape[0], block):
        chunk_lab = srgb_to_lab(cells[start : start + block])
        distances = ((chunk_lab[:, None, :] - palette_lab[None, :, :]) ** 2).sum(axis=2)
        result[start : start + block] = np.argmin(distances, axis=1)
    return result.reshape(_LUT_LEVELS, _LUT_LEVELS, _LUT_LEVELS)


def _map_direct(pixels: np.ndarray, lut: np.ndarray) -> np.ndarray:
    """Jeden Pixel ohne Fehlerdiffusion auf die nächste Palettenfarbe abbilden."""
    cells = (np.clip(pixels, 0, 255).astype(np.int32)) // _LUT_STEP
    return lut[cells[..., 0], cells[..., 1], cells[..., 2]].astype(np.int32)


def _map_floyd_steinberg(
    pixels: np.ndarray, lut: np.ndarray, palette_rgb: np.ndarray
) -> np.ndarray:
    """Floyd-Steinberg mit Serpentinen-Abtastung.

    Der Quantisierungsfehler wird auf die noch nicht besuchten Nachbarpixel
    verteilt; dadurch entstehen Mischtöne, die die kleine Palette optisch
    erweitern.
    """
    work = pixels.astype(np.float64).copy()
    height, width = work.shape[:2]
    indices = np.zeros((height, width), dtype=np.int32)

    for y in range(height):
        left_to_right = y % 2 == 0
        columns = range(width) if left_to_right else range(width - 1, -1, -1)
        ahead = 1 if left_to_right else -1
        for x in columns:
            old = work[y, x]
            cell = np.clip(old, 0, 255).astype(np.int32) // _LUT_STEP
            index = int(lut[cell[0], cell[1], cell[2]])
            indices[y, x] = index
            error = old - palette_rgb[index]

            nx = x + ahead
            if 0 <= nx < width:
                work[y, nx] += error * (7.0 / 16.0)
            if y + 1 < height:
                if 0 <= x - ahead < width:
                    work[y + 1, x - ahead] += error * (3.0 / 16.0)
                work[y + 1, x] += error * (5.0 / 16.0)
                if 0 <= nx < width:
                    work[y + 1, nx] += error * (1.0 / 16.0)
    return indices


def prepare_pixels(
    image: Image.Image,
    width: int,
    height: int,
    *,
    fit: FitMode = "cover",
    background: str = "#FFFFFF",
    brightness: float = 1.0,
    contrast: float = 1.0,
    saturation: float = 1.0,
) -> np.ndarray:
    """Bild auf das Stud-Raster verkleinern und Tonwerte anpassen.

    Rückgabe: (height, width, 3) float64 mit sRGB-Werten 0..255.
    """
    if width < 1 or height < 1:
        raise ValueError("Breite und Höhe müssen mindestens 1 Stud betragen")

    prepared = ImageOps.exif_transpose(image)
    background_rgb = hex_to_rgb(background)

    # Transparenz auf die Hintergrundfarbe legen, damit keine schwarzen Ränder entstehen.
    if prepared.mode in ("RGBA", "LA", "P"):
        prepared = prepared.convert("RGBA")
        flat = Image.new("RGB", prepared.size, background_rgb)
        flat.paste(prepared, mask=prepared.getchannel("A"))
        prepared = flat
    else:
        prepared = prepared.convert("RGB")

    if fit == "stretch":
        prepared = prepared.resize((width, height), Image.LANCZOS)
    elif fit == "cover":
        prepared = ImageOps.fit(
            prepared, (width, height), method=Image.LANCZOS, centering=(0.5, 0.5)
        )
    elif fit == "contain":
        prepared = ImageOps.contain(prepared, (width, height), method=Image.LANCZOS)
        canvas = Image.new("RGB", (width, height), background_rgb)
        canvas.paste(
            prepared,
            ((width - prepared.width) // 2, (height - prepared.height) // 2),
        )
        prepared = canvas
    else:
        raise ValueError(f"Unbekannter Fit-Modus: {fit!r}")

    for factor, enhancer in (
        (brightness, ImageEnhance.Brightness),
        (contrast, ImageEnhance.Contrast),
        (saturation, ImageEnhance.Color),
    ):
        if factor != 1.0:
            prepared = enhancer(prepared).enhance(factor)

    return np.asarray(prepared, dtype=np.float64)


def quantize(
    pixels: np.ndarray,
    palette: Palette,
    *,
    dither: DitherMode = "floyd-steinberg",
) -> np.ndarray:
    """Pixelfeld auf Palettenindizes abbilden."""
    lut = _nearest_index_lut(palette)
    if dither == "none":
        return _map_direct(pixels, lut)
    if dither == "floyd-steinberg":
        return _map_floyd_steinberg(pixels, lut, palette.rgb)
    raise ValueError(f"Unbekannter Dither-Modus: {dither!r}")


def build_mosaic(
    image: Image.Image,
    width: int,
    height: int,
    palette: Palette,
    *,
    fit: FitMode = "cover",
    dither: DitherMode = "floyd-steinberg",
    max_colors: int | None = None,
    background: str = "#FFFFFF",
    brightness: float = 1.0,
    contrast: float = 1.0,
    saturation: float = 1.0,
) -> Mosaic:
    """Kompletter Weg von der Bilddatei zum fertigen Mosaik.

    Mit ``max_colors`` wird zweistufig gearbeitet: erst mit der vollen
    Palette quantisieren, dann die häufigsten Farben behalten und mit
    dieser Teilpalette erneut quantisieren. Das liefert bessere Ergebnisse
    als ein bloßes Umbiegen der seltenen Farben, weil die Fehlerdiffusion
    die Beschränkung mitbekommt.
    """
    pixels = prepare_pixels(
        image,
        width,
        height,
        fit=fit,
        background=background,
        brightness=brightness,
        contrast=contrast,
        saturation=saturation,
    )
    indices = quantize(pixels, palette, dither=dither)

    if max_colors is not None:
        if max_colors < 1:
            raise ValueError("max_colors muss mindestens 1 sein")
        counts = np.bincount(indices.ravel(), minlength=len(palette))
        used = np.flatnonzero(counts)
        if used.size > max_colors:
            keep = used[np.argsort(counts[used])[::-1][:max_colors]]
            palette, _ = palette.subset(keep)
            indices = quantize(pixels, palette, dither=dither)

    return Mosaic(indices=indices, palette=palette)


def fit_dimensions(
    image_size: tuple[int, int],
    width: int | None,
    height: int | None,
) -> tuple[int, int]:
    """Fehlende Kantenlänge aus dem Seitenverhältnis des Bildes ergänzen."""
    source_width, source_height = image_size
    if width and height:
        return width, height
    if width:
        return width, max(1, round(width * source_height / source_width))
    if height:
        return max(1, round(height * source_width / source_height)), height
    raise ValueError("Mindestens Breite oder Höhe muss angegeben werden")
