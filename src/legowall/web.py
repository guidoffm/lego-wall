"""Web-Oberfläche: Bild hochladen, Abmessungen angeben, Bauunterlagen herunterladen.

Bewusst zustandsarm: die erzeugten Dateien liegen nur in einem kleinen
LRU-Cache im Speicher und werden nie auf die Platte geschrieben.
"""

from __future__ import annotations

import io
import secrets
import zipfile
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from threading import Lock

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
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
from .render import image_to_data_uri, instructions_html, render_preview, summary_lines

# Obergrenzen — schützen den Server vor übergroßen Uploads und Rastern.
MAX_UPLOAD_BYTES = 25 * 1024 * 1024
MAX_STUDS_PER_EDGE = 256
MAX_TOTAL_STUDS = 200 * 200
CACHE_SIZE = 20

ALLOWED_CONTENT_TYPES = {"image/png", "image/jpeg", "image/jpg", "image/webp"}

templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))

app = FastAPI(title="LEGO-Wandbild-Generator", version=__version__)


@dataclass
class ResultBundle:
    """Downloadbare Artefakte eines Durchlaufs."""

    files: dict[str, tuple[str, bytes]]


class _ResultCache:
    """Kleiner threadsicherer LRU-Cache für die Download-Artefakte."""

    def __init__(self, size: int = CACHE_SIZE) -> None:
        self._size = size
        self._items: OrderedDict[str, ResultBundle] = OrderedDict()
        self._lock = Lock()

    def put(self, bundle: ResultBundle) -> str:
        token = secrets.token_urlsafe(16)
        with self._lock:
            self._items[token] = bundle
            while len(self._items) > self._size:
                self._items.popitem(last=False)
        return token

    def get(self, token: str) -> ResultBundle | None:
        with self._lock:
            bundle = self._items.get(token)
            if bundle is not None:
                self._items.move_to_end(token)
            return bundle


_cache = _ResultCache()


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

    files: dict[str, tuple[str, bytes]] = {
        "vorschau.png": ("image/png", preview_bytes.getvalue()),
        "mosaik.png": ("image/png", mosaic_bytes.getvalue()),
        "stueckliste.csv": ("text/csv; charset=utf-8", parts_csv(plan).encode("utf-8")),
        "stueckliste.json": ("application/json", parts_json(plan).encode("utf-8")),
        "bricklink-wanted-list.xml": (
            "application/xml",
            bricklink_wanted_list_xml(plan).encode("utf-8"),
        ),
        "bauanleitung.html": ("text/html; charset=utf-8", instructions.encode("utf-8")),
    }

    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, (_, data) in files.items():
            zf.writestr(name, data)
    files["wandbild.zip"] = ("application/zip", archive.getvalue())

    token = _cache.put(ResultBundle(files=files))

    return templates.TemplateResponse(
        request,
        "result.html",
        {
            "request": request,
            "plan": plan,
            "mosaic": mosaic,
            "summary": summary_lines(plan),
            "preview_uri": image_to_data_uri(preview),
            "token": token,
            "downloads": [name for name in files if name != "wandbild.zip"],
            "filename": image.filename or "Upload",
            "version": __version__,
        },
    )


@app.get("/download/{token}/{name}")
def download(token: str, name: str) -> Response:
    bundle = _cache.get(token)
    if bundle is None or name not in bundle.files:
        raise HTTPException(
            status_code=404,
            detail="Download nicht mehr verfügbar — bitte das Mosaik neu erzeugen.",
        )
    media_type, data = bundle.files[name]
    disposition = "inline" if name == "bauanleitung.html" else "attachment"
    return Response(
        content=data,
        media_type=media_type,
        headers={"Content-Disposition": f'{disposition}; filename="{name}"'},
    )
