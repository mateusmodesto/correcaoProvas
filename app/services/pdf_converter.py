from __future__ import annotations

import logging
from pathlib import Path

import fitz  # PyMuPDF
import numpy as np
from PIL import Image

logger = logging.getLogger(__name__)

DPI = 200  # resolução suficiente para OCR e visão computacional


def pdf_to_images(pdf_path: str | Path) -> list[np.ndarray]:
    """Converte todas as páginas de um PDF em arrays numpy (BGR)."""
    path = Path(pdf_path)
    doc = fitz.open(str(path))
    images: list[np.ndarray] = []

    for page_num, page in enumerate(doc):
        mat = fitz.Matrix(DPI / 72, DPI / 72)
        pix = page.get_pixmap(matrix=mat, alpha=False)
        pil_img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
        arr = np.array(pil_img)
        # PIL RGB → OpenCV BGR
        import cv2
        bgr = cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)
        images.append(bgr)
        logger.debug("PDF página %d convertida (%dx%d)", page_num + 1, bgr.shape[1], bgr.shape[0])

    doc.close()
    logger.info("PDF '%s' → %d página(s) convertida(s)", path.name, len(images))
    return images


def image_file_to_array(image_path: str | Path) -> np.ndarray:
    """Carrega PNG/JPG/JPEG como array numpy BGR."""
    import cv2
    img = cv2.imread(str(image_path))
    if img is None:
        raise ValueError(f"Não foi possível carregar a imagem: {image_path}")
    return img


def bytes_to_array(data: bytes, filename: str = "") -> list[np.ndarray]:
    """
    Converte bytes de upload em lista de imagens numpy.
    Suporta PDF, PNG, JPG, JPEG.
    """
    import tempfile, os

    ext = Path(filename).suffix.lower() if filename else ""
    with tempfile.NamedTemporaryFile(suffix=ext or ".tmp", delete=False) as tmp:
        tmp.write(data)
        tmp_path = tmp.name

    try:
        if ext == ".pdf":
            return pdf_to_images(tmp_path)
        else:
            return [image_file_to_array(tmp_path)]
    finally:
        os.unlink(tmp_path)
