"""Kommandozeile: Bild rein, Mosaik plus Stückliste raus."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from PIL import Image

from . import __version__
from .mosaic import build_mosaic, fit_dimensions
from .palette import DEFAULT_PALETTE, available_palettes, load_palette
from .parts import (
    DEFAULT_ELEMENT,
    DEFAULT_PANEL_SIZE,
    ELEMENTS,
    bricklink_wanted_list_xml,
    build_plan,
    parts_csv,
    parts_json,
)
from .render import instructions_html, render_preview, summary_lines


def _parse_size(value: str) -> tuple[int, int]:
    """'48x64' -> (48, 64)."""
    text = value.lower().replace(" ", "").replace("*", "x")
    if "x" not in text:
        raise argparse.ArgumentTypeError("Format erwartet: BREITExHOEHE, z. B. 48x48")
    left, right = text.split("x", 1)
    try:
        width, height = int(left), int(right)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"Ungültige Größe: {value!r}") from exc
    if width < 1 or height < 1:
        raise argparse.ArgumentTypeError("Breite und Höhe müssen mindestens 1 sein")
    return width, height


def _positive(value: str) -> int:
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("Wert muss mindestens 1 sein")
    return number


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="legowall",
        description="Bilder in LEGO-Wandbilder umrechnen: Raster, Farbauswahl und Stückliste.",
    )
    parser.add_argument("--version", action="version", version=f"legowall {__version__}")
    subparsers = parser.add_subparsers(dest="command", required=True)

    build = subparsers.add_parser(
        "build",
        help="Mosaik aus einer Bilddatei erzeugen",
        description="Bild auf das Stud-Raster reduzieren und alle Bau-Unterlagen schreiben.",
    )
    build.add_argument("image", type=Path, help="Eingabebild (PNG oder JPG)")

    dimensions = build.add_argument_group("Abmessungen")
    dimensions.add_argument(
        "--size", type=_parse_size, help="Raster als BREITExHOEHE in Studs, z. B. 48x48"
    )
    dimensions.add_argument("--width", type=_positive, help="Breite in Studs")
    dimensions.add_argument("--height", type=_positive, help="Höhe in Studs")
    dimensions.add_argument(
        "--fit",
        choices=("cover", "contain", "stretch"),
        default="cover",
        help="cover = mittig beschneiden (Standard), contain = vollständig einpassen, stretch = verzerren",
    )

    colors = build.add_argument_group("Farben")
    colors.add_argument(
        "--palette",
        default=DEFAULT_PALETTE,
        help=f"Palette-ID oder Pfad zu einer JSON-Palette (Standard: {DEFAULT_PALETTE})",
    )
    colors.add_argument(
        "--max-colors",
        type=_positive,
        help="Farbanzahl begrenzen — es bleiben die häufigsten Farben übrig",
    )
    colors.add_argument(
        "--dither",
        choices=("floyd-steinberg", "none"),
        default="floyd-steinberg",
        help="Fehlerdiffusion für weichere Verläufe (Standard) oder harte Farbflächen",
    )
    colors.add_argument("--brightness", type=float, default=1.0, help="Helligkeit, 1.0 = unverändert")
    colors.add_argument("--contrast", type=float, default=1.0, help="Kontrast, 1.0 = unverändert")
    colors.add_argument("--saturation", type=float, default=1.0, help="Sättigung, 1.0 = unverändert")
    colors.add_argument(
        "--background",
        default="#FFFFFF",
        help="Farbe für transparente Bereiche und Ränder (Standard: #FFFFFF)",
    )

    parts = build.add_argument_group("Teile")
    parts.add_argument(
        "--element",
        choices=tuple(ELEMENTS),
        default=DEFAULT_ELEMENT,
        help=f"1x1-Element für die Fläche (Standard: {DEFAULT_ELEMENT})",
    )
    parts.add_argument(
        "--panel-size",
        type=_positive,
        default=DEFAULT_PANEL_SIZE,
        help=f"Kantenlänge der Trägerplatten in Studs (Standard: {DEFAULT_PANEL_SIZE})",
    )

    output = build.add_argument_group("Ausgabe")
    output.add_argument(
        "--out-dir", type=Path, default=Path("legowall-out"), help="Zielverzeichnis"
    )
    output.add_argument(
        "--cell", type=_positive, default=12, help="Pixel pro Stud im Vorschaubild (Standard: 12)"
    )
    output.add_argument(
        "--stud-shape",
        choices=("round", "square"),
        default="round",
        help="Darstellung der Studs in der Vorschau",
    )

    subparsers.add_parser("palettes", help="Mitgelieferte Paletten auflisten")

    serve = subparsers.add_parser("serve", help="Web-Oberfläche mit Datei-Upload starten")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)
    serve.add_argument("--reload", action="store_true", help="Autoreload für die Entwicklung")

    return parser


def _command_palettes() -> int:
    for palette in available_palettes():
        print(f"{palette.id}  ({len(palette)} Farben)  — {palette.name}")
        if palette.description:
            print(f"    {palette.description}")
    return 0


def _command_serve(args: argparse.Namespace) -> int:
    try:
        import uvicorn
    except ImportError:
        print(
            "Die Web-Oberfläche braucht die Extras: pip install 'legowall[web]'",
            file=sys.stderr,
        )
        return 1
    uvicorn.run("legowall.web:app", host=args.host, port=args.port, reload=args.reload)
    return 0


def _command_build(args: argparse.Namespace) -> int:
    if not args.image.is_file():
        print(f"Bilddatei nicht gefunden: {args.image}", file=sys.stderr)
        return 1
    if not args.size and not args.width and not args.height:
        print(
            "Bitte die Abmessungen angeben, z. B. --size 48x48 oder --width 48",
            file=sys.stderr,
        )
        return 2

    try:
        palette = load_palette(args.palette)
    except (ValueError, FileNotFoundError) as exc:
        print(str(exc), file=sys.stderr)
        return 2

    try:
        image = Image.open(args.image)
    except OSError as exc:
        print(f"Bild konnte nicht gelesen werden: {exc}", file=sys.stderr)
        return 1

    with image:
        if args.size:
            width, height = args.size
        else:
            width, height = fit_dimensions(image.size, args.width, args.height)

        mosaic = build_mosaic(
            image,
            width,
            height,
            palette,
            fit=args.fit,
            dither=args.dither,
            max_colors=args.max_colors,
            background=args.background,
            brightness=args.brightness,
            contrast=args.contrast,
            saturation=args.saturation,
        )

    plan = build_plan(mosaic, element=args.element, panel_size=args.panel_size)
    preview = render_preview(
        mosaic, cell=args.cell, shape=args.stud_shape, panel_size=args.panel_size
    )

    out_dir = args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    preview.save(out_dir / "vorschau.png")
    mosaic.to_image().save(out_dir / "mosaik.png")
    (out_dir / "stueckliste.csv").write_text(parts_csv(plan), encoding="utf-8")
    (out_dir / "stueckliste.json").write_text(parts_json(plan), encoding="utf-8")
    (out_dir / "bricklink-wanted-list.xml").write_text(
        bricklink_wanted_list_xml(plan), encoding="utf-8"
    )
    (out_dir / "bauanleitung.html").write_text(
        instructions_html(plan, preview=preview, title=f"LEGO-Wandbild — {args.image.name}"),
        encoding="utf-8",
    )

    for line in summary_lines(plan):
        print(line)
    print()
    print(f"{'Code':<5}{'Farbe':<46}{'Anzahl':>8}{'Anteil':>9}")
    print("-" * 68)
    for line in plan.parts:
        print(
            f"{line.code:<5}{line.color.label[:45]:<46}{line.count:>8}"
            f"{line.share * 100:>8.1f}%"
        )
    print()
    print(f"Dateien in {out_dir}/:")
    for name in sorted(p.name for p in out_dir.iterdir()):
        print(f"  {name}")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "palettes":
            return _command_palettes()
        if args.command == "serve":
            return _command_serve(args)
        return _command_build(args)
    except KeyboardInterrupt:
        return 130
    except BrokenPipeError:
        # Passiert beim Weiterleiten an `head` & Co. — kein Fehler, nur Ende der Ausgabe.
        try:
            sys.stdout.close()
        finally:
            return 0


if __name__ == "__main__":
    raise SystemExit(main())
