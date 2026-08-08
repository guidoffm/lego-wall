"""legowall — Bilder in LEGO-Wandbilder umrechnen.

Kernbausteine:

* :mod:`legowall.palette` — LEGO-Farbpaletten
* :mod:`legowall.mosaic`  — Skalierung und Farbreduktion
* :mod:`legowall.parts`   — Stückliste, Plattenbedarf, Exportformate
* :mod:`legowall.render`  — Vorschau und Bauanleitung
"""

from .mosaic import Mosaic, build_mosaic, fit_dimensions, prepare_pixels, quantize
from .palette import LegoColor, Palette, available_palettes, load_palette
from .parts import BuildPlan, build_plan, bricklink_wanted_list_xml, parts_csv, parts_json
from .render import instructions_html, render_preview, summary_lines

__version__ = "1.0.0"

__all__ = [
    "BuildPlan",
    "LegoColor",
    "Mosaic",
    "Palette",
    "available_palettes",
    "bricklink_wanted_list_xml",
    "build_mosaic",
    "build_plan",
    "fit_dimensions",
    "instructions_html",
    "load_palette",
    "parts_csv",
    "parts_json",
    "prepare_pixels",
    "quantize",
    "render_preview",
    "summary_lines",
]
