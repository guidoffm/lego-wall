import json

import pytest

from legowall.cli import _parse_size, main


@pytest.fixture
def image_path(tmp_path, gradient_image):
    path = tmp_path / "motiv.png"
    gradient_image.save(path)
    return path


def test_parse_size_variants():
    assert _parse_size("48x64") == (48, 64)
    assert _parse_size("48 X 64") == (48, 64)
    assert _parse_size("48*64") == (48, 64)


@pytest.mark.parametrize("value", ["48", "48x", "axb", "0x10"])
def test_parse_size_rejects_garbage(value):
    with pytest.raises(Exception):
        _parse_size(value)


def test_build_writes_all_artifacts(image_path, tmp_path, capsys):
    out = tmp_path / "out"
    code = main(
        [
            "build",
            str(image_path),
            "--size",
            "32x32",
            "--palette",
            "art-16",
            "--dither",
            "none",
            "--out-dir",
            str(out),
        ]
    )
    assert code == 0

    expected = {
        "vorschau.png",
        "mosaik.png",
        "stueckliste.csv",
        "stueckliste.json",
        "bricklink-wanted-list.xml",
        "bauanleitung.html",
    }
    assert {p.name for p in out.iterdir()} == expected

    data = json.loads((out / "stueckliste.json").read_text(encoding="utf-8"))
    assert data["mosaic"]["total_studs"] == 32 * 32

    output = capsys.readouterr().out
    assert "32 x 32 Studs" in output
    assert "Anteil" in output


def test_build_derives_height_from_aspect_ratio(image_path, tmp_path):
    out = tmp_path / "out"
    assert main(["build", str(image_path), "--width", "60", "--out-dir", str(out)]) == 0
    data = json.loads((out / "stueckliste.json").read_text(encoding="utf-8"))
    # Quellbild ist 120x80 -> 60 Studs Breite ergeben 40 Studs Höhe.
    assert (data["mosaic"]["width_studs"], data["mosaic"]["height_studs"]) == (60, 40)


def test_build_honours_max_colors(image_path, tmp_path):
    out = tmp_path / "out"
    assert (
        main(
            ["build", str(image_path), "--size", "24x24", "--max-colors", "4", "--out-dir", str(out)]
        )
        == 0
    )
    data = json.loads((out / "stueckliste.json").read_text(encoding="utf-8"))
    assert len(data["parts"]) <= 4


def test_build_without_dimensions_fails(image_path, tmp_path, capsys):
    code = main(["build", str(image_path), "--out-dir", str(tmp_path / "out")])
    assert code == 2
    assert "Abmessungen" in capsys.readouterr().err


def test_build_with_missing_file_fails(tmp_path, capsys):
    code = main(["build", str(tmp_path / "weg.png"), "--size", "8x8"])
    assert code == 1
    assert "nicht gefunden" in capsys.readouterr().err


def test_build_with_unknown_palette_fails(image_path, capsys):
    code = main(["build", str(image_path), "--size", "8x8", "--palette", "quatsch"])
    assert code == 2
    assert "Unbekannte Palette" in capsys.readouterr().err


def test_palettes_command_lists_bundled_palettes(capsys):
    assert main(["palettes"]) == 0
    output = capsys.readouterr().out
    assert "pab-full" in output and "grayscale-5" in output
