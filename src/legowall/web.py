"""Web-Oberfläche: Bild hochladen, Abmessungen angeben, Bauunterlagen herunterladen.

Vollständig zustandslos: ein Request rechnet das Mosaik und liefert alle
Artefakte als Data-URIs in der Antwortseite mit. Nichts wird zwischengespeichert
oder auf die Platte geschrieben — deshalb läuft die App unverändert hinter einem
dauerhaften Prozess wie auch als Serverless-Function, wo jeder Folge-Request in
einer anderen Instanz landen kann.
"""

from __future__ import annotations

import io
import zipfile
from dataclasses import dataclass
from pathlib import Path

from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, Response
from fastapi.templating import Jinja2Templates
from PIL import Image, UnidentifiedImageError

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
from .render import (
    bytes_to_data_uri,
    data_uri_size,
    image_to_data_uri,
    instructions_html,
    render_preview,
    summary_lines,
)

# Obergrenzen — schützen den Server vor übergroßen Uploads und Rastern.
MAX_UPLOAD_BYTES = 25 * 1024 * 1024
MAX_STUDS_PER_EDGE = 256
MAX_TOTAL_STUDS = 200 * 200

# Budget für die eingebetteten Downloads. Serverless-Plattformen kappen
# Antworten typischerweise bei 4,5 MB; darunter bleibt Luft für die Seite selbst.
MAX_EMBEDDED_BYTES = 3 * 1024 * 1024

ALLOWED_CONTENT_TYPES = {"image/png", "image/jpeg", "image/jpg", "image/webp"}

templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))

app = FastAPI(title="LEGO-Wandbild-Generator", version=__version__)


@dataclass(frozen=True)
class Download:
    """Ein Artefakt, fertig zum Einbetten in die Ergebnisseite."""

    name: str
    label: str
    data: bytes
    mime: str

    @property
    def uri(self) -> str:
        return bytes_to_data_uri(self.data, self.mime)

    @property
    def size_kb(self) -> int:
        return max(1, round(len(self.data) / 1024))


def _fit_into_budget(
    candidates: list[Download], budget: int = MAX_EMBEDDED_BYTES
) -> tuple[list[Download], list[Download]]:
    """Artefakte der Reihe nach einbetten, solange das Budget reicht.

    Die Liste ist nach Wichtigkeit sortiert; das ZIP steht vorn und enthält
    ohnehin alles. Was nicht mehr passt — bei großen Rastern vor allem die
    Bauanleitung — wird ausgelassen und in der Seite als „nur im ZIP" vermerkt.
    """
    embedded: list[Download] = []
    skipped: list[Download] = []
    for candidate in candidates:
        needed = data_uri_size(candidate.data)
        if needed <= budget:
            embedded.append(candidate)
            budget -= needed
        else:
            skipped.append(candidate)
    return embedded, skipped


def _form_context(request: Request, **extra) -> dict:
    return {
        "request": request,
        "palettes": available_palettes(),
        "default_palette": DEFAULT_PALETTE,
        "elements": ELEMENTS,
        "default_element": DEFAULT_ELEMENT,
        "default_panel_size": DEFAULT_PANEL_SIZE,
        "max_edge": MAX_STUDS_PER_EDGE,
        "max_total": MAX_TOTAL_STUDS,
        "max_upload_mb": MAX_UPLOAD_BYTES // (1024 * 1024),
        "version": __version__,
        **extra,
    }


@app.get("/", response_class=HTMLResponse)
def index(request: Request) -> Response:
    return templates.TemplateResponse(request, "index.html", _form_context(request))


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok", "version": __version__}


def _error(request: Request, message: str, status: int = 400) -> Response:
    return templates.TemplateResponse(
        request,
        "index.html",
        _form_context(request, error=message),
        status_code=status,
    )


