import numpy as np
import pytest
from PIL import Image


@pytest.fixture
def gradient_image() -> Image.Image:
    """120x80 Farbverlauf — deckt viele Farbtöne ab."""
    width, height = 120, 80
    x = np.linspace(0, 255, width, dtype=np.float64)
    y = np.linspace(0, 255, height, dtype=np.float64)
    grid_x, grid_y = np.meshgrid(x, y)
    data = np.stack([grid_x, grid_y, 255 - grid_x], axis=-1).astype(np.uint8)
    return Image.fromarray(data, mode="RGB")


@pytest.fixture
def halves_image() -> Image.Image:
    """Linke Hälfte reines Rot, rechte Hälfte reines Blau."""
    data = np.zeros((40, 40, 3), dtype=np.uint8)
    data[:, :20] = (255, 0, 0)
    data[:, 20:] = (0, 0, 255)
    return Image.fromarray(data, mode="RGB")
