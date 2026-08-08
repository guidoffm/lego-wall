"""Stückliste, Platten-Bedarf und Export-Formate für die Bestellung."""

from __future__ import annotations

import csv
import io
import json
import math
from dataclasses import dataclass, field
from xml.etree import ElementTree as ET

import numpy as np

from .mosaic import STUD_MM, Mosaic
from .palette import LegoColor

# Auswählbare 1x1-Elemente für die Mosaikfläche. Die Nummern sind die
# BrickLink-/LEGO-Designnummern der jeweiligen Teile.
ELEMENTS: dict[str, dict[str, str]] = {
    "tile-round-1x1": {
        "part": "98138",
        "label": "Fliese rund 1x1 (Tile Round 1x1)",
        "note": "Von LEGO Art verwendet — glatte Oberfläche, keine sichtbaren Noppen.",
    },
    "plate-round-1x1": {
        "part": "6141",
        "label": "Platte rund 1x1 (Plate Round 1x1)",
        "note": "Günstige Alternative, Noppe bleibt sichtbar.",
    },
    "plate-1x1": {
        "part": "3024",
        "label": "Platte 1x1 (Plate 1x1)",
        "note": "Eckiges Raster, sehr breit verfügbar.",
    },
    "tile-1x1": {
        "part": "3070b",
        "label": "Fliese 1x1 (Tile 1x1)",
        "note": "Eckig und glatt — ergibt eine geschlossene Fläche.",
    },
}
DEFAULT_ELEMENT = "tile-round-1x1"

# Trägerplatten, auf die das Mosaik gebaut wird.
BASEPLATES: dict[int, dict[str, str]] = {
    16: {"part": "91405", "label": "Platte 16x16"},
    32: {"part": "3867", "label": "Platte 32x32"},
    48: {"part": "4186", "label": "Bauplatte 48x48"},
}
DEFAULT_PANEL_SIZE = 16


@dataclass(frozen=True)
class PartLine:
    """Eine Zeile der Stückliste."""

    color: LegoColor
    count: int
    share: float
    code: str


@dataclass(frozen=True)
class PanelPlan:
    """Aufteilung der Fläche in Trägerplatten."""

    panel_size: int
    columns: int
    rows: int
    partial_columns: int
    partial_rows: int

    @property
    def total(self) -> int:
        return self.columns * self.rows

    @property
    def is_exact(self) -> bool:
        return self.partial_columns == 0 and self.partial_rows == 0


@dataclass(frozen=True)
class Run:
    """Zusammenhängende Folge gleicher Farbe innerhalb einer Reihe."""

    code: str
    color: LegoColor
    count: int


@dataclass(frozen=True)
class BuildPlan:
    """Alles, was zum Bestellen und Bauen gebraucht wird."""

    mosaic: Mosaic
    parts: list[PartLine]
    panels: PanelPlan
    element: str = DEFAULT_ELEMENT
    codes: dict[int, str] = field(default_factory=dict)

    @property
    def element_info(self) -> dict[str, str]:
        return ELEMENTS[self.element]

    @property
    def total_studs(self) -> int:
        return self.mosaic.stud_count

    def code_for(self, index: int) -> str:
        return self.codes[int(index)]

    def rows_for_panel(self, panel_column: int, panel_row: int) -> list[list[Run]]:
        """Reihenweise Bauanleitung für eine einzelne Trägerplatte."""
        size = self.panels.panel_size
        x0, y0 = panel_column * size, panel_row * size
        block = self.mosaic.indices[y0 : y0 + size, x0 : x0 + size]
        return [self._runs(row) for row in block]

    def _runs(self, row: np.ndarray) -> list[Run]:
        runs: list[Run] = []
        for index in row:
            index = int(index)
            if runs and runs[-1].code == self.codes[index]:
                previous = runs[-1]
                runs[-1] = Run(previous.code, previous.color, previous.count + 1)
            else:
                runs.append(Run(self.codes[index], self.mosaic.palette[index], 1))
        return runs


