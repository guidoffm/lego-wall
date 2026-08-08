import numpy as np
import pytest
from PIL import Image

from legowall.mosaic import (
    STUD_MM,
    build_mosaic,
    fit_dimensions,
    prepare_pixels,
    quantize,
)
from legowall.palette import load_palette


def test_grid_dimensions_and_physical_size(gradient_image):
    palette = load_palette("art-16")
    mosaic = build_mosaic(gradient_image, 48, 32, palette, dither="none")
    assert mosaic.indices.shape == (32, 48)
    assert mosaic.width == 48 and mosaic.height == 32
    assert mosaic.stud_count == 48 * 32
    assert mosaic.size_mm == (48 * STUD_MM, 32 * STUD_MM)
    assert mosaic.size_cm == pytest.approx((38.4, 25.6))


def test_indices_stay_within_palette(gradient_image):
    palette = load_palette("pab-full")
    mosaic = build_mosaic(gradient_image, 32, 32, palette)
    assert mosaic.indices.min() >= 0
    assert mosaic.indices.max() < len(palette)


def test_pure_colors_map_to_expected_palette_entries(halves_image):
    palette = load_palette("art-16")
    mosaic = build_mosaic(halves_image, 20, 10, palette, dither="none", fit="stretch")
    names = np.array([c.name for c in palette])[mosaic.indices]
    # Reines Rot links, reines Blau rechts — die Palette hat nur je einen Kandidaten.
    assert set(names[:, :10].ravel()) == {"Red"}
    assert set(names[:, 10:].ravel()) == {"Dark Blue"}


def test_quantize_picks_nearest_color():
    palette = load_palette("grayscale-5")
    pixels = np.array([[[255, 255, 255], [0, 0, 0], [160, 165, 169]]], dtype=np.float64)
    indices = quantize(pixels, palette, dither="none")
    assert [palette[i].name for i in indices[0]] == [
        "White",
        "Black",
        "Light Bluish Gray",
    ]


def test_dithering_creates_more_colors_than_flat_mapping():
    # Mittelgrauer Block: ohne Dithering eine Farbe, mit Dithering ein Mischmuster.
    flat = Image.new("RGB", (64, 64), (128, 128, 128))
    palette = load_palette("grayscale-5")
    without = build_mosaic(flat, 32, 32, palette, dither="none")
    with_dither = build_mosaic(flat, 32, 32, palette, dither="floyd-steinberg")
    assert without.used_color_count == 1
    assert with_dither.used_color_count > 1
    # Der Mittelwert bleibt trotz Dithering nahe am Original.
    assert with_dither.to_rgb_array().mean() == pytest.approx(128, abs=12)


def test_max_colors_limits_palette(gradient_image):
    palette = load_palette("pab-full")
    mosaic = build_mosaic(gradient_image, 40, 40, palette, max_colors=6)
    assert mosaic.used_color_count <= 6
    assert len(mosaic.palette) <= 6


def test_max_colors_above_usage_is_noop(halves_image):
    palette = load_palette("art-16")
    mosaic = build_mosaic(halves_image, 16, 16, palette, dither="none", max_colors=30)
    assert len(mosaic.palette) == len(palette)


def test_max_colors_must_be_positive(halves_image):
    with pytest.raises(ValueError):
        build_mosaic(halves_image, 8, 8, load_palette("art-16"), max_colors=0)


@pytest.mark.parametrize("fit", ["cover", "contain", "stretch"])
def test_fit_modes_fill_the_grid(gradient_image, fit):
    palette = load_palette("pab-full")
    mosaic = build_mosaic(gradient_image, 24, 24, palette, fit=fit, dither="none")
    assert mosaic.indices.shape == (24, 24)


def test_contain_uses_background_for_the_border(gradient_image):
    # Breites Bild in ein hohes Raster: oben und unten muss der Hintergrund stehen.
    pixels = prepare_pixels(gradient_image, 20, 60, fit="contain", background="#FF00FF")
    assert tuple(pixels[0, 0].astype(int)) == (255, 0, 255)
    assert tuple(pixels[-1, -1].astype(int)) == (255, 0, 255)


def test_transparency_is_flattened_onto_background():
    image = Image.new("RGBA", (10, 10), (0, 0, 0, 0))
    pixels = prepare_pixels(image, 4, 4, background="#FFFFFF")
    assert (pixels == 255).all()


def test_unknown_fit_and_dither_are_rejected(gradient_image):
    with pytest.raises(ValueError):
        prepare_pixels(gradient_image, 8, 8, fit="quetschen")
    with pytest.raises(ValueError):
        quantize(np.zeros((2, 2, 3)), load_palette("art-16"), dither="ordered")


def test_zero_dimensions_are_rejected(gradient_image):
    with pytest.raises(ValueError):
        prepare_pixels(gradient_image, 0, 10)


def test_fit_dimensions_derives_missing_edge():
    assert fit_dimensions((200, 100), 40, None) == (40, 20)
    assert fit_dimensions((200, 100), None, 20) == (40, 20)
    assert fit_dimensions((200, 100), 48, 48) == (48, 48)
    with pytest.raises(ValueError):
        fit_dimensions((200, 100), None, None)


def test_fit_dimensions_never_returns_zero():
    assert fit_dimensions((1000, 10), 5, None) == (5, 1)


def test_saturation_zero_gives_neutral_pixels(gradient_image):
    pixels = prepare_pixels(gradient_image, 16, 16, saturation=0.0)
    spread = pixels.max(axis=2) - pixels.min(axis=2)
    assert spread.max() <= 1.0


def test_to_image_matches_indices(halves_image):
    palette = load_palette("art-16")
    mosaic = build_mosaic(halves_image, 8, 8, palette, dither="none", fit="stretch")
    image = mosaic.to_image()
    assert image.size == (8, 8)
    assert image.getpixel((0, 0)) == palette[mosaic.indices[0, 0]].rgb
