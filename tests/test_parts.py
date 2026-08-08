import csv
import io
import json
from xml.etree import ElementTree as ET

import pytest

from legowall.mosaic import build_mosaic
from legowall.palette import load_palette
from legowall.parts import (
    bricklink_wanted_list_xml,
    build_plan,
    parts_csv,
    parts_json,
    plan_panels,
)


@pytest.fixture
def plan(halves_image):
    mosaic = build_mosaic(
        halves_image, 32, 16, load_palette("art-16"), dither="none", fit="stretch"
    )
    return build_plan(mosaic, panel_size=16)


def test_bom_counts_every_stud(plan):
    assert sum(line.count for line in plan.parts) == plan.total_studs == 32 * 16
    assert sum(line.share for line in plan.parts) == pytest.approx(1.0)


def test_bom_is_sorted_descending(plan):
    counts = [line.count for line in plan.parts]
    assert counts == sorted(counts, reverse=True)


def test_codes_are_unique_and_stable(plan):
    codes = [line.code for line in plan.parts]
    assert len(set(codes)) == len(codes)
    assert codes[0] == "A"
    for line in plan.parts:
        assert plan.code_for(plan.mosaic.indices[0].tolist()[0]) in codes


def test_only_used_colors_appear(plan):
    # Zwei Farbflächen -> genau zwei Stücklistenzeilen.
    assert len(plan.parts) == 2
    assert {line.color.name for line in plan.parts} == {"Red", "Dark Blue"}


def test_panel_plan_exact_and_partial():
    exact = plan_panels(48, 32, 16)
    assert (exact.columns, exact.rows, exact.total) == (3, 2, 6)
    assert exact.is_exact

    partial = plan_panels(50, 33, 16)
    assert (partial.columns, partial.rows, partial.total) == (4, 3, 12)
    assert not partial.is_exact
    assert (partial.partial_columns, partial.partial_rows) == (2, 1)


def test_panel_plan_rejects_zero():
    with pytest.raises(ValueError):
        plan_panels(16, 16, 0)


def test_unknown_element_is_rejected(halves_image):
    mosaic = build_mosaic(halves_image, 8, 8, load_palette("art-16"), dither="none")
    with pytest.raises(ValueError, match="Unbekanntes Element"):
        build_plan(mosaic, element="brick-2x4")


def test_row_runs_cover_the_panel_width(plan):
    rows = plan.rows_for_panel(0, 0)
    assert len(rows) == 16
    for runs in rows:
        assert sum(run.count for run in runs) == 16
        # Aufeinanderfolgende Runs haben immer unterschiedliche Farben.
        codes = [run.code for run in runs]
        assert all(a != b for a, b in zip(codes, codes[1:]))


def test_row_runs_collapse_uniform_rows(plan):
    # Die linke Platte ist komplett rot -> ein Run pro Reihe.
    for runs in plan.rows_for_panel(0, 0):
        assert len(runs) == 1
        assert runs[0].count == 16


def test_csv_export_is_parseable(plan):
    rows = list(csv.reader(io.StringIO(parts_csv(plan)), delimiter=";"))
    header, *body = rows
    assert header[0] == "Code" and header[-1] == "Anteil %"
    data_rows = [row for row in body if row and row[0] not in ("", "Summe Elemente", "Trägerplatten")]
    assert len(data_rows) == len(plan.parts)
    total_row = next(row for row in body if row and row[0] == "Summe Elemente")
    assert int(total_row[7]) == plan.total_studs
    plate_row = next(row for row in body if row and row[0] == "Trägerplatten")
    assert int(plate_row[7]) == plan.panels.total


def test_json_export_has_expected_shape(plan):
    data = json.loads(parts_json(plan))
    assert data["mosaic"]["total_studs"] == plan.total_studs
    assert data["mosaic"]["width_cm"] == pytest.approx(25.6)
    assert data["element"]["part"] == "98138"
    assert data["baseplates"]["total"] == plan.panels.total
    assert sum(part["count"] for part in data["parts"]) == plan.total_studs


def test_bricklink_xml_is_valid_and_complete(plan):
    xml = bricklink_wanted_list_xml(plan)
    root = ET.fromstring(xml.split("?>", 1)[1])
    assert root.tag == "INVENTORY"
    items = root.findall("ITEM")
    # Eine Zeile pro Farbe plus die Trägerplatten.
    assert len(items) == len(plan.parts) + 1
    tiles = [item for item in items if item.findtext("ITEMID") == "98138"]
    assert sum(int(item.findtext("MINQTY")) for item in tiles) == plan.total_studs
    for item in tiles:
        assert item.findtext("COLOR").isdigit()
    plate = next(item for item in items if item.findtext("ITEMID") == "91405")
    assert int(plate.findtext("MINQTY")) == plan.panels.total


def test_bricklink_xml_can_skip_baseplates(plan):
    root = ET.fromstring(
        bricklink_wanted_list_xml(plan, include_baseplates=False).split("?>", 1)[1]
    )
    assert len(root.findall("ITEM")) == len(plan.parts)


def test_colors_without_bricklink_id_are_flagged(gradient_image):
    # 'Pink' hat keine LEGO-ID, aber eine BL-ID; wir prüfen den Kommentarpfad
    # mit einer Palette, in der eine Farbe ohne BL-ID vorkommt.
    palette = load_palette("pab-full")
    stripped = type(palette)(
        id=palette.id,
        name=palette.name,
        colors=tuple(
            type(c)(name=c.name, hex=c.hex, name_de=c.name_de, lego_id=c.lego_id, bricklink_id=None)
            if i == 0
            else c
            for i, c in enumerate(palette.colors)
        ),
    )
    mosaic = build_mosaic(gradient_image, 24, 24, stripped, dither="none")
    plan = build_plan(mosaic)
    xml = bricklink_wanted_list_xml(plan)
    missing = [line for line in plan.parts if line.color.bricklink_id is None]
    if missing:
        assert "Ohne BrickLink-Farb-ID" in xml
        root = ET.fromstring(xml.split("-->", 1)[1])
        assert len(root.findall("ITEM")) == len(plan.parts) - len(missing) + 1
