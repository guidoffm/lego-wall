import pytest

from legowall.mosaic import build_mosaic
from legowall.palette import load_palette
from legowall.parts import build_plan
from legowall.render import instructions_html, render_preview, summary_lines


@pytest.fixture
def plan(halves_image):
    mosaic = build_mosaic(
        halves_image, 32, 16, load_palette("art-16"), dither="none", fit="stretch"
    )
    return build_plan(mosaic, panel_size=16)


def test_preview_size_follows_cell_size(plan):
    image = render_preview(plan.mosaic, cell=10, panel_size=16)
    assert image.size == (320, 160)


def test_preview_rejects_tiny_cells(plan):
    with pytest.raises(ValueError):
        render_preview(plan.mosaic, cell=2)


def test_preview_uses_palette_colors(plan):
    image = render_preview(plan.mosaic, cell=12, shape="square", panel_size=None)
    # Mitte des ersten Studs trägt die Farbe des Mosaiks.
    expected = plan.mosaic.palette[plan.mosaic.indices[0, 0]].rgb
    assert image.getpixel((6, 6)) == expected


def test_summary_mentions_grid_and_plates(plan):
    text = "\n".join(summary_lines(plan))
    assert "32 x 16 Studs" in text
    assert "25.6 x 12.8 cm" in text
    assert "Platte 16x16" in text


def test_summary_warns_on_partial_plates(halves_image):
    mosaic = build_mosaic(halves_image, 20, 20, load_palette("art-16"), dither="none")
    text = "\n".join(summary_lines(build_plan(mosaic, panel_size=16)))
    assert "nicht glatt" in text


def test_instructions_contain_all_panels_and_legend(plan):
    html = instructions_html(plan, preview=render_preview(plan.mosaic, cell=6))
    assert html.startswith("<!doctype html>")
    # 32x16 bei Plattengröße 16 -> zwei Platten.
    assert html.count('<section class="panel">') == 2
    assert "Platte Reihe 1, Spalte 1" in html
    assert "Platte Reihe 1, Spalte 2" in html
    for line in plan.parts:
        assert line.color.hex in html
        assert line.color.name in html
    assert "data:image/png;base64," in html


def test_instructions_escape_the_title(plan):
    html = instructions_html(plan, title='Foto <script>alert("x")</script>')
    assert "<script>alert" not in html
    assert "&lt;script&gt;" in html
