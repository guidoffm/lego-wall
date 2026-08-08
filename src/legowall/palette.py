"""LEGO-Farbpaletten: Laden, Auflisten, Teilmengen bilden."""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path

import numpy as np

from .color import hex_to_rgb, relative_luminance, srgb_to_lab

PALETTE_DIR = Path(__file__).parent / "palettes"
DEFAULT_PALETTE = "pab-full"


@dataclass(frozen=True)
class LegoColor:
    """Eine einzelne LEGO-Farbe inklusive Bestell-IDs."""

    name: str
    hex: str
    name_de: str | None = None
    lego_id: int | None = None
    bricklink_id: int | None = None

    @property
    def rgb(self) -> tuple[int, int, int]:
        return hex_to_rgb(self.hex)

    @property
    def label(self) -> str:
        """Anzeigename: deutscher Name mit englischem Original in Klammern."""
        if self.name_de and self.name_de != self.name:
            return f"{self.name_de} ({self.name})"
        return self.name

    @property
    def is_light(self) -> bool:
        return relative_luminance(self.rgb) > 0.45


@dataclass(frozen=True)
class Palette:
    """Eine Menge von LEGO-Farben, aus der das Mosaik gebaut wird."""

    id: str
    name: str
    colors: tuple[LegoColor, ...]
    description: str = ""
    source: str = ""

    def __len__(self) -> int:
        return len(self.colors)

    def __getitem__(self, index: int) -> LegoColor:
        return self.colors[index]

    def __iter__(self):
        return iter(self.colors)

    @cached_property
    def rgb(self) -> np.ndarray:
        """(K, 3) float64 — RGB-Werte aller Farben."""
        return np.array([c.rgb for c in self.colors], dtype=np.float64)

    @cached_property
    def lab(self) -> np.ndarray:
        """(K, 3) float64 — Lab-Werte aller Farben."""
        return srgb_to_lab(self.rgb)

    def subset(self, indices) -> tuple["Palette", np.ndarray]:
        """Teilpalette aus den angegebenen Indizes.

        Gibt die neue Palette und das Index-Mapping (alt -> neu) zurück.
        """
        ordered = sorted(dict.fromkeys(int(i) for i in indices))
        if not ordered:
            raise ValueError("Teilpalette braucht mindestens eine Farbe")
        mapping = np.full(len(self.colors), -1, dtype=np.int32)
        for new_index, old_index in enumerate(ordered):
            mapping[old_index] = new_index
        reduced = Palette(
            id=f"{self.id}-subset{len(ordered)}",
            name=f"{self.name} ({len(ordered)} Farben)",
            colors=tuple(self.colors[i] for i in ordered),
            description=self.description,
            source=self.source,
        )
        return reduced, mapping


def _palette_from_dict(data: dict, fallback_id: str) -> Palette:
    colors = tuple(
        LegoColor(
            name=entry["name"],
            hex=entry["hex"],
            name_de=entry.get("name_de"),
            lego_id=entry.get("lego_id"),
            bricklink_id=entry.get("bricklink_id"),
        )
        for entry in data["colors"]
    )
    if not colors:
        raise ValueError("Palette enthält keine Farben")
    return Palette(
        id=data.get("id", fallback_id),
        name=data.get("name", fallback_id),
        colors=colors,
        description=data.get("description", ""),
        source=data.get("source", ""),
    )


def available_palettes() -> list[Palette]:
    """Alle mitgelieferten Paletten, sortiert nach Farbanzahl."""
    palettes = [load_palette(path.stem) for path in sorted(PALETTE_DIR.glob("*.json"))]
    return sorted(palettes, key=lambda p: len(p))


def load_palette(name_or_path: str | Path = DEFAULT_PALETTE) -> Palette:
    """Palette laden — entweder eine mitgelieferte (über ihre ID) oder eine JSON-Datei."""
    candidate = Path(name_or_path)
    if candidate.suffix.lower() == ".json":
        if not candidate.is_file():
            raise FileNotFoundError(f"Palettendatei nicht gefunden: {candidate}")
        path = candidate
    else:
        path = PALETTE_DIR / f"{candidate.name}.json"
        if not path.is_file():
            known = ", ".join(p.stem for p in sorted(PALETTE_DIR.glob("*.json")))
            raise ValueError(f"Unbekannte Palette {name_or_path!r}. Verfügbar: {known}")
    with path.open(encoding="utf-8") as handle:
        return _palette_from_dict(json.load(handle), path.stem)