@app.post("/generate", response_class=HTMLResponse)
async def generate(
    request: Request,
    image: UploadFile = File(...),
    width: int = Form(...),
    height: int | None = Form(None),
    keep_aspect: bool = Form(False),
    palette_id: str = Form(DEFAULT_PALETTE),
    max_colors: int | None = Form(None),
    dither: str = Form("floyd-steinberg"),
    fit: str = Form("cover"),
    element: str = Form(DEFAULT_ELEMENT),
    panel_size: int = Form(DEFAULT_PANEL_SIZE),
    brightness: float = Form(1.0),
    contrast: float = Form(1.0),
    saturation: float = Form(1.0),
    stud_shape: str = Form("round"),
) -> Response:
    if image.content_type and image.content_type.lower() not in ALLOWED_CONTENT_TYPES:
        return _error(request, "Bitte eine PNG- oder JPG-Datei hochladen.")

    payload = await image.read(MAX_UPLOAD_BYTES + 1)
    if len(payload) > MAX_UPLOAD_BYTES:
        return _error(
            request,
            f"Die Datei ist größer als {MAX_UPLOAD_BYTES // (1024 * 1024)} MB.",
            status=413,
        )
    if not payload:
        return _error(request, "Die Datei ist leer.")

    try:
        source = Image.open(io.BytesIO(payload))
        source.load()
    except (UnidentifiedImageError, OSError):
        return _error(request, "Die Datei konnte nicht als Bild gelesen werden.")

    with source:
        try:
            if keep_aspect or not height:
                target_width, target_height = fit_dimensions(source.size, width, None)
            else:
                target_width, target_height = width, height
        except ValueError as exc:
            return _error(request, str(exc))

        if not 1 <= target_width <= MAX_STUDS_PER_EDGE or not 1 <= target_height <= MAX_STUDS_PER_EDGE:
            return _error(
                request,
                f"Breite und Höhe müssen zwischen 1 und {MAX_STUDS_PER_EDGE} Studs liegen "
                f"(berechnet: {target_width} x {target_height}).",
            )
        if target_width * target_height > MAX_TOTAL_STUDS:
            return _error(
                request,
                f"Das Raster hat {target_width * target_height} Studs — erlaubt sind "
                f"maximal {MAX_TOTAL_STUDS}.",
            )

        try:
            palette = load_palette(palette_id)
        except (ValueError, FileNotFoundError):
            return _error(request, "Unbekannte Palette.")

        if dither not in ("floyd-steinberg", "none"):
            return _error(request, "Unbekannter Dither-Modus.")
        if fit not in ("cover", "contain", "stretch"):
            return _error(request, "Unbekannter Zuschnitt-Modus.")
        if element not in ELEMENTS:
            return _error(request, "Unbekanntes Element.")
        if not 1 <= panel_size <= MAX_STUDS_PER_EDGE:
            return _error(request, "Ungültige Plattengröße.")
        if max_colors is not None and max_colors < 1:
            return _error(request, "Die Farbanzahl muss mindestens 1 sein.")

        try:
            mosaic = build_mosaic(
                source,
                target_width,
                target_height,
                palette,
                fit=fit,  # type: ignore[arg-type]
                dither=dither,  # type: ignore[arg-type]
                max_colors=max_colors,
                brightness=brightness,
                contrast=contrast,
                saturation=saturation,
            )
        except ValueError as exc:
            return _error(request, str(exc))

    plan = build_plan(mosaic, element=element, panel_size=panel_size)

    cell = max(4, min(16, 1200 // max(mosaic.width, 1)))
    preview = render_preview(
        mosaic, cell=cell, shape=stud_shape, panel_size=panel_size
    )
    instructions = instructions_html(
        plan, preview=preview, title=f"LEGO-Wandbild — {image.filename or 'Upload'}"
    )

    preview_bytes = io.BytesIO()
    preview.save(preview_bytes, format="PNG")
    mosaic_bytes = io.BytesIO()
    mosaic.to_image().save(mosaic_bytes, format="PNG")

    artifacts = [
        Download(
            "bauanleitung.html",
            "Bauanleitung",
            instructions.encode("utf-8"),
            "text/html; charset=utf-8",
        ),
        Download("vorschau.png", "Vorschau", preview_bytes.getvalue(), "image/png"),
        Download(
            "mosaik.png", "Mosaik (1 Pixel je Stud)", mosaic_bytes.getvalue(), "image/png"
        ),
        Download(
            "stueckliste.csv",
            "Stückliste (CSV)",
            parts_csv(plan).encode("utf-8"),
            "text/csv; charset=utf-8",
        ),
        Download(
            "stueckliste.json",
            "Stückliste (JSON)",
            parts_json(plan).encode("utf-8"),
            "application/json",
        ),
        Download(
            "bricklink-wanted-list.xml",
            "BrickLink Wanted List",
            bricklink_wanted_list_xml(plan).encode("utf-8"),
            "application/xml",
        ),
    ]

    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zf:
        for artifact in artifacts:
            zf.writestr(artifact.name, artifact.data)
    bundle = Download(
        "wandbild.zip", "Alles als ZIP", archive.getvalue(), "application/zip"
    )

    # Das ZIP zuerst: es enthält ohnehin alles und ist komprimiert am kleinsten.
    # Die Bauanleitung wandert ans Ende, weil sie bei großen Rastern mehrere
    # Megabyte gross wird und sonst das ganze Budget aufbraucht.
    embedded, skipped = _fit_into_budget(
        [bundle, *artifacts[1:], artifacts[0]],
    )

    return templates.TemplateResponse(
        request,
        "result.html",
        {
            "request": request,
            "plan": plan,
            "mosaic": mosaic,
            "summary": summary_lines(plan),
            "preview_uri": image_to_data_uri(preview),
            "downloads": embedded,
            "skipped": skipped,
            "filename": image.filename or "Upload",
            "version": __version__,
        },
    )
