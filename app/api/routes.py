from __future__ import annotations

import logging
from typing import Annotated, Optional

from fastapi import APIRouter, File, Form, HTTPException, UploadFile, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.core.model_registry import (
    ModelConfig,
    delete_model_config,
    get_model_config,
    get_model_details,
    list_models,
    save_model_config,
)
from app.models.schemas import ErroResponse, ResultadoProva
from app.services.pipeline import processar_prova

logger = logging.getLogger(__name__)

router = APIRouter()

ALLOWED_CONTENT_TYPES = {
    "image/png",
    "image/jpeg",
    "image/jpg",
    "application/pdf",
}
MAX_FILE_SIZE = 20 * 1024 * 1024  # 20 MB


# ─── Schemas para gerenciamento de modelos ─────────────────────────────────

class ModeloRequest(BaseModel):
    """Payload para criar/atualizar um modelo."""
    descricao: str = Field(..., description="Descrição do modelo")
    n_panels: int = Field(4, description="Número de painéis (colunas de questões)")
    grid_top_ratio: float = Field(0.35, description="Ratio do topo da grade (0.0-1.0)")
    grid_bottom_ratio: float = Field(0.99, description="Ratio do fundo da grade (0.0-1.0)")
    grid_left_ratio: float = Field(0.02, description="Ratio da esquerda da grade (0.0-1.0)")
    grid_right_ratio: float = Field(0.98, description="Ratio da direita da grade (0.0-1.0)")
    fill_threshold_empty: float = Field(0.12, description="Threshold para bolha vazia")
    fill_threshold_filled: float = Field(0.40, description="Threshold para bolha preenchida")
    disable_auto_top: bool = Field(False, description="Desativa detecção automática do topo")


class ModeloResponse(BaseModel):
    """Resposta com detalhes de um modelo."""
    modelo: str
    descricao: str
    n_panels: int
    grid_top_ratio: float
    grid_bottom_ratio: float
    grid_left_ratio: float
    grid_right_ratio: float
    fill_threshold_empty: float
    fill_threshold_filled: float
    disable_auto_top: bool


# ─── Endpoints ────────────────────────────────────────────────────────────

@router.get("/modelos", summary="Lista todos os modelos disponíveis")
async def listar_modelos_endpoint() -> dict[str, str]:
    """Retorna dicionário com chave:descrição de todos os modelos."""
    return list_models()


@router.get("/modelos-lista", summary="Lista modelos com detalhes para o frontend")
async def listar_modelos_lista_endpoint() -> list[dict]:
    """Retorna lista com id, descricao, n_panels e n_questoes de cada modelo."""
    from app.services.db_service import listar_modelos_completo
    return listar_modelos_completo()


@router.get("/provas", summary="Lista provas cadastradas para o frontend")
async def listar_provas_endpoint() -> list[dict]:
    """Retorna lista de provas com id, descricao, modelo e n_questoes."""
    from app.services.db_service import listar_provas
    return listar_provas()


@router.get("/provas/{prova_id}", summary="Detalhes de uma prova")
async def obter_prova_endpoint(prova_id: int) -> dict:
    from app.services.db_service import buscar_prova
    prova = buscar_prova(prova_id)
    if not prova:
        raise HTTPException(status_code=404, detail=f"Prova '{prova_id}' não encontrada")
    return {
        "id": prova.id,
        "descricao": prova.descricao,
        "modelo_id": prova.modelo_id,
        "gabarito": prova.gabarito,
    }


class ProvaRequest(BaseModel):
    descricao: str
    modelo_id: str
    gabarito: str = Field("", description="CSV de letras, ex: A,B,C,D,E,...")


@router.post("/provas", summary="Criar nova prova", status_code=status.HTTP_201_CREATED)
async def criar_prova_endpoint(body: ProvaRequest) -> dict:
    from app.services.db_service import upsert_prova
    new_id = upsert_prova(None, body.descricao, body.modelo_id, body.gabarito)
    if new_id is None:
        raise HTTPException(status_code=500, detail="Falha ao criar prova")
    return {"sucesso": True, "id": new_id}


@router.put("/provas/{prova_id}", summary="Atualizar prova")
async def atualizar_prova_endpoint(prova_id: int, body: ProvaRequest) -> dict:
    from app.services.db_service import upsert_prova
    result = upsert_prova(prova_id, body.descricao, body.modelo_id, body.gabarito)
    if result is None:
        raise HTTPException(status_code=500, detail="Falha ao atualizar prova")
    return {"sucesso": True, "id": prova_id}


@router.delete("/provas/{prova_id}", summary="Deletar prova")
async def deletar_prova_endpoint(prova_id: int) -> dict:
    from app.services.db_service import deletar_prova
    ok = deletar_prova(prova_id)
    if not ok:
        raise HTTPException(status_code=404, detail=f"Prova '{prova_id}' não encontrada")
    return {"sucesso": True}


@router.get("/modelos/{modelo_id}", summary="Obter detalhes de um modelo")
async def obter_modelo_endpoint(modelo_id: str) -> ModeloResponse:
    """Retorna configuração completa de um modelo específico."""
    detalhes = get_model_details(modelo_id)
    if not detalhes:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Modelo '{modelo_id}' não encontrado",
        )

    return ModeloResponse(modelo=modelo_id, **detalhes)


