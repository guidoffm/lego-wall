import io
import zipfile

import pytest

fastapi_testclient = pytest.importorskip("fastapi.testclient")
from fastapi.testclient import TestClient  # noqa: E402

from legowall.web import MAX_TOTAL_STUDS, app  # noqa: E402


@pytest.fixture
def client():
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def upload(gradient_image):
    buffer = io.BytesIO()
    gradient_image.save(buffer, format="PNG")
    return buffer.getvalue()


def _post(client, payload, **overrides):
    data = {
        "width": "32",
        "height": "32",
        "palette_id": "art-16",
        "dither": "none",
        "fit": "cover",
        "element": "tile-round-1x1",
        "panel_size": "16",
        "brightness": "1.0",
        "contrast": "1.0",
        "saturation": "1.0",
        "stud_shape": "round",
    }
    data.update(overrides)
    return client.post(
        "/generate",
        data=data,
        files={"image": ("motiv.png", payload, "image/png")},
    )


def test_index_renders_form(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "Bilddatei" in response.text
    assert 'name="width"' in response.text


def test_healthz(client):
    assert client.get("/healthz").json()["status"] == "ok"


def test_generate_returns_summary_and_downloads(client, upload):
    response = _post(client, upload)
    assert response.status_code == 200
    assert "32 x 32 Studs" in response.text
    assert "1024 Elemente" in response.text
    assert "data:image/png;base64," in response.text
    assert "/download/" in response.text
    assert "wandbild.zip" in response.text


def test_downloads_are_served(client, upload):
    response = _post(client, upload)
    token = response.text.split("/download/")[1].split("/")[0]

    csv_response = client.get(f"/download/{token}/stueckliste.csv")
    assert csv_response.status_code == 200
    assert csv_response.text.startswith("Code;")
    assert "attachment" in csv_response.headers["content-disposition"]

    xml_response = client.get(f"/download/{token}/bricklink-wanted-list.xml")
    assert xml_response.status_code == 200
    assert "<INVENTORY>" in xml_response.text

    zip_response = client.get(f"/download/{token}/wandbild.zip")
    with zipfile.ZipFile(io.BytesIO(zip_response.content)) as archive:
        assert "bauanleitung.html" in archive.namelist()
        assert "mosaik.png" in archive.namelist()


def test_unknown_download_is_404(client):
    assert client.get("/download/abc/stueckliste.csv").status_code == 404


def test_keep_aspect_derives_height(client, upload):
    # Quellbild 120x80, Breite 60 -> 40 Studs Höhe.
    response = _post(client, upload, width="60", keep_aspect="true")
    assert response.status_code == 200
    assert "60 x 40 Studs" in response.text


def test_missing_height_falls_back_to_aspect_ratio(client, upload):
    response = client.post(
        "/generate",
        data={"width": "40", "palette_id": "art-16", "dither": "none"},
        files={"image": ("motiv.png", upload, "image/png")},
    )
    assert response.status_code == 200
    assert "40 x 27 Studs" in response.text


def test_oversized_grid_is_rejected(client, upload):
    response = _post(client, upload, width="300", height="300")
    assert response.status_code == 400
    assert "Studs liegen" in response.text


def test_total_stud_limit_is_enforced(client, upload):
    response = _post(client, upload, width="256", height="256")
    assert response.status_code == 400
    assert str(MAX_TOTAL_STUDS) in response.text


def test_non_image_upload_is_rejected(client):
    response = client.post(
        "/generate",
        data={"width": "16", "height": "16"},
        files={"image": ("notiz.txt", b"kein bild", "text/plain")},
    )
    assert response.status_code == 400
    assert "PNG- oder JPG" in response.text


def test_broken_image_is_rejected(client):
    response = client.post(
        "/generate",
        data={"width": "16", "height": "16"},
        files={"image": ("motiv.png", b"\x89PNG kaputt", "image/png")},
    )
    assert response.status_code == 400
    assert "nicht als Bild" in response.text


def test_empty_upload_is_rejected(client):
    response = client.post(
        "/generate",
        data={"width": "16", "height": "16"},
        files={"image": ("leer.png", b"", "image/png")},
    )
    assert response.status_code == 400
    assert "leer" in response.text


def test_unknown_palette_is_rejected(client, upload):
    response = _post(client, upload, palette_id="../../etc/passwd")
    assert response.status_code == 400
    assert "Unbekannte Palette" in response.text


def test_unknown_element_is_rejected(client, upload):
    response = _post(client, upload, element="brick-2x4")
    assert response.status_code == 400
    assert "Unbekanntes Element" in response.text


def test_max_colors_is_applied(client, upload):
    response = _post(client, upload, palette_id="pab-full", max_colors="3")
    assert response.status_code == 200
    assert "3 Farben verwendet" in response.text
