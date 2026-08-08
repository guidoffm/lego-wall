import json

import numpy as np
import pytest

from legowall.color import hex_to_rgb, rgb_to_hex, srgb_to_lab
from legowall.palette import available_palettes, load_palette


def test_hex_roundtrip():
    assert hex_to_rgb("#A0A5A9") == (160, 165, 169)
    assert hex_to_rgb("a0a5a9") == (160, 165, 169)
    assert rgb_to_hex((160, 165, 169)) == "#A0A5A9"


def test_hex_rejects_garbage():
    with pytest.raises(ValueError):
        hex_to_rgb("#12345")


def test_lab_reference_values():
    lab = srgb_to_lab(np.array([[255, 255, 255], [0, 0, 0], [255, 0, 0]], dtype=np.float64))
    # Weiß: L=100, a=b=0. Schwarz: L=0. Rot: bekannte sRGB-Referenz.
    assert lab[0] == pytest.approx([100.0, 0.0, 0.0], abs=0.05)
    assert lab[1] == pytest.approx([0.0, 0.0, 0.0], abs=0.05)
    assert lab[2] == pytest.approx([53.24, 80.09, 67.20], abs=0.1)


def test_bundled_palettes_are_wellformed():
    palettes = available_palettes()
    assert {p.id for p in palettes} >= {"pab-full", "art-16", "grayscale-5"}
    for palette in palettes:
        assert len(palette) >= 1
        assert palette.lab.shape == (len(palette), 3)
        hexes = [c.hex for c in palette]
        assert len(set(hexes)) == len(hexes), f"Doppelte Farbe in {palette.id}"
        names = [c.name for c in palette]
        assert len(set(names)) == len(names), f"Doppelter Name in {palette.id}"


def test_grayscale_palette_is_neutral():
    palette = load_palette("grayscale-5")
    assert len(palette) == 5
    # Chroma bleibt klein — LEGO-Schwarz ist bewusst leicht bläulich (#05131D),
    # deshalb reicht die Schranke nicht bis null.
    assert np.abs(palette.lab[:, 1:]).max() < 10.0
    # Die Helligkeiten decken den ganzen Bereich ab und sind absteigend sortiert.
    lightness = palette.lab[:, 0]
    assert lightness[0] > 95 and lightness[-1] < 10
    assert list(lightness) == sorted(lightness, reverse=True)


def test_subset_keeps_order_and_maps_indices():
    palette = load_palette("pab-full")
    reduced, mapping = palette.subset([5, 1, 1])
    assert [c.name for c in reduced] == [palette[1].name, palette[5].name]
    assert mapping[1] == 0 and mapping[5] == 1
    assert mapping[0] == -1


def test_subset_rejects_empty():
    with pytest.raises(ValueError):
        load_palette("art-16").subset([])


def test_load_custom_palette(tmp_path):
    path = tmp_path / "custom.json"
    path.write_text(
        json.dumps(
            {
                "id": "custom",
                "name": "Test",
                "colors": [
                    {"name": "Black", "hex": "#000000", "bricklink_id": 11},
                    {"name": "White", "hex": "#FFFFFF", "bricklink_id": 1},
                ],
            }
        ),
        encoding="utf-8",
    )
    palette = load_palette(path)
    assert len(palette) == 2
    assert palette[0].name == "Black"


def test_unknown_palette_raises():
    with pytest.raises(ValueError, match="Unbekannte Palette"):
        load_palette("gibtsnicht")


def test_label_and_lightness():
    palette = load_palette("grayscale-5")
    white, black = palette[0], palette[4]
    assert white.is_light and not black.is_light
    assert white.label == "Weiß (White)"