@router.post("/modelos", summary="Criar novo modelo", status_code=status.HTTP_201_CREATED)
async def criar_modelo_endpoint(
    modelo_id: Annotated[str, Form(description="Identificador único do modelo")],
    config: Annotated[ModeloRequest, Form()],
) -> dict:
    """
    Cria um novo modelo de gabarito com configurações específicas.

    Parâmetros essenciais:
    - `n_panels`: Quantas colunas o gabarito tem (ex: 4 para 100 questões em 4 painéis)
    - `grid_top_ratio` / `grid_bottom_ratio`: Onde começa/termina a grade de respostas
    - `fill_threshold_empty` / `fill_threshold_filled`: Limiares para detecção de bolhas
    """
    try:
        model_cfg = ModelConfig(
            descricao=config.descricao,
            n_panels=config.n_panels,
            grid_top_ratio=config.grid_top_ratio,
            grid_bottom_ratio=config.grid_bottom_ratio,
            grid_left_ratio=config.grid_left_ratio,
            grid_right_ratio=config.grid_right_ratio,
            fill_threshold_empty=config.fill_threshold_empty,
            fill_threshold_filled=config.fill_threshold_filled,
            disable_auto_top=config.disable_auto_top,
        )

        result = save_model_config(modelo_id, model_cfg)

        if not result["sucesso"]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="; ".join(result.get("erros", ["Erro desconhecido"])),
            )

        return {
            "sucesso": True,
            "modelo": modelo_id,
            "avisos": result.get("avisos", []),
            "mensagem": f"Modelo '{modelo_id}' criado com sucesso",
        }

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.put("/modelos/{modelo_id}", summary="Atualizar um modelo existente")
async def atualizar_modelo_endpoint(
    modelo_id: str,
    config: ModeloRequest,
) -> dict:
    """Atualiza a configuração de um modelo existente."""
    try:
        model_cfg = ModelConfig(
            descricao=config.descricao,
            n_panels=config.n_panels,
            grid_top_ratio=config.grid_top_ratio,
            grid_bottom_ratio=config.grid_bottom_ratio,
            grid_left_ratio=config.grid_left_ratio,
            grid_right_ratio=config.grid_right_ratio,
            fill_threshold_empty=config.fill_threshold_empty,
            fill_threshold_filled=config.fill_threshold_filled,
            disable_auto_top=config.disable_auto_top,
        )

        result = save_model_config(modelo_id, model_cfg)

        if not result["sucesso"]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="; ".join(result.get("erros", ["Erro desconhecido"])),
            )

        return {
            "sucesso": True,
            "modelo": modelo_id,
            "avisos": result.get("avisos", []),
            "mensagem": f"Modelo '{modelo_id}' atualizado com sucesso",
        }

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/modelos/{modelo_id}", summary="Deletar um modelo")
async def deletar_modelo_endpoint(modelo_id: str) -> dict:
    """Remove um modelo do registro."""
    result = delete_model_config(modelo_id)

    if not result["sucesso"]:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=result.get("erro", "Erro desconhecido"),
        )

    return {
        "sucesso": True,
        "modelo": modelo_id,
        "mensagem": f"Modelo '{modelo_id}' deletado com sucesso",
    }


@router.post(
    "/processar-prova",
    response_model=ResultadoProva,
    response_model_exclude_none=True,
    response_model_include={"prova", "dados_aluno", "comparacao", "processado_em", "total_questoes", "total_respondidas", "imagem_anotada"},
    responses={
        400: {"model": ErroResponse},
        500: {"model": ErroResponse},
    },
    summary="Processa um gabarito de prova",
    description=(
        "Recebe imagem (PNG/JPG/JPEG) ou PDF de gabarito e retorna "
        "JSON com dados do aluno, respostas por questão e comparação com gabarito (se enviado)."
    ),
)
async def processar_prova_endpoint(
    arquivo: Annotated[UploadFile, File(description="PNG, JPG, JPEG ou PDF do gabarito")],
    prova_id: Annotated[
        Optional[int],
        Form(description="ID da prova cadastrada no banco"),
    ] = None,
    n_questoes: Annotated[int, Form(description="Total de questões (ignorado quando prova_id informado)")] = 20,
    n_alternativas: Annotated[int, Form(description="Alternativas por questão (ignorado quando prova_id informado)")] = 5,
    ra_manual: Annotated[
        Optional[str],
        Form(description="RA informado manualmente quando não detectado automaticamente"),
    ] = None,
) -> ResultadoProva:
    if arquivo.content_type not in ALLOWED_CONTENT_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Tipo não suportado: {arquivo.content_type}. Use PNG, JPG ou PDF.",
        )

    file_bytes = await arquivo.read()
    if len(file_bytes) > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=400,
            detail=f"Arquivo muito grande ({len(file_bytes)/1024/1024:.1f} MB). Limite: 20 MB.",
        )
    if len(file_bytes) == 0:
        raise HTTPException(status_code=400, detail="Arquivo vazio.")

    if prova_id is None:
        if not (1 <= n_questoes <= 500):
            raise HTTPException(status_code=400, detail="n_questoes deve estar entre 1 e 500.")
        if not (2 <= n_alternativas <= 10):
            raise HTTPException(status_code=400, detail="n_alternativas deve estar entre 2 e 10.")

    logger.info("Requisição: arquivo=%s | prova_id=%s", arquivo.filename, prova_id)

    try:
        resultado = processar_prova(
            file_bytes=file_bytes,
            filename=arquivo.filename or "upload",
            n_questoes=n_questoes,
            n_alternativas=n_alternativas,
            prova_id=prova_id,
            ra_manual=ra_manual.strip() if ra_manual else None,
        )
    except ValueError as e:
        logger.warning("Erro de validação: %s", e)
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.exception("Erro interno na pipeline")
        raise HTTPException(status_code=500, detail=f"Erro interno: {str(e)}")

    return resultado
