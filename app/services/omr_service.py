from __future__ import annotations

import base64
import logging
import os
from datetime import datetime
from typing import Any, Optional

import cv2
import numpy as np

from app.core.model_registry import ModelConfig, get_model_config
from app.services.aligner import align_sheet
from app.services.bubble_detector import annotate_results, detect_answer_grid
from app.services.ra_detector import detect_ra

logger = logging.getLogger(__name__)


def detectar_respostas_omr(
    image: np.ndarray,
    n_questoes: int,
    n_alternativas: int,
    modelo: Optional[str] = None,
    cfg: Optional[ModelConfig] = None,
) -> dict[str, Any]:
    alignment = align_sheet(image)
    aligned = alignment.aligned

    # cfg passado pelo pipeline (já montado com dados do DB) tem precedência
    if cfg is None:
        cfg = get_model_config(modelo)

    if not modelo:
        cfg.n_panels = 4 if n_questoes >= 80 else 1
        cfg.fill_threshold_empty = float(os.getenv("BUBBLE_EMPTY_THRESHOLD", "0.42"))
        cfg.fill_threshold_filled = float(os.getenv("BUBBLE_FILLED_THRESHOLD", "0.60"))

    logger.info(
        "OMR config: modelo=%s | n_panels=%d | empty=%.2f | filled=%.2f",
        modelo or "default", cfg.n_panels, cfg.fill_threshold_empty, cfg.fill_threshold_filled,
    )

    debug_dir = (
        f"debug/{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}"
        if os.getenv("DEBUG", "false").lower() == "true"
        else None
    )

    results, cells, grid_points = detect_answer_grid(
        aligned_image=aligned,
        n_questions=n_questoes,
        n_alternatives=n_alternativas,
        n_panels=cfg.n_panels,
        grid_top_ratio=cfg.grid_top_ratio,
        grid_bottom_ratio=cfg.grid_bottom_ratio,
        grid_left_ratio=cfg.grid_left_ratio,
        grid_right_ratio=cfg.grid_right_ratio,
        fill_threshold_empty=cfg.fill_threshold_empty,
        fill_threshold_filled=cfg.fill_threshold_filled,
        disable_auto_top=cfg.disable_auto_top,
        debug_dir=debug_dir,
    )

    # ── RA detection ──────────────────────────────────────────────────────────
    ra_result = None
    if cfg.ra_n_digits and cfg.ra_region:
        region = cfg.ra_region
        ra_result = detect_ra(
            aligned_image=aligned,
            n_digits=cfg.ra_n_digits,
            region_top_ratio=region.get("top", 0.02),
            region_bottom_ratio=region.get("bottom", 0.25),
            region_left_ratio=region.get("left", 0.65),
            region_right_ratio=region.get("right", 0.98),
            fill_threshold_empty=cfg.ra_fill_threshold_empty,
            fill_threshold_filled=cfg.ra_fill_threshold_filled,
            debug_dir=debug_dir,
        )
        logger.info("RA detectado: %s (conf=%.2f)", ra_result.ra, ra_result.confidence)

    respostas: dict[str, str | None] = {}
    n_ambiguas = 0

    for r in results:
        key = str(r.questao)
        if r.status == "ok":
            respostas[key] = r.resposta
        elif r.status in ("dupla_marcacao", "ambigua"):
            respostas[key] = "?"
            if r.status == "ambigua":
                n_ambiguas += 1
        else:
            respostas[key] = None

    logger.info(
        "OMR final: %d questões | %d ambíguas | folha_encontrada=%s | rotação=%.2f",
        len(respostas), n_ambiguas, alignment.sheet_found, alignment.rotation_deg,
    )

    # ── Imagem anotada em base64 ──────────────────────────────────────────────
    annotated = annotate_results(aligned, cells, results, cfg.fill_threshold_filled)
    _, buf = cv2.imencode(".jpg", annotated, [cv2.IMWRITE_JPEG_QUALITY, 82])
    imagem_anotada_b64 = base64.b64encode(buf.tobytes()).decode()

    return {
        "respostas": respostas,
        "ra": ra_result.ra if ra_result else None,
        "imagem_anotada": imagem_anotada_b64,
        "meta": {
            "sheet_found": alignment.sheet_found,
            "rotation_deg": alignment.rotation_deg,
            "n_ambiguas": n_ambiguas,
            "grid_points": grid_points if grid_points.get("panels") else None,
        },
    }
