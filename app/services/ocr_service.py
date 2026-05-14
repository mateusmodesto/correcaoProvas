from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Optional

import cv2
import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class HeaderInfo:
    nome: Optional[str]
    numero: Optional[str]
    turma: Optional[str]
    raw_text: str


def _init_tesseract(tesseract_cmd: str, lang: str) -> None:
    import pytesseract
    pytesseract.pytesseract.tesseract_cmd = tesseract_cmd
    pytesseract._pytesseract_lang = lang  # type: ignore[attr-defined]


def extract_header(
    aligned_image: np.ndarray,
    header_ratio: float = 0.20,
    tesseract_cmd: str = "/usr/bin/tesseract",
    lang: str = "por+eng",
) -> HeaderInfo:
    """
    Extrai informações do cabeçalho da prova (nome, número, turma).
    Assume que o cabeçalho ocupa os primeiros `header_ratio` da altura da imagem.
    """
    try:
        import pytesseract
        pytesseract.pytesseract.tesseract_cmd = tesseract_cmd
    except ImportError:
        logger.error("pytesseract não instalado")
        return HeaderInfo(None, None, None, "")

    h = aligned_image.shape[0]
    header_crop = aligned_image[: int(h * header_ratio), :]

    gray = cv2.cvtColor(header_crop, cv2.COLOR_BGR2GRAY) if len(header_crop.shape) == 3 else header_crop
    # Threshold para melhorar leitura OCR
    _, thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)

    config = "--psm 6 -l " + lang
    try:
        raw = pytesseract.image_to_string(thresh, config=config)
    except Exception as e:
        logger.warning("Falha no OCR do cabeçalho: %s", e)
        return HeaderInfo(None, None, None, "")

    logger.debug("OCR cabeçalho raw:\n%s", raw)
    return _parse_header(raw)


def _parse_header(text: str) -> HeaderInfo:
    nome = _extract_field(text, r"(?:Nome|Aluno|Student)[:\s]+([A-Za-zÀ-ÿ\s]+)")
    numero = _extract_field(text, r"(?:N[oº°]|Número|Matrícula|RA)[:\s#]?\s*(\d+)")
    turma = _extract_field(text, r"(?:Turma|Série|Classe|Class)[:\s]+([A-Za-z0-9\s]+)")

    return HeaderInfo(
        nome=nome.strip() if nome else None,
        numero=numero.strip() if numero else None,
        turma=turma.strip() if turma else None,
        raw_text=text,
    )


def _extract_field(text: str, pattern: str) -> Optional[str]:
    match = re.search(pattern, text, re.IGNORECASE)
    return match.group(1) if match else None