def _color_codes(count: int) -> list[str]:
    """Kurzcodes A, B, ... Z, AA, AB, ... für die Legende."""
    codes = []
    for i in range(count):
        if i < 26:
            codes.append(chr(ord("A") + i))
        else:
            codes.append(chr(ord("A") + i // 26 - 1) + chr(ord("A") + i % 26))
    return codes


def plan_panels(width: int, height: int, panel_size: int = DEFAULT_PANEL_SIZE) -> PanelPlan:
    """Wie viele Trägerplatten der angegebenen Größe werden gebraucht."""
    if panel_size < 1:
        raise ValueError("panel_size muss mindestens 1 sein")
    return PanelPlan(
        panel_size=panel_size,
        columns=math.ceil(width / panel_size),
        rows=math.ceil(height / panel_size),
        partial_columns=width % panel_size,
        partial_rows=height % panel_size,
    )


def build_plan(
    mosaic: Mosaic,
    *,
    element: str = DEFAULT_ELEMENT,
    panel_size: int = DEFAULT_PANEL_SIZE,
) -> BuildPlan:
    """Stückliste und Plattenaufteilung aus einem Mosaik ableiten."""
    if element not in ELEMENTS:
        raise ValueError(
            f"Unbekanntes Element {element!r}. Verfügbar: {', '.join(ELEMENTS)}"
        )

    counts = np.bincount(mosaic.indices.ravel(), minlength=len(mosaic.palette))
    order = np.argsort(counts)[::-1]
    used = [int(i) for i in order if counts[i] > 0]

    codes = dict(zip(used, _color_codes(len(used))))
    total = float(mosaic.stud_count)
    parts = [
        PartLine(
            color=mosaic.palette[index],
            count=int(counts[index]),
            share=counts[index] / total,
            code=codes[index],
        )
        for index in used
    ]

    return BuildPlan(
        mosaic=mosaic,
        parts=parts,
        panels=plan_panels(mosaic.width, mosaic.height, panel_size),
        element=element,
        codes=codes,
    )


def parts_csv(plan: BuildPlan) -> str:
    """Stückliste als CSV — direkt in Tabellenkalkulationen nutzbar."""
    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter=";", lineterminator="\n")
    writer.writerow(
        [
            "Code",
            "Farbe",
            "Farbe (EN)",
            "Hex",
            "LEGO-ID",
            "BrickLink-ID",
            "Teilenummer",
            "Anzahl",
            "Anteil %",
        ]
    )
    element_part = plan.element_info["part"]
    for line in plan.parts:
        writer.writerow(
            [
                line.code,
                line.color.name_de or line.color.name,
                line.color.name,
                line.color.hex,
                line.color.lego_id if line.color.lego_id is not None else "",
                line.color.bricklink_id if line.color.bricklink_id is not None else "",
                element_part,
                line.count,
                f"{line.share * 100:.2f}",
            ]
        )
    writer.writerow([])
    writer.writerow(["Summe Elemente", "", "", "", "", "", element_part, plan.total_studs, "100.00"])
    baseplate = BASEPLATES.get(plan.panels.panel_size)
    writer.writerow(
        [
            "Trägerplatten",
            baseplate["label"] if baseplate else f"Platte {plan.panels.panel_size}x{plan.panels.panel_size}",
            "",
            "",
            "",
            "",
            baseplate["part"] if baseplate else "",
            plan.panels.total,
            "",
        ]
    )
    return buffer.getvalue()


def parts_json(plan: BuildPlan) -> str:
    """Stückliste plus Metadaten als JSON — Schnittstelle für weitere Tools."""
    mosaic = plan.mosaic
    width_cm, height_cm = mosaic.size_cm
    data = {
        "mosaic": {
            "width_studs": mosaic.width,
            "height_studs": mosaic.height,
            "total_studs": mosaic.stud_count,
            "width_cm": round(width_cm, 1),
            "height_cm": round(height_cm, 1),
            "stud_mm": STUD_MM,
            "palette": mosaic.palette.id,
            "colors_used": mosaic.used_color_count,
        },
        "element": {"key": plan.element, **plan.element_info},
        "baseplates": {
            "panel_size": plan.panels.panel_size,
            "columns": plan.panels.columns,
            "rows": plan.panels.rows,
            "total": plan.panels.total,
            "exact_fit": plan.panels.is_exact,
            "part": (BASEPLATES.get(plan.panels.panel_size) or {}).get("part"),
        },
        "parts": [
            {
                "code": line.code,
                "name": line.color.name,
                "name_de": line.color.name_de,
                "hex": line.color.hex,
                "lego_id": line.color.lego_id,
                "bricklink_id": line.color.bricklink_id,
                "part": plan.element_info["part"],
                "count": line.count,
                "share": round(line.share, 6),
            }
            for line in plan.parts
        ],
    }
    return json.dumps(data, indent=2, ensure_ascii=False) + "\n"


def bricklink_wanted_list_xml(plan: BuildPlan, *, include_baseplates: bool = True) -> str:
    """Wanted-List-XML für den BrickLink-Massenupload.

    Farben ohne bekannte BrickLink-ID werden übersprungen und als
    XML-Kommentar vermerkt, damit sie beim Bestellen nicht untergehen.
    """
    root = ET.Element("INVENTORY")
    skipped: list[str] = []

    for line in plan.parts:
        if line.color.bricklink_id is None:
            skipped.append(f"{line.color.name}: {line.count}")
            continue
        item = ET.SubElement(root, "ITEM")
        ET.SubElement(item, "ITEMTYPE").text = "P"
        ET.SubElement(item, "ITEMID").text = plan.element_info["part"]
        ET.SubElement(item, "COLOR").text = str(line.color.bricklink_id)
        ET.SubElement(item, "MINQTY").text = str(line.count)
        ET.SubElement(item, "REMARKS").text = f"{line.color.name} ({line.code})"

    baseplate = BASEPLATES.get(plan.panels.panel_size)
    if include_baseplates and baseplate:
        item = ET.SubElement(root, "ITEM")
        ET.SubElement(item, "ITEMTYPE").text = "P"
        ET.SubElement(item, "ITEMID").text = baseplate["part"]
        ET.SubElement(item, "MINQTY").text = str(plan.panels.total)
        ET.SubElement(item, "REMARKS").text = baseplate["label"]

    ET.indent(root, space="  ")
    xml = ET.tostring(root, encoding="unicode")
    header = '<?xml version="1.0" encoding="UTF-8"?>\n'
    if skipped:
        header += "<!-- Ohne BrickLink-Farb-ID, bitte manuell ergänzen: " + "; ".join(skipped) + " -->\n"
    return header + xml + "\n"
