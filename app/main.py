from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.routes import router
from app.core.logging_config import configure_logging


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    configure_logging(debug=os.getenv("DEBUG", "false").lower() == "true")
    logger = logging.getLogger(__name__)
    logger.info("Leitura de Prova API iniciada na porta %s", os.getenv("API_PORT", "5041"))
    logger.info("LangSmith tracing: %s | projeto: %s",
                os.getenv("LANGCHAIN_TRACING_V2", "false"), os.getenv("LANGCHAIN_PROJECT", ""))
    yield
    logger.info("Encerrando aplicação")


def create_app() -> FastAPI:
    app = FastAPI(
        title="Leitura de Prova API",
        description=(
            "Pipeline de leitura automática de gabaritos de provas escolares.\n\n"
            "**Stack:** OpenCV · Tesseract OCR · Google Gemini · LangChain · LangSmith"
        ),
        version="1.0.0",
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(router, prefix="/api/v1", tags=["Provas"])

    @app.get("/", include_in_schema=False)
    async def root() -> JSONResponse:
        return JSONResponse({"status": "ok", "servico": "Leitura de Prova API", "versao": "1.0.0"})

    @app.get("/health", tags=["Saúde"])
    async def health() -> JSONResponse:
        return JSONResponse({"status": "healthy"})

    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn
    from dotenv import load_dotenv
    load_dotenv()

    uvicorn.run(
        "app.main:app",
        host=os.getenv("API_HOST", "0.0.0.0"),
        port=int(os.getenv("API_PORT", "5041")),
        reload=os.getenv("DEBUG", "false").lower() == "true",
        log_level="debug" if os.getenv("DEBUG", "false").lower() == "true" else "info",
    )
