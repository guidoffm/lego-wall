"""Visualisierung: Vorschaubild und druckbare Bauanleitung."""

from __future__ import annotations

import base64
import html
import io
from typing import Literal

import numpy as np
from PIL import Image, ImageDraw

from .mosaic import Mosaic
from .parts import BASEPLATES, BuildPlan

StudShape = Literal["round", "square"]


def render_preview(
    mosaic: Mosaic,
    *,
    cell: int = 12,
    shape: StudShape = "round",
    panel_size: int | None = None,
    background: str = "#20232A",
) -> Image.Image:
    """Vorschau mit sichtbaren Studs.

    ``panel_size`` zeichnet zusätzlich die Trennlinien der Trägerplatten,
    damit man beim Bauen sieht, wo eine Platte endet.
    """
    if cell < 3:
        raise ValueError("cell muss mindestens 3 Pixel sein")

    width_px = mosaic.width * cell
    height_px = mosaic.height * cell
    image = Image.new("RGB", (width_px, height_px), background)
    draw = ImageDraw.Draw(image)

    rgb = mosaic.to_rgb_array()
    inset = max(1, cell // 12)
    for y in range(mosaic.height):
        for x in range(mosaic.width):
            color = tuple(int(v) for v in rgb[y, x])
            box = (
                x * cell + inset,
                y * cell + inset,
                (x + 1) * cell - inset - 1,
                (y + 1) * cell - inset - 1,
            )
            if shape == "round":
                draw.ellipse(box, fill=color)
            else:
                draw.rectangle(box, fill=color)

    if panel_size:
        for x in range(panel_size, mosaic.width, panel_size):
            draw.line([(x * cell, 0), (x * cell, height_px)], fill="#FF3B30", width=1)
        for y in range(panel_size, mosaic.height, panel_size):
            draw.line([(0, y * cell), (width_px, y * cell)], fill="#FF3B30", width=1)

    return image


def bytes_to_data_uri(data: bytes, mime: str) -> str:
    """Beliebige Nutzdaten als Data-URI — damit kommen Downloads ohne Serverzustand aus."""
    encoded = base64.b64encode(data).decode("ascii")
    return f"data:{mime};base64,{encoded}"


def data_uri_size(data: bytes) -> int:
    """Platz, den ``data`` als Base64 in der Seite belegt."""
    return (len(data) + 2) // 3 * 4


def image_to_data_uri(image: Image.Image, fmt: str = "PNG") -> str:
    buffer = io.BytesIO()
    image.save(buffer, format=fmt)
    return bytes_to_data_uri(buffer.getvalue(), f"image/{fmt.lower()}")


def text_to_data_uri(text: str, mime: str) -> str:
    return bytes_to_data_uri(text.encode("utf-8"), mime)


def _text_color(color) -> str:
    return "#111111" if color.is_light else "#FFFFFF"


def summary_lines(plan: BuildPlan) -> list[str]:
    """Kurzüberblick als Textzeilen — für CLI-Ausgabe und Web-Kopfzeile."""
    mosaic = plan.mosaic
    width_cm, height_cm = mosaic.size_cm
    baseplate = BASEPLATES.get(plan.panels.panel_size)
    plate_label = (
        baseplate["label"]
        if baseplate
        else f"Platte {plan.panels.panel_size}x{plan.panels.panel_size}"
    )
    lines = [
        f"Raster:        {mosaic.width} x {mosaic.height} Studs ({mosaic.stud_count} Elemente)",
        f"Wandbild:      {width_cm:.1f} x {height_cm:.1f} cm",
        f"Palette:       {mosaic.palette.name} — {mosaic.used_color_count} Farben verwendet",
        f"Element:       {plan.element_info['label']} — Teil {plan.element_info['part']}",
        f"Trägerplatten: {plan.panels.total}x {plate_label} "
        f"({plan.panels.columns} x {plan.panels.rows})",
    ]
    if not plan.panels.is_exact:
        lines.append(
            "Hinweis:       Raster geht nicht glatt in die Trägerplatten auf — "
            "Randplatten bleiben teilweise unbelegt."
        )
    return lines


def _legend_html(plan: BuildPlan) -> str:
    rows = []
    for line in plan.parts:
        color = line.color
        rows.append(
            "<tr>"
            f'<td class="code" style="background:{color.hex};color:{_text_color(color)}">{line.code}</td>'
            f"<td>{html.escape(color.label)}</td>"
            f"<td class=\"mono\">{color.hex}</td>"
            f"<td class=\"mono\">{color.bricklink_id if color.bricklink_id is not None else '—'}</td>"
            f"<td class=\"num\">{line.count}</td>"
            f'<td class="num">{line.share * 100:.1f}%</td>'
            "</tr>"
        )
    return "".join(rows)


def _panel_grid_html(plan: BuildPlan, panel_column: int, panel_row: int) -> str:
    size = plan.panels.panel_size
    x0, y0 = panel_column * size, panel_row * size
    block = plan.mosaic.indices[y0 : y0 + size, x0 : x0 + size]

    header = "".join(f"<th>{x0 + x + 1}</th>" for x in range(block.shape[1]))
    body = []
    for y, row in enumerate(block):
        cells = []
        for index in row:
            color = plan.mosaic.palette[int(index)]
            cells.append(
                f'<td style="background:{color.hex};color:{_text_color(color)}">'
                f"{plan.code_for(index)}</td>"
            )
        body.append(f"<tr><th>{y0 + y + 1}</th>{''.join(cells)}</tr>")

    return (
        '<table class="grid"><thead><tr><th></th>'
        + header
        + "</tr></thead><tbody>"
        + "".join(body)
        + "</tbody></table>"
    )


def _panel_runs_html(plan: BuildPlan, panel_column: int, panel_row: int) -> str:
    size = plan.panels.panel_size
    rows = []
    for offset, runs in enumerate(plan.rows_for_panel(panel_column, panel_row)):
        parts = " · ".join(
            f'<span class="run"><span class="swatch" style="background:{run.color.hex}"></span>'
            f"{run.count}× {run.code}</span>"
            for run in runs
        )
        rows.append(
            f'<li><span class="rowno">Reihe {panel_row * size + offset + 1}</span>{parts}</li>'
        )
    return '<ol class="runs">' + "".join(rows) + "</ol>"


def instructions_html(
    plan: BuildPlan,
    *,
    preview: Image.Image | None = None,
    title: str = "LEGO-Wandbild — Bauanleitung",
) -> str:
    """Vollständige, druckbare Bauanleitung als eigenständige HTML-Datei."""
    mosaic = plan.mosaic
    preview_html = ""
    if preview is not None:
        preview_html = (
            f'<img class="preview" src="{image_to_data_uri(preview)}" alt="Vorschau des Mosaiks">'
        )

    panels = []
    for panel_row in range(plan.panels.rows):
        for panel_column in range(plan.panels.columns):
            panels.append(
                "<section class=\"panel\">"
                f"<h3>Platte Reihe {panel_row + 1}, Spalte {panel_column + 1} "
                f"<small>Spalten {panel_column * plan.panels.panel_size + 1}–"
                f"{min((panel_column + 1) * plan.panels.panel_size, mosaic.width)}, "
                f"Reihen {panel_row * plan.panels.panel_size + 1}–"
                f"{min((panel_row + 1) * plan.panels.panel_size, mosaic.height)}</small></h3>"
                + _panel_grid_html(plan, panel_column, panel_row)
                + _panel_runs_html(plan, panel_column, panel_row)
                + "</section>"
            )

    summary = "".join(f"<li>{html.escape(line)}</li>" for line in summary_lines(plan))

    return f"""<!doctype html>
<html lang="de">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(title)}</title>
<style>
  :root {{ color-scheme: light; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
         margin: 0 auto; padding: 2rem 1.5rem 4rem; max-width: 1100px; color: #111; background: #fff; }}
  h1 {{ font-size: 1.6rem; margin-bottom: .25rem; }}
  h2 {{ font-size: 1.2rem; margin-top: 2.5rem; border-bottom: 2px solid #eee; padding-bottom: .3rem; }}
  h3 {{ font-size: 1rem; margin-bottom: .5rem; }}
  h3 small {{ font-weight: 400; color: #666; margin-left: .5rem; }}
  ul.summary {{ list-style: none; padding: 0; font-variant-numeric: tabular-nums; }}
  ul.summary li {{ padding: .15rem 0; white-space: pre-wrap; font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: .85rem; }}
  img.preview {{ max-width: 100%; height: auto; image-rendering: pixelated; border: 1px solid #ddd; border-radius: 6px; }}
  table {{ border-collapse: collapse; }}
  table.legend {{ width: 100%; font-size: .9rem; }}
  table.legend th, table.legend td {{ border-bottom: 1px solid #eee; padding: .35rem .5rem; text-align: left; }}
  table.legend td.code {{ text-align: center; font-weight: 700; width: 2.5rem; border-radius: 3px; }}
  .num {{ text-align: right !important; font-variant-numeric: tabular-nums; }}
  .mono {{ font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: .8rem; }}
  .panel {{ margin: 1.5rem 0 2.5rem; page-break-inside: avoid; }}
  table.grid {{ font-size: .55rem; table-layout: fixed; }}
  table.grid th {{ color: #999; font-weight: 400; font-size: .5rem; padding: 0 1px; }}
  table.grid td {{ width: 1.1rem; height: 1.1rem; text-align: center; border: 1px solid rgba(0,0,0,.12); }}
  .grid-wrap {{ overflow-x: auto; }}
  ol.runs {{ font-size: .8rem; padding-left: 1.2rem; margin-top: .75rem; list-style: none; }}
  ol.runs li {{ padding: .1rem 0; }}
  .rowno {{ display: inline-block; min-width: 5.5rem; color: #666; }}
  .run {{ white-space: nowrap; margin-right: .1rem; }}
  .swatch {{ display: inline-block; width: .6rem; height: .6rem; border: 1px solid rgba(0,0,0,.25);
             border-radius: 2px; margin-right: .2rem; vertical-align: baseline; }}
  footer {{ margin-top: 3rem; color: #777; font-size: .8rem; border-top: 1px solid #eee; padding-top: 1rem; }}
  @media print {{ body {{ padding: 0; }} .panel {{ page-break-after: always; }} }}
</style>
</head>
<body>
<h1>{html.escape(title)}</h1>
<ul class="summary">{summary}</ul>
{preview_html}

<h2>Stückliste</h2>
<table class="legend">
<thead><tr><th>Code</th><th>Farbe</th><th>Hex</th><th>BL-ID</th><th class="num">Anzahl</th><th class="num">Anteil</th></tr></thead>
<tbody>{_legend_html(plan)}</tbody>
</table>

<h2>Bauanleitung nach Platten</h2>
<p>Jede Platte wird von oben nach unten gebaut. Die Reihenangaben zählen die
Anzahl gleichfarbiger Elemente in Folge von links nach rechts.</p>
<div class="grid-wrap">{''.join(panels)}</div>

<footer>
Erzeugt mit legowall. Farbwerte und Teile-IDs sind Annäherungen aus öffentlichen
Datenquellen — vor dem Bestellen bei BrickLink bzw. Pick a Brick prüfen.
</footer>
</body>
</html>
"""
