import logging
import sys
import warnings

_NOISY_TOPS = {
    "httpcore", "httpx", "urllib3", "multipart", "python_multipart",
    "pytesseract", "langsmith", "google_genai", "google",
    "langchain_core", "langchain_google_genai", "pydantic",
}

_NOISY_FULL = {
    "python_multipart.multipart",
    "langsmith.client",
    "google_genai.models",
    "google.api_core",
    "google.auth",
}


class _LibraryFilter(logging.Filter):
    """Bloqueia mensagens abaixo de WARNING de libs externas mesmo se reinicializarem seus loggers."""

    def filter(self, record: logging.LogRecord) -> bool:
        top = record.name.split(".")[0]
        if top in _NOISY_TOPS or record.name in _NOISY_FULL:
            return record.levelno >= logging.WARNING
        return True


def configure_logging(debug: bool = False) -> None:
    warnings.filterwarnings("ignore", category=UserWarning, module="pydantic")
    warnings.filterwarnings("ignore", message=".*Pydantic V1.*")

    level = logging.DEBUG if debug else logging.INFO
    fmt = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
    datefmt = "%Y-%m-%d %H:%M:%S"

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter(fmt=fmt, datefmt=datefmt))
    handler.addFilter(_LibraryFilter())

    root = logging.getLogger()
    root.setLevel(level)
    root.handlers.clear()
    root.addHandler(handler)

    for name in _NOISY_TOPS | _NOISY_FULL:
        logging.getLogger(name).setLevel(logging.WARNING)
