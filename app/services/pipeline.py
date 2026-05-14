from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from app.core.config import get_settings
from app.core.model_registry import ModelConfig
from app.models.schemas import (
    ComparacaoGabarito,
    DetalheComparacao,
    RespostaQuestao,
    ResultadoProva,
    StatusQuestao,
)
from app.services.ocr_service import extract_header
from app.services.pdf_converter import bytes_to_array
from app.services.omr_service import detectar_respostas_omr
from app.services.db_service import (
    buscar_aluno_por_ra,
    buscar_modelo_gabarito,
    buscar_prova,
    salvar_resultado,
)

logger = logging.getLogger(__name__)


def processar_prova(
    file_bytes: bytes,
    filename: str,
    n_questoes: int = 20,
    n_alternativas: int = 5,
    gabarito: Optional[list[dict]] = None,
    modelo: Optional[str] = None,
    prova_id: Optional[int] = None,
    ra_manual: Optional[str] = None,
) -> ResultadoProva:
    logger.info("Pipeline: '%s' | prova_id=%s | modelo=%s", filename, prova_id, modelo or "default")

    # ── Carrega configuração da prova/modelo do banco ──────────────────────
    modelo_db = None
    if prova_id is not None:
        prova = buscar_prova(prova_id)
        if prova is None:
            raise ValueError(f"Prova {prova_id} não encontrada no banco")

        modelo_db = buscar_modelo_gabarito(prova.modelo_id)
        if modelo_db is None:
            raise ValueError(f"Modelo '{prova.modelo_id}' não encontrado no banco")

        n_questoes = modelo_db.n_questoes
        n_alternativas = modelo_db.n_alternativas
        modelo = prova.modelo_id
        if not gabarito:
            gabarito = prova.gabarito or None

        logger.info(
            "Prova '%s' (id=%d): modelo=%s | %d questões | %d alternativas",
            prova.descricao, prova_id, modelo, n_questoes, n_alternativas,
        )

    # ── Monta ModelConfig para o OMR ───────────────────────────────────────
    cfg: Optional[ModelConfig] = None
    if modelo_db is not None:
        cfg = ModelConfig(
            descricao=modelo_db.descricao,
            n_panels=modelo_db.n_panels,
            grid_top_ratio=modelo_db.grid_top_ratio,
            grid_bottom_ratio=modelo_db.grid_bottom_ratio,
            grid_left_ratio=modelo_db.grid_left_ratio,
            grid_right_ratio=modelo_db.grid_right_ratio,
            fill_threshold_empty=modelo_db.fill_threshold_empty,
            fill_threshold_filled=modelo_db.fill_threshold_filled,
            disable_auto_top=modelo_db.disable_auto_top,
            ra_n_digits=modelo_db.ra_n_digits,
            ra_region={
                "top": modelo_db.ra_region_top,
                "bottom": modelo_db.ra_region_bottom,
                "left": modelo_db.ra_region_left,
                "right": modelo_db.ra_region_right,
            } if modelo_db.ra_n_digits else None,
            ra_fill_threshold_empty=modelo_db.ra_fill_threshold_empty,
            ra_fill_threshold_filled=modelo_db.ra_fill_threshold_filled,
        )

    images = bytes_to_array(file_bytes, filename)
    if not images:
        raise ValueError("Nenhuma imagem extraída do arquivo enviado")

    image = images[0]
    logger.info("Imagem: %dx%d", image.shape[1], image.shape[0])

    # ── Extrai dados do cabeçalho via OCR ──────────────────────────────────
    settings = get_settings()
    header_info = extract_header(
        aligned_image=image,
        header_ratio=0.20,
        tesseract_cmd=settings.TESSERACT_CMD,
        lang=settings.TESSERACT_LANG,
    )
    logger.info("OCR: nome=%s | numero=%s | turma=%s", header_info.nome, header_info.numero, header_info.turma)

    # ── Detecta respostas via OMR ───────────────────────────────────────────
    resultado_omr = detectar_respostas_omr(
        image=image,
        n_questoes=n_questoes,
        n_alternativas=n_alternativas,
        modelo=modelo,
        cfg=cfg,
    )

    respostas_detectadas = resultado_omr["respostas"]
    ra_detectado = resultado_omr.get("ra")
    meta = resultado_omr["meta"]
    imagem_anotada = resultado_omr.get("imagem_anotada")



    logger.info("OMR: %d ambíguas | RA=%s", meta.get("n_ambiguas", 0), ra_detectado)

    # ra_manual tem precedência sobre RA detectado automaticamente
    ra_final = ra_manual or ra_detectado

    # ── Lookup de aluno no banco via RA ─────────────────────────────────────
    nome_db: Optional[str] = None
    if ra_final and "?" not in ra_final:
        aluno_info = buscar_aluno_por_ra(ra_final)
        if aluno_info:
            nome_db = aluno_info.nome
            logger.info("Nome DB: '%s' (RA=%s)", nome_db, aluno_info.ra)

    # ── Constrói detalhes de cada questão ──────────────────────────────────
    respostas_detalhes: dict[str, RespostaQuestao] = {}
    for i in range(1, n_questoes + 1):
        key = str(i)
        resposta_str = respostas_detectadas.get(key)

        if resposta_str is None:
            status = StatusQuestao.em_branco
        elif resposta_str == "?":
            status = StatusQuestao.ambigua
        else:
            status = StatusQuestao.ok

        respostas_detalhes[key] = RespostaQuestao(
            resposta=None if resposta_str in (None, "?") else resposta_str,
            status=status,
        )

    respondidas = sum(1 for r in respostas_detalhes.values() if r.resposta is not None)
    logger.info("Respondidas: %d/%d", respondidas, n_questoes)

    # ── Compara com gabarito ────────────────────────────────────────────────
    comparacao = _comparar_com_gabarito(respostas_detectadas, gabarito) if gabarito else None

    # ── Salva resultado no banco ────────────────────────────────────────────
    if prova_id is not None and ra_final and comparacao is not None:
        salvar_resultado(
            aluno_ra=ra_final,
            modelo_id=modelo or "",
            prova_id=prova_id,
            acertos=comparacao.total_acertos,
            erros=comparacao.total_erros,
            resultado_json={
                "respostas": {k: v.resposta for k, v in respostas_detalhes.items()},
                "comparacao": comparacao.model_dump(),
            },
        )

    return ResultadoProva(
        prova=filename,
        dados_aluno={
            "nome": nome_db or header_info.nome,
            "numero": header_info.numero,
            "turma": header_info.turma,
            "ra": ra_final,
        },
        respostas=respostas_detalhes,
        respostas_gemini=None,
        comparacao=comparacao,
        total_questoes=n_questoes,
        total_respondidas=respondidas,
        imagem_anotada=imagem_anotada,
        info_alinhamento={
            "sheet_found": meta.get("sheet_found", False),
            "rotation_deg": meta.get("rotation_deg", 0.0),
            "n_ambiguas": meta.get("n_ambiguas", 0),
        },
        processado_em=datetime.now(timezone.utc).isoformat(),
    )


