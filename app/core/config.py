from __future__ import annotations

import os
from functools import lru_cache


class Settings:
    TESSERACT_CMD: str = os.getenv(
        "TESSERACT_CMD", r"C:\Program Files\Tesseract-OCR\tesseract.exe"
    )
    TESSERACT_LANG: str = os.getenv("TESSERACT_LANG", "por+eng")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