def _comparar_com_gabarito(
    respostas_detectadas: dict[str, Optional[str]],
    gabarito: list[dict],
) -> ComparacaoGabarito:
    detalhes: dict[str, DetalheComparacao] = {}
    acertos = erros = em_branco = anuladas = 0
    acertos_disc: dict[str, int] = {}
    erros_disc: dict[str, int] = {}

    for i, entrada in enumerate(gabarito, start=1):
        key = str(i)
        gabarito_letra = entrada["resp"]
        disciplina: Optional[str] = entrada.get("disc")
        resposta = respostas_detectadas.get(key)
        is_anulada = gabarito_letra.lower() == "anulada"
        gabarito_display = gabarito_letra if is_anulada else gabarito_letra.upper()

        if is_anulada:
            anuladas += 1
            acerto = True
        elif resposta is None:
            em_branco += 1
            acerto = False
        elif resposta == "?":
            erros += 1
            acerto = False
        else:
            acerto = resposta == gabarito_display
            if acerto:
                acertos += 1
            else:
                erros += 1

        if disciplina and not is_anulada:
            if acerto:
                acertos_disc[disciplina] = acertos_disc.get(disciplina, 0) + 1
            else:
                erros_disc[disciplina] = erros_disc.get(disciplina, 0) + 1

        detalhes[key] = DetalheComparacao(
            resposta_aluno=resposta,
            gabarito=gabarito_display,
            acerto=acerto,
            anulada=is_anulada,
            disciplina=disciplina,
        )

    total = len(gabarito)
    questoes_validas = total - anuladas
    porcentagem = round((acertos / questoes_validas) * 100, 2) if questoes_validas > 0 else 0.0

    return ComparacaoGabarito(
        total_acertos=acertos,
        total_erros=erros,
        total_em_branco=em_branco,
        total_anuladas=anuladas,
        total_questoes=total,
        porcentagem_acerto=porcentagem,
        detalhes=detalhes,
        acertos_por_disciplina=acertos_disc,
        erros_por_disciplina=erros_disc,
    )
