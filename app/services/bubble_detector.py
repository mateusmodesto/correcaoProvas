from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import cv2
import numpy as np

logger = logging.getLogger(__name__)

ALTERNATIVES = ["A", "B", "C", "D", "E", "F", "G", "H", "I", "J"]


@dataclass
class BubbleCell:
    row: int       # índice global de questão (0-based)
    col: int       # índice da alternativa (0-based: 0=A, …)
    x: int         # coordenada na imagem original
    y: int
    w: int
    h: int
    fill_ratio: float
    crop: np.ndarray = field(repr=False)


@dataclass
class QuestionResult:
    questao: int           # 1-based
    resposta: Optional[str]
    status: str            # ok | em_branco | dupla_marcacao | ambigua
    confianca: float
    filled_cols: list[int] = field(default_factory=list)
    ambiguous_crop: Optional[np.ndarray] = field(default=None, repr=False)


def detect_answer_grid(
    aligned_image: np.ndarray,
    n_questions: int,
    n_alternatives: int,
    n_panels: int = 4,
    grid_top_ratio: float = 0.35,
    grid_bottom_ratio: float = 0.99,
    grid_left_ratio: float = 0.02,
    grid_right_ratio: float = 0.98,
    fill_threshold_empty: float = 0.14,
    fill_threshold_filled: float = 0.38,
    disable_auto_top: bool = False,
    debug_dir: Optional[str] = None,
) -> tuple[list[QuestionResult], list[BubbleCell], dict]:
    """
    Pipeline de detecção:
    1. Tenta encontrar a seção de respostas automaticamente (projeção horizontal)
    2. Faz o crop da região de respostas ANTES de procurar bolhas
    3. Detecta candidatos circulares apenas nessa região
    4. Usa histograma X/Y para localizar a grade (robusto com múltiplos painéis)
    5. Fallback para grade fixa se o histograma falhar
    """
    # if debug_dir:
    #     Path(debug_dir).mkdir(parents=True, exist_ok=True)
    #     cv2.imwrite(str(Path(debug_dir) / "00_original.jpg"), aligned_image)

    gray = (cv2.cvtColor(aligned_image, cv2.COLOR_BGR2GRAY)
            if len(aligned_image.shape) == 3 else aligned_image.copy())
    # if debug_dir:
    #     cv2.imwrite(str(Path(debug_dir) / "01_gray.jpg"), gray)
    # CLAHE mais agressivo: cobre gradiente de iluminação de fotos de celular
    clahe = cv2.createCLAHE(clipLimit=3.5, tileGridSize=(16, 16))
    gray = clahe.apply(gray)
    # if debug_dir:
    #     cv2.imwrite(str(Path(debug_dir) / "02_clahe.jpg"), gray)

    h_full, w_full = gray.shape

    # ── Tenta detectar automaticamente onde começa a seção de respostas ──────
    if disable_auto_top:
        logger.info("Auto-detecção do topo desativada pelo modelo; usando grid_top_ratio=%.2f", grid_top_ratio)
    else:
        auto_top = _detect_answer_section_top(gray, grid_top_ratio, grid_bottom_ratio)
        if auto_top is not None:
            logger.info("Seção de respostas detectada automaticamente: topo=%.1f%%", auto_top * 100)
            grid_top_ratio = auto_top

    # ── Crop para a região de respostas ──────────────────────────────────────
    crop_y1 = int(h_full * grid_top_ratio)
    crop_y2 = int(h_full * grid_bottom_ratio)
    crop_x1 = int(w_full * grid_left_ratio)
    crop_x2 = int(w_full * grid_right_ratio)

    # if debug_dir:
    #     Path(debug_dir).mkdir(parents=True, exist_ok=True)
    #     pre_crop = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
    #     cv2.rectangle(pre_crop, (crop_x1, crop_y1), (crop_x2, crop_y2), (0, 255, 0), 3)
    #     cv2.putText(pre_crop, f"crop: y={crop_y1}-{crop_y2} x={crop_x1}-{crop_x2}",
    #                 (crop_x1, max(crop_y1 - 10, 20)),
    #                 cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
    #     cv2.imwrite(str(Path(debug_dir) / "00_pre_crop.jpg"), pre_crop)

    gray_crop = gray[crop_y1:crop_y2, crop_x1:crop_x2]
    # if debug_dir:
    #     cv2.imwrite(str(Path(debug_dir) / "03_crop.jpg"), gray_crop)

    # Brilho de referência do fundo: percentil 90 da região de respostas.
    # Normaliza o fill_ratio independente do brilho da foto (scan escuro/claro).
    bg_brightness = float(np.percentile(gray_crop.astype(np.float32), 90))
    logger.info("Brilho de fundo (p90): %.1f/255", bg_brightness)

    logger.debug(
        "Região de respostas: y=[%d:%d] x=[%d:%d] (%dx%d px)",
        crop_y1, crop_y2, crop_x1, crop_x2,
        gray_crop.shape[1], gray_crop.shape[0],
    )

    # ── Detecta candidatos SOMENTE dentro da região de respostas ─────────────
    candidates_local = _find_bubble_candidates(gray_crop, debug_dir=debug_dir)

    # Mapeia de volta para coordenadas da imagem completa
    candidates = [(x + crop_x1, y + crop_y1, w, h)
                  for x, y, w, h in candidates_local]

    expected = n_questions * n_alternatives
    n_per_panel = n_questions // n_panels
    logger.info("Candidatos na região de respostas: %d (esperado ~%d)", len(candidates), expected)

    # ── Passos 1-4: assign KMeans (multi-painel) ─────────────────────────────
    from sklearn.cluster import KMeans as _KMeans
    cells_kmeans: list[BubbleCell] = []
    grid_points: dict = {"panels": [], "image_w": w_full, "image_h": h_full}

    if n_panels > 1 and len(candidates) >= expected * 0.25:
        # Passo 1: KMeans X global → n_panels*(n_alternatives+1) colunas
        cx_all = np.array([x + w / 2.0 for x, y, w, h in candidates])

        # Remove candidatos espúrios antes do KMeans: X muito isolado do vizinho mais próximo
        cx_sorted = np.sort(cx_all)
        expected_col_spacing = (float(cx_sorted[-1]) - float(cx_sorted[0])) / (n_panels * (n_alternatives + 1))
        isolation_threshold = expected_col_spacing * 1.5
        keep_mask = np.ones(len(cx_all), dtype=bool)
        for i, cx in enumerate(cx_all):
            dists = np.abs(cx_all - cx)
            dists[i] = np.inf
            min_dist = float(np.min(dists))
            if min_dist > isolation_threshold:
                keep_mask[i] = False
        candidates_filtered = [c for c, k in zip(candidates, keep_mask) if k]
        n_removed = int(np.sum(~keep_mask))
        if n_removed:
            logger.info("Passo1 filtro espúrios: removidos %d candidatos isolados (threshold=%.1fpx)", n_removed, isolation_threshold)
        cx_all = np.array([c[0] + c[2] / 2.0 for c in candidates_filtered])

        n_col_total = n_panels * (n_alternatives + 1)
        km_global = _KMeans(n_clusters=n_col_total, n_init=10, random_state=0)
        km_global.fit(cx_all.reshape(-1, 1))
        all_col_centers = sorted(float(c[0]) for c in km_global.cluster_centers_)

        # Agrupa os centros em n_panels grupos de (n_alternatives+1) colunas
        cols_per_panel = n_alternatives + 1
        panel_col_centers = [all_col_centers[i*cols_per_panel:(i+1)*cols_per_panel]
                             for i in range(n_panels)]

        # Boundaries = ponto médio entre última coluna de painel i e primeira de painel i+1
        panel_boundaries = [0.0]
        for i in range(n_panels - 1):
            mid = (panel_col_centers[i][-1] + panel_col_centers[i+1][0]) / 2.0
            panel_boundaries.append(mid)
        panel_boundaries.append(float(w_full))

        panels_candidates: list[list[tuple]] = [[] for _ in range(n_panels)]
        for c in candidates:
            cx = c[0] + c[2] / 2.0
            for pi in range(n_panels):
                if panel_boundaries[pi] <= cx < panel_boundaries[pi + 1]:
                    panels_candidates[pi].append(c)
                    break

        # if debug_dir:
        #     _panel_colors = [(255, 80, 80), (80, 200, 80), (80, 120, 255), (255, 200, 0)]
        #     _dbg_p1 = (aligned_image.copy() if len(aligned_image.shape) == 3
        #                else cv2.cvtColor(aligned_image, cv2.COLOR_GRAY2BGR))
        #     for pi, pc in enumerate(panels_candidates):
        #         color = _panel_colors[pi % len(_panel_colors)]
        #         for x, y, w, h in pc:
        #             cv2.rectangle(_dbg_p1, (x, y), (x + w, y + h), color, 1)
        #         bx = int(panel_boundaries[pi + 1])
        #         cv2.line(_dbg_p1, (bx, crop_y1), (bx, crop_y2), (255, 255, 255), 2)
        #         cv2.putText(_dbg_p1, f"P{pi}", (int(panel_boundaries[pi]) + 5, crop_y1 + 25),
        #                     cv2.FONT_HERSHEY_SIMPLEX, 0.8, color, 2)
        #     cv2.imwrite(str(Path(debug_dir) / "passo1_paineis.jpg"), _dbg_p1)
        #     _dbg_p2 = cv2.cvtColor(aligned_image, cv2.COLOR_GRAY2BGR) if len(aligned_image.shape) == 2 else aligned_image.copy()
        #     _dbg_p3 = _dbg_p2.copy()
        #     _dbg_p4 = _dbg_p2.copy()

        kmeans_ok = True
        for pi, pc in enumerate(panels_candidates):
            cx_vals = sorted([c[0] + c[2] / 2.0 for c in pc])
            logger.info(
                "PASSO1 Painel %d: %d candidatos | x=[%.1f..%.1f] | boundary=[%.1f..%.1f]",
                pi, len(pc),
                cx_vals[0] if cx_vals else 0, cx_vals[-1] if cx_vals else 0,
                panel_boundaries[pi], panel_boundaries[pi + 1],
            )

            # Passo 2: usa col_centers já calculados pelo KMeans global
            col_centers = list(panel_col_centers[pi])
            if len(col_centers) < n_alternatives + 1:
                logger.warning("PASSO2 Painel %d: col_centers insuficientes (%d) → fallback", pi, len(col_centers))
                kmeans_ok = False
                break
            cx_arr = np.array(cx_vals)

            half_gap_x = (col_centers[1] - col_centers[0]) / 2 if len(col_centers) >= 2 else 20.0
            col_counts = [int(np.sum(np.abs(cx_arr - c) < half_gap_x)) for c in col_centers]
            logger.info("PASSO2 Painel %d: col_centers=%s counts=%s",
                        pi, [round(c, 1) for c in col_centers], col_counts)

            # if debug_dir:
            #     max_count = max(col_counts) if col_counts else 1
            #     for ci, (cx_c, cnt) in enumerate(zip(col_centers, col_counts)):
            #         is_index = ci == 0
            #         color = (0, 0, 220) if is_index else (0, 200, 80)
            #         x_int = int(cx_c)
            #         cv2.line(_dbg_p2, (x_int, crop_y1), (x_int, crop_y2), color, 2)
            #         cv2.putText(_dbg_p2, f"{'idx' if is_index else chr(65+ci-1)}({cnt})",
            #                     (x_int - 10, crop_y1 + 45 + pi * 18),
            #                     cv2.FONT_HERSHEY_SIMPLEX, 0.38, color, 1)

            # Passo 3: KMeans Y → n_per_panel linhas
            cy_arr = np.array(sorted([c[1] + c[3] / 2.0 for c in pc]))
            if len(cy_arr) < n_per_panel:
                logger.warning("PASSO3 Painel %d: candidatos Y insuficientes (%d) → fallback", pi, len(cy_arr))
                kmeans_ok = False
                break
            km_y = _KMeans(n_clusters=n_per_panel, n_init=5, random_state=0)
            km_y.fit(cy_arr.reshape(-1, 1))
            row_centers = sorted(float(c[0]) for c in km_y.cluster_centers_)
            half_gap_y = (row_centers[1] - row_centers[0]) / 2 if len(row_centers) >= 2 else 15.0
            row_counts = [int(np.sum(np.abs(cy_arr - r) < half_gap_y)) for r in row_centers]
            logger.info("PASSO3 Painel %d: row_centers(primeiros5)=%s ... row_centers(ultimos5)=%s | counts min=%d max=%d median=%d",
                        pi,
                        [round(r, 1) for r in row_centers[:5]],
                        [round(r, 1) for r in row_centers[-5:]],
                        min(row_counts), max(row_counts), int(np.median(row_counts)))

            grid_points["panels"].append({
                "painel": pi,
                "col_centers": [round(c, 1) for c in col_centers],  # [idx, A, B, C, D, E]
                "row_centers": [round(r, 1) for r in row_centers],  # [Q1..Q25]
            })

            # if debug_dir:
            #     for ri, (ry, cnt) in enumerate(zip(row_centers, row_counts)):
            #         ok = abs(cnt - int(np.median(row_counts))) <= 2
            #         color = (0, 200, 80) if ok else (0, 0, 220)
            #         y_int = int(ry)
            #         cv2.line(_dbg_p3, (0, y_int), (_dbg_p3.shape[1], y_int), color, 1)
            #         cv2.putText(_dbg_p3, f"R{ri+1}({cnt})", (5 + pi * 80, y_int - 2),
            #                     cv2.FONT_HERSHEY_SIMPLEX, 0.3, color, 1)

            # Passo 4: assign — cada candidato → coluna+linha mais próxima
            # bg local do painel
            panel_xs = [c[0] for c in pc]
            px1 = max(0, min(panel_xs) - 5)
            px2 = min(gray.shape[1], max(c[0] + c[2] for c in pc) + 5)
            panel_strip = gray[:, px1:px2]
            panel_bg = float(np.percentile(panel_strip.astype(np.float32), 90))
            panel_bg = max(panel_bg, bg_brightness * 0.85)

            avg_w_global = float(np.median([c[2] for c in candidates]))
            avg_w_panel = float(np.median([c[2] for c in pc]))
            fill_scale = (avg_w_global / avg_w_panel) ** 0.5 if avg_w_panel > 0 else 1.0

            col_tol = half_gap_x
            row_tol = half_gap_y

            # grade: (row_global, col_alt) → melhor candidato por distância
            grid: dict[tuple[int, int], tuple[float, tuple]] = {}
            for cand in pc:
                cx = cand[0] + cand[2] / 2.0
                cy = cand[1] + cand[3] / 2.0
                # coluna mais próxima
                ci = int(np.argmin([abs(cx - cc) for cc in col_centers]))
                if abs(cx - col_centers[ci]) > col_tol:
                    continue
                if ci == 0:  # índice → ignorar
                    continue
                col_alt = ci - 1  # 0=A, 1=B, ...
                # linha mais próxima
                ri = int(np.argmin([abs(cy - rc) for rc in row_centers]))
                if abs(cy - row_centers[ri]) > row_tol:
                    continue
                row_global = pi * n_per_panel + ri
                dist = abs(cx - col_centers[ci]) + abs(cy - row_centers[ri])
                key = (row_global, col_alt)
                if key not in grid or dist < grid[key][0]:
                    grid[key] = (dist, cand)

            for (row_global, col_alt), (_, cand) in grid.items():
                x, y, w, h = cand
                crop = gray[max(0, y):y + h, max(0, x):x + w]
                fill = min(1.0, _compute_fill_ratio(crop, panel_bg) * fill_scale)
                cells_kmeans.append(BubbleCell(
                    row=row_global, col=col_alt,
                    x=x, y=y, w=w, h=h,
                    fill_ratio=fill, crop=crop,
                ))

            logger.info("PASSO4 Painel %d: %d células atribuídas (esperado %d)",
                        pi, sum(1 for k in grid if k[0] // n_per_panel == pi), n_per_panel * n_alternatives)

            # if debug_dir:
            #     for cell in cells_kmeans:
            #         if cell.row // n_per_panel == pi:
            #             letra = ALTERNATIVES[cell.col] if cell.col < len(ALTERNATIVES) else str(cell.col)
            #             is_filled = cell.fill_ratio >= fill_threshold_filled
            #             color = (0, 140, 255) if is_filled else (50, 200, 50)
            #             cv2.rectangle(_dbg_p4, (cell.x, cell.y), (cell.x + cell.w, cell.y + cell.h),
            #                           color, 2 if is_filled else 1)
            #             cv2.putText(_dbg_p4, f"Q{cell.row+1}{letra}",
            #                         (cell.x + 1, cell.y + 9),
            #                         cv2.FONT_HERSHEY_SIMPLEX, 0.2, (0, 0, 180), 1)

        # if debug_dir:
        #     cv2.imwrite(str(Path(debug_dir) / "passo2_colunas.jpg"), _dbg_p2)
        #     cv2.imwrite(str(Path(debug_dir) / "passo3_linhas.jpg"), _dbg_p3)
        #     cv2.imwrite(str(Path(debug_dir) / "passo4_assign.jpg"), _dbg_p4)

        if not kmeans_ok:
            cells_kmeans = []

    # ── Atribuição de células ─────────────────────────────────────────────────
    cells: list[BubbleCell] = []

    if cells_kmeans:
        cells = cells_kmeans
        logger.info("Células atribuídas via KMeans: %d", len(cells))
    elif len(candidates) >= expected * 0.25:
        if n_panels > 1:
            cells = _assign_multipanel(
                candidates, gray, n_questions, n_alternatives, n_panels, n_per_panel,
                bg_brightness=bg_brightness,
                grid_top_y=crop_y1,
            )
        else:
            cells = _assign_histogram(
                candidates, gray, n_questions, n_alternatives,
                bg_brightness=bg_brightness,
                grid_top_y=crop_y1,
            )
        logger.info("Células atribuídas via histograma: %d", len(cells))

    if len(cells) < expected * 0.25:
        logger.warning("Histograma insuficiente → fallback para grade fixa")
        cells = _assign_fixed(
            gray, n_questions, n_alternatives, n_panels,
            grid_top_ratio, grid_bottom_ratio, grid_left_ratio, grid_right_ratio,
            bg_brightness=bg_brightness,
        )

    # ── Debug passo-a-passo: células atribuídas sobre o crop ──────────────────
    # if debug_dir:
    #     dbg_cells = cv2.cvtColor(gray_crop.copy(), cv2.COLOR_GRAY2BGR)
    #     for cell in cells:
    #         cx = cell.x - crop_x1
    #         cy = cell.y - crop_y1
    #         letra = ALTERNATIVES[cell.col] if cell.col < len(ALTERNATIVES) else str(cell.col)
    #         is_filled = cell.fill_ratio >= fill_threshold_filled
    #         color = (0, 140, 255) if is_filled else (50, 200, 50)
    #         cv2.rectangle(dbg_cells, (cx, cy), (cx + cell.w, cy + cell.h), color, 2 if is_filled else 1)
    #         cv2.putText(dbg_cells, f"Q{cell.row+1}{letra}", (cx + 1, cy + 9),
    #                     cv2.FONT_HERSHEY_SIMPLEX, 0.2, (0, 0, 180), 1)
    #     cv2.imwrite(str(Path(debug_dir) / "04_cells_assigned.jpg"), dbg_cells)

    # ── Debug final ───────────────────────────────────────────────────────────
    # if debug_dir:
    #     _save_debug(aligned_image, candidates, cells, crop_y1, crop_y2, crop_x1, crop_x2, debug_dir)

    # ── Auto-calibração de thresholds ─────────────────────────────────────────
    # Ajusta thresholds dinamicamente usando distribuição bimodal dos fills.
    # Fotos longe/escuras têm fills menores — calibrar por imagem é mais robusto
    # do que usar constantes globais.
    fill_threshold_empty, fill_threshold_filled = _autocalibrate_thresholds(
        cells, fill_threshold_empty, fill_threshold_filled
    )

    # ── Classificação ─────────────────────────────────────────────────────────
    results: list[QuestionResult] = []
    for q in range(n_questions):
        row_cells = [c for c in cells if c.row == q]
        result = _classify_question(q + 1, row_cells, fill_threshold_empty, fill_threshold_filled)
        results.append(result)

        # Log de cada questão: alternativas detectadas com x,fill%, e resultado
        if row_cells:
            alts = " | ".join(
                f"{ALTERNATIVES[c.col] if c.col < len(ALTERNATIVES) else c.col}(x={c.x})={c.fill_ratio:.2f}"
                for c in sorted(row_cells, key=lambda c: c.col)
            )
        else:
            alts = "sem células"
        logger.info("Q%03d [%s] → %s  (%s)", q + 1, alts, result.resposta or result.status, result.status)

    filled = sum(1 for r in results if r.status == "ok")
    ambiguous = sum(1 for r in results if r.status == "ambigua")
    blank = sum(1 for r in results if r.status == "em_branco")
    logger.info("Classificação: %d preenchidas | %d ambíguas | %d em_branco", filled, ambiguous, blank)

    # Log da distribuição de fill ratios para calibrar threshold
    all_fills = [c.fill_ratio for c in cells]
    if all_fills:
        fills_sorted = sorted(all_fills, reverse=True)
        top10 = [f"{v:.2f}" for v in fills_sorted[:10]]
        logger.info("Top-10 fill ratios: %s", " ".join(top10))
        fills_arr = np.array(all_fills)
        logger.info("Fill stats: min=%.2f p25=%.2f median=%.2f p75=%.2f p90=%.2f max=%.2f",
                    float(np.min(fills_arr)), float(np.percentile(fills_arr.astype(np.float32), 25)),
                    float(np.median(fills_arr)), float(np.percentile(fills_arr.astype(np.float32), 75)),
                    float(np.percentile(fills_arr.astype(np.float32), 90)), float(np.max(fills_arr)))

    return results, cells, grid_points


# ─── Detecção automática do topo da seção de respostas ───────────────────────

def _detect_answer_section_top(
    gray: np.ndarray,
    search_start: float,
    search_end: float,
) -> Optional[float]:
    """
    Encontra onde começa a grelha de respostas usando projeção horizontal.
    Busca a última linha densa de texto/linha antes da grade (ex: "RESPOSTAS").
    Retorna ratio (0.0–1.0) ou None se não encontrar.
    """
    h, w = gray.shape
    y1 = int(h * search_start)
    # Limit search to first 30% of the candidate region so horizontal lines
    # inside the answer grid (cell borders, mid-sheet separators) are not
    # mistaken for the header/separator that precedes the grid.
    search_cap = search_start + (search_end - search_start) * 0.30
    y2 = int(h * min(search_cap, search_end))

    region = gray[y1:y2, :]
    _, thresh = cv2.threshold(region, 0, 255, cv2.THRESH_BINARY_INV | cv2.THRESH_OTSU)

    # Projeção horizontal: soma de pixels escuros por linha
    projection = thresh.sum(axis=1).astype(float)

    # Suaviza para remover ruído
    kernel = np.ones(5, dtype=float) / 5.0
    projection = np.convolve(projection.astype(np.float64), kernel, mode="same")

    # Linha "densa" = muito acima da média (provavelmente o separador ou "RESPOSTAS")
    mean_proj = projection.mean()
    threshold_line = mean_proj * 2.5
    dense_rows = np.where(projection > threshold_line)[0]

    if len(dense_rows) == 0:
        return None

    # O topo da grade começa logo após a última linha densa.
    # offset_px negativo recua o corte para não perder Q1/Q2.
    # -50px: margem suficiente mesmo com CLAHE agressivo amplificando a projeção.
    last_dense = int(dense_rows[-1])
    offset_px = -50

    answer_top_px = y1 + last_dense + offset_px
    answer_top_ratio = answer_top_px / h

    # Sanidade: deve estar entre 20% e 85% da imagem
    if not (0.20 <= answer_top_ratio <= 0.85):
        return None

    return answer_top_ratio


# ─── NMS: remove contornos que contêm outros menores ─────────────────────────

def _nms_contained(candidates: list[tuple[int, int, int, int]]) -> list[tuple[int, int, int, int]]:
    """
    Remove candidatos que contêm quase totalmente outro candidato menor.
    Mantém o menor (normalmente a bolha real) e descarta a caixa maior.

    Limite: candidato maior só é descartado se sua área for < 8x a do menor.
    Contornos gigantes (sombra, mancha) não devem eliminar bolhas reais.
    """
    if len(candidates) <= 1:
        return candidates

    by_area = sorted(candidates, key=lambda c: c[2] * c[3])
    keep: list[tuple[int, int, int, int]] = []
    discard = set()

    for i, (x1, y1, w1, h1) in enumerate(by_area):
        if i in discard:
            continue

        keep.append((x1, y1, w1, h1))
        small_area = w1 * h1

        for j in range(i + 1, len(by_area)):
            if j in discard:
                continue

            x2, y2, w2, h2 = by_area[j]

            # Não descarta candidato muito maior que o menor — provavelmente
            # é um contorno espúrio (sombra, mancha) que cobre região maior
            if w2 * h2 > small_area * 8:
                continue

            ix1, iy1 = max(x1, x2), max(y1, y2)
            ix2, iy2 = min(x1 + w1, x2 + w2), min(y1 + h1, y2 + h2)

            if ix2 <= ix1 or iy2 <= iy1:
                continue

            inter = (ix2 - ix1) * (iy2 - iy1)

            if small_area > 0 and inter / small_area > 0.80:
                discard.add(j)

    return keep


# ─── Candidatos circulares ────────────────────────────────────────────────────

def _find_bubble_candidates(gray: np.ndarray, debug_dir: Optional[str] = None) -> list[tuple[int, int, int, int]]:
    """
    Detecta candidatos a bolhas/quadrados de resposta com limites ADAPTATIVOS.
    Funciona com qualquer forma geométrica (círculo, quadrado, retângulo, etc.).
    Opera sobre a imagem JÁ RECORTADA para a região de respostas.
    """
    import time as _time
    _ts = int(_time.time()) if debug_dir else 0

    def _dbg_save(img: np.ndarray, name: str) -> None:
        if not debug_dir:
            return
        from pathlib import Path as _Path
        _Path(debug_dir).mkdir(parents=True, exist_ok=True)
        cv2.imwrite(str(_Path(debug_dir) / f"cand_{_ts}_{name}.jpg"), img)

    blurred = cv2.GaussianBlur(gray, (5, 5), 0)
    # _dbg_save(blurred, "1_blur")

    # Otsu por faixa horizontal: evita que sombra localizada (canto escuro) eleve
    # o threshold global e inverta toda a região sombreada em blob branco gigante.
    # Divide em 8 faixas; faixas onde o threshold Otsu > 180 (sombra pesada) são
    # descartadas — nesses casos o adaptive local já é suficiente.
    h_img, w_img = blurred.shape[:2]
    n_strips = 8
    strip_h = max(1, h_img // n_strips)
    otsu = np.zeros_like(blurred)
    for i in range(n_strips):
        y1s = i * strip_h
        y2s = h_img if i == n_strips - 1 else (i + 1) * strip_h
        strip = blurred[y1s:y2s, :]
        tval, strip_otsu = cv2.threshold(strip, 0, 255, cv2.THRESH_BINARY_INV | cv2.THRESH_OTSU)
        if tval <= 180:  # threshold alto = sombra/fundo escuro → descarta faixa
            otsu[y1s:y2s, :] = strip_otsu
    # _dbg_save(otsu, "2_otsu")

    adaptive = cv2.adaptiveThreshold(
        blurred, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY_INV, 15, 4
    )
    # _dbg_save(adaptive, "3_adaptive")

    thresh = cv2.bitwise_or(otsu, adaptive)
    # _dbg_save(thresh, "4_combined")

    # MORPH_RECT funciona igualmente bem para formas circulares e quadradas
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
    thresh = cv2.morphologyEx(thresh, cv2.MORPH_CLOSE, kernel)
    # _dbg_save(thresh, "5_morph")

    contours, _ = cv2.findContours(thresh, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    h_img, w_img = gray.shape

    raw: list[tuple[int, int, int, int, float]] = []
    for cnt in contours:
        area = cv2.contourArea(cnt)
        if area < 10:
            continue
        if area > w_img * h_img * 0.08:
            continue
        x, y, w, h = cv2.boundingRect(cnt)
        # descarta candidatos muito abaixo (ruído fora da grade)
        if y > gray.shape[0] * 0.97:
            continue
        if w == 0 or h == 0:
            continue
        # Aceita proporções compatíveis com círculos, quadrados e retângulos leves
        if not (0.35 <= w / h <= 2.80):
            continue
        peri = cv2.arcLength(cnt, True)
        if peri == 0:
            continue
        # Limiar de compacidade muito baixo: aceita qualquer forma razoavelmente compacta.
        # Círculo perfeito ≈ 1.0 | Quadrado ≈ 0.785 | Retângulo 2:1 ≈ 0.698
        # Threshold 0.10 rejeita apenas formas muito irregulares (ruído, texto solto).
        if 4 * np.pi * area / (peri ** 2) < 0.10:
            continue
        raw.append((x, y, w, h, area))

    if not raw:
        logger.warning("Nenhum candidato detectado")
        return []

    # Debug: todos os contornos antes de filtrar
    # if debug_dir:
    #     dbg6 = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
    #     for x, y, w, h, _ in raw:
    #         cv2.rectangle(dbg6, (x, y), (x + w, y + h), (255, 0, 0), 1)
    #     _dbg_save(dbg6, "6_all_contours")

    # Filtra pelo tamanho modal com range amplo
    areas = np.array([r[4] for r in raw], dtype=float)
    log_areas = np.log1p(areas)
    hist, bin_edges = np.histogram(log_areas, bins=min(30, len(raw)))
    peak_bin = int(np.argmax(hist))
    peak_area = float(np.expm1((bin_edges[peak_bin] + bin_edges[peak_bin + 1]) / 2.0))
    lo, hi = peak_area * 0.20, peak_area * 4.00
    filtered = [(x, y, w, h) for x, y, w, h, a in raw if lo <= a <= hi]
    logger.info("Candidatos: %d → %d após filtro de área (modal=%.0f, range=[%.0f, %.0f])",
                len(raw), len(filtered), peak_area, lo, hi)

    # Debug: após filtro de área
    # if debug_dir:
    #     dbg7 = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
    #     for x, y, w, h in filtered:
    #         cv2.rectangle(dbg7, (x, y), (x + w, y + h), (0, 200, 0), 1)
    #     _dbg_save(dbg7, "7_filtered_area")

    # NMS: RETR_LIST retorna contornos aninhados (bolha + borda da célula que a contém).
    # Remove candidatos que contêm outro candidato menor — mantém o menor (= a bolha).
    if filtered:
        w_img_local = gray.shape[1]
        quartis = [int(w_img_local * q) for q in [0.25, 0.50, 0.75]]
        def _count_in_band(cands, x_lo, x_hi):
            return sum(1 for x, y, w, h in cands if x_lo <= x + w/2 < x_hi)
        pre_bands = [
            _count_in_band(filtered, 0, quartis[0]),
            _count_in_band(filtered, quartis[0], quartis[1]),
            _count_in_band(filtered, quartis[1], quartis[2]),
            _count_in_band(filtered, quartis[2], w_img_local),
        ]
        logger.info("Candidatos pré-NMS por quartil X: %s (total=%d)", pre_bands, len(filtered))

    filtered = _nms_contained(filtered)

    if filtered:
        post_bands = [
            _count_in_band(filtered, 0, quartis[0]),
            _count_in_band(filtered, quartis[0], quartis[1]),
            _count_in_band(filtered, quartis[1], quartis[2]),
            _count_in_band(filtered, quartis[2], w_img_local),
        ]
        logger.info("Candidatos pós-NMS por quartil X: %s (total=%d)", post_bands, len(filtered))
    else:
        logger.info("Candidatos após NMS: 0")

    # Debug: candidatos finais após NMS
    # if debug_dir:
    #     dbg8 = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
    #     for x, y, w, h in filtered:
    #         cv2.rectangle(dbg8, (x, y), (x + w, y + h), (0, 255, 0), 2)
    #     _dbg_save(dbg8, "8_nms_final")

    return filtered


# ─── Segmentação de painéis por cluster X ────────────────────────────────────

def _split_panels_by_x(
    candidates: list[tuple[int, int, int, int]],
    n_panels: int,
) -> list[list[tuple[int, int, int, int]]]:
    """
    Agrupa candidatos em n_panels grupos usando KMeans sobre coordenada X central.
    Retorna lista de grupos ordenados da esquerda para a direita.
    Substitui a divisão por faixas fixas (panel_width), que falha quando painéis
    têm larguras diferentes na imagem real.
    """
    from sklearn.cluster import KMeans

    cx = np.array([[c[0] + c[2] / 2.0] for c in candidates], dtype=float)
    kmeans = KMeans(n_clusters=n_panels, n_init=10, random_state=42)
    labels = kmeans.fit_predict(cx)

    panels: list[list[tuple[int, int, int, int]]] = [[] for _ in range(n_panels)]
    for c, label in zip(candidates, labels):
        panels[label].append(c)

    return sorted(
        panels,
        key=lambda panel: float(np.mean([c[0] + c[2] / 2.0 for c in panel])) if panel else 0.0,
    )


# ─── Multi-painel via histograma X/Y ─────────────────────────────────────────

def _assign_multipanel(
    candidates: list[tuple[int, int, int, int]],
    gray: np.ndarray,
    n_questions: int,
    n_alternatives: int,
    n_panels: int,
    n_per_panel: int,
    bg_brightness: float = 255.0,
    grid_top_y: int = 0,
) -> list[BubbleCell]:
    """
    Versão estável:
    - divide por painel
    - detecta colunas A..E por picos X simples
    - estima a coluna âncora à esquerda
    - reconstrói linhas por coluna âncora
    - associa candidatos à coluna e linha mais próximas
    """
    if not candidates:
        return []

    avg_w = float(np.median([c[2] for c in candidates]))
    avg_h = float(np.median([c[3] for c in candidates]))

    panels_by_x = _split_panels_by_x(candidates, n_panels)

    # y_min_bound global: Y do candidato mais alto entre TODOS os painéis.
    # Usar crop_y1 (grid_top_y) faz a regressão extrapolar a grade para antes de Q1
    # quando há um gap entre o topo da seção e a primeira linha real de bolhas.
    # Usar o mínimo global garante sincronização entre painéis.
    global_min_y = float(min(c[1] + c[3] / 2.0 for c in candidates))

    grid: dict[tuple[int, int], tuple] = {}

    # Acumula col_spacing real de cada painel para interpolar painéis ruins
    panel_col_spacings: dict[int, float] = {}

    for pi, panel_candidates in enumerate(panels_by_x):

        if len(panel_candidates) < max(20, n_per_panel):
            logger.warning("Painel %d: poucos candidatos (%d)", pi, len(panel_candidates))
            continue

        panel_cx = np.array([c[0] + c[2] / 2.0 for c in panel_candidates], dtype=float)

        # Busca n_alternatives + 2 picos: painel tem âncora + A..E, total n+1 colunas.
        # Buscar apenas n_alternatives captura âncora como col-0 e exclui a última alternativa.
        n_search = n_alternatives + 2
        panel_span = float(panel_cx.max() - panel_cx.min()) if len(panel_cx) > 1 else avg_w * n_search
        bw_inner = max(4.0, panel_span / (n_search * 3))
        peaks = _histogram_peaks(panel_cx, n_search, bandwidth=bw_inner)

        if peaks is not None and len(peaks) >= n_alternatives:
            peaks_list = sorted(peaks.tolist())
        else:
            # fallback: quantis com n_alternatives + 1 slots
            peaks_list = []
            sorted_cx = np.sort(panel_cx)
            n_slots = n_alternatives + 1
            for k in range(n_slots):
                lo_q = k * 100.0 / n_slots
                hi_q = (k + 1) * 100.0 / n_slots
                lo_v = float(np.percentile(sorted_cx.astype(np.float32), lo_q)) if k > 0 else float(sorted_cx.min()) - 1
                hi_v = float(np.percentile(sorted_cx.astype(np.float32), hi_q)) if k < n_slots - 1 else float(sorted_cx.max()) + 1
                slot = sorted_cx[(sorted_cx > lo_v) & (sorted_cx <= hi_v)]
                peaks_list.append(float(np.median(slot)) if len(slot) > 0 else (lo_v + hi_v) / 2)

        peaks_list = sorted(set(peaks_list))
        logger.info("Painel %d: peaks_list=%s", pi, [round(p, 1) for p in peaks_list])

        # Seleciona o subconjunto de n_alternatives picos mais uniformemente espaçados.
        # A âncora (nº da questão) quebra o padrão uniforme; a combinação mais uniforme
        # são as colunas de resposta reais.
        if len(peaks_list) >= n_alternatives + 1:
            from itertools import combinations as _comb
            best_cv = float('inf')
            best_answer_cols = sorted(peaks_list[1:1 + n_alternatives])  # fallback seguro

            for combo in _comb(peaks_list, n_alternatives):
                combo_sorted = sorted(combo)
                gaps = [combo_sorted[i + 1] - combo_sorted[i] for i in range(len(combo_sorted) - 1)]
                mean_g = float(np.mean(gaps)) if gaps else 0.0
                if mean_g <= 0:
                    continue
                cv = float(np.std(gaps)) / mean_g
                if cv < best_cv:
                    best_cv = cv
                    best_answer_cols = combo_sorted

            answer_cols_x = sorted(best_answer_cols)
        else:
            answer_cols_x = sorted(peaks_list)[:n_alternatives]

        answer_cols_x = answer_cols_x[:n_alternatives]
        logger.info("Painel %d: answer_cols_x selecionado=%s", pi, [round(c, 1) for c in answer_cols_x])

        if len(answer_cols_x) >= 2:
            col_spacing = float(np.median(np.diff(np.array(answer_cols_x))))
        else:
            col_spacing = avg_w * 2.5

        # Valida col_spacing: se menor que 1 largura de bolha, detecção de colunas falhou.
        # Acontece em painéis com perspectiva (mais longe da câmera = bolhas menores/comprimidas)
        # onde o histograma retorna poucos picos e a seleção por CV escolhe picos colados.
        # Nesse caso, reconstrói as colunas usando o espaçamento médio dos painéis anteriores
        # ou o span do painel dividido por n_alternatives.
        if col_spacing < avg_w * 1.2 and len(answer_cols_x) >= 1:
            # Tenta usar espaçamento dos painéis já processados
            if panel_col_spacings:
                ref_spacing = float(np.median(list(panel_col_spacings.values())))
            else:
                # Sem referência: estima pelo span do painel
                ref_spacing = max(avg_w * 1.8, panel_span / (n_alternatives + 1))

            # Reconstrói colunas a partir do centro estimado do painel
            panel_cx_mean = float(np.median(panel_cx))
            total_width = ref_spacing * (n_alternatives - 1)
            col_start = panel_cx_mean - total_width / 2.0
            answer_cols_x = [col_start + k * ref_spacing for k in range(n_alternatives)]
            col_spacing = ref_spacing
            logger.warning(
                "Painel %d: col_spacing=%.1f < avg_w*1.2=%.1f → reconstruído com spacing=%.1f centrado em %.1f",
                pi, col_spacing, avg_w * 1.2, ref_spacing, panel_cx_mean,
            )
        else:
            panel_col_spacings[pi] = col_spacing

        # âncora = pico mais próximo à esquerda das colunas de resposta
        # Margem 0.5*avg_w: evita que o índice seja confundido com coluna A quando
        # o pico do índice cai perto demais de answer_cols_x[0].
        leftmost_answer = answer_cols_x[0]
        anchor_candidates_x = [p for p in peaks_list if p < leftmost_answer - avg_w * 0.5]
        if anchor_candidates_x:
            anchor_x = float(max(anchor_candidates_x))
            anchor_tol = max(avg_w * 1.2, col_spacing * 0.75)
        else:
            # Sem pico real para âncora: posiciona à esquerda e usa tolerância estreita
            # para não capturar candidatos reais da coluna A.
            anchor_x = leftmost_answer - col_spacing
            anchor_tol = avg_w * 0.8
        # 0.90: perspectiva trapezoidal desloca col C/D para fora do range 0.75*spacing
        col_tol = max(avg_w * 1.2, col_spacing * 0.90)
        logger.info("Painel %d: anchor_x=%.1f anchor_tol=%.1f col_tol=%.1f leftmost_A=%.1f dist_anchor_A=%.1f",
                    pi, anchor_x, anchor_tol, col_tol, answer_cols_x[0], answer_cols_x[0] - anchor_x)

        # usa candidatos próximos da âncora para estimar linhas
        anchor_candidates = [
            c for c in panel_candidates
            if abs((c[0] + c[2] / 2.0) - anchor_x) <= anchor_tol
        ]

        if len(anchor_candidates) < max(5, n_per_panel // 3):
            logger.warning("Painel %d: poucos candidatos âncora (%d)", pi, len(anchor_candidates))
            # fallback: usa todas as bolhas do painel para estimar Y
            anchor_y = sorted([c[1] + c[3] / 2.0 for c in panel_candidates])
        else:
            anchor_y = sorted([c[1] + c[3] / 2.0 for c in anchor_candidates])

        row_pos = _build_rows_from_anchor_positions(
            anchor_y=anchor_y,
            n_rows=n_per_panel,
            y_min_bound=global_min_y,
            avg_h=avg_h,
        )

        if len(row_pos) < n_per_panel:
            logger.warning("Painel %d: falha ao reconstruir linhas", pi)
            continue

        if len(row_pos) >= 2:
            row_spacing = float(np.median(np.diff(row_pos)))
        else:
            row_spacing = avg_h * 1.8

        # 0.90: perspectiva residual sem warp comprime linhas finais do painel
        # — candidatos reais ficam até 0.85*spacing afastados do row_pos estimado.
        row_tol = max(avg_h * 1.2, row_spacing * 0.90)

        # Phantom shift iterativo: remove linhas fantasma enquanto row_pos[0] estiver
        # mais de 0.5*spacing antes do primeiro candidato DENSO do painel.
        # "Denso": percentil 5 dos Y do painel (ignora 1-2 candidatos espúrios no topo).
        # panel_min_y robusto: primeira linha com fill_ratio médio razoável.
        # Agrupa candidatos por linha e descarta linhas onde fill médio < 0.10
        # (candidatos espúrios: bordas/texto que não são bolhas preenchidas).
        panel_ys = sorted([c[1] + c[3] / 2.0 for c in panel_candidates])
        panel_min_y = float(panel_ys[0])  # fallback: mínimo absoluto
        line_gap = row_spacing * 0.5
        # Constrói grupos de linhas
        lines: list[list[tuple]] = []
        for c in sorted(panel_candidates, key=lambda c: c[1] + c[3] / 2.0):
            cy = c[1] + c[3] / 2.0
            if lines and cy - (lines[-1][-1][1] + lines[-1][-1][3] / 2.0) <= line_gap:
                lines[-1].append(c)
            else:
                lines.append([c])
        # Primeira linha com fill médio ≥ 0.10 (bolhas reais, não bordas)
        for line_cands in lines:
            line_fills = [_compute_fill_ratio(
                gray[max(0, c[1]):c[1]+c[3], max(0, c[0]):c[0]+c[2]], bg_brightness
            ) for c in line_cands]
            if float(np.mean(line_fills)) >= 0.10:
                panel_min_y = float(min(c[1] + c[3] / 2.0 for c in line_cands))
                break

        shift_count = 0
        while (len(row_pos) >= 2
               and row_pos[0] < panel_min_y - row_spacing * 0.5
               and shift_count < n_per_panel):
            row_pos = np.append(row_pos[1:], row_pos[-1] + row_spacing)
            shift_count += 1
        if shift_count > 0:
            logger.warning(
                "Painel %d: grade deslocada %d linhas (panel_min_y_p5=%.1f), row_pos[0]=%.1f",
                pi, shift_count, panel_min_y, row_pos[0],
            )

        logger.info(
            "Painel %d: anchor_x=%.1f cols=%s rows=[%.1f..%.1f] row_spacing=%.1f",
            pi,
            anchor_x,
            " ".join(f"{ALTERNATIVES[i]}={answer_cols_x[i]:.0f}" for i in range(min(len(answer_cols_x), n_alternatives))),
            row_pos[0],
            row_pos[-1],
            row_spacing,
        )
        if pi == 0:
            for _ri, _ry in enumerate(row_pos[:26]):
                logger.warning("Painel 0 row_pos[%d]=%.1f (Q%d)", _ri, _ry, pi * n_per_panel + _ri + 1)

        row_pos_arr = np.array(row_pos, dtype=float)

        # bg_brightness local do painel
        panel_xs = [c[0] for c in panel_candidates]
        if panel_xs:
            px1 = max(0, min(panel_xs) - 5)
            px2 = min(gray.shape[1], max(c[0] + c[2] for c in panel_candidates) + 5)
            panel_strip = gray[:, px1:px2]
            panel_bg = float(np.percentile(panel_strip.astype(np.float32), 90))
            panel_bg = max(panel_bg, bg_brightness * 0.85)
        else:
            panel_bg = bg_brightness

        # Fator de compensação de escala: bolhas perspectiva-comprimidas têm
        # menos pixels escuros por área → fill_ratio subestimado.
        # Compensação: (avg_w_global / avg_w_panel)^0.5 — raiz para ser conservador.
        panel_avg_w = float(np.median([c[2] for c in panel_candidates]))
        panel_avg_h = float(np.median([c[3] for c in panel_candidates]))
        scale_area = (avg_w * avg_h) / max(panel_avg_w * panel_avg_h, 1.0)
        fill_scale = float(np.sqrt(np.clip(scale_area, 0.5, 2.0)))
        if abs(fill_scale - 1.0) > 0.05:
            logger.info(
                "Painel %d: bolhas %.1fx%.1f vs global %.1fx%.1f → fill_scale=%.3f",
                pi, panel_avg_w, panel_avg_h, avg_w, avg_h, fill_scale,
            )
        else:
            fill_scale = 1.0

        logger.info("Painel %d: bg_brightness local=%.1f (global=%.1f)", pi, panel_bg, bg_brightness)

        def _assign_to_grid(
            candidates_list: list[tuple[int, int, int, int]],
            rp_arr: np.ndarray,
            r_spacing: float,
        ) -> dict[tuple[int, int], tuple]:
            g: dict[tuple[int, int], tuple] = {}
            for x, y, w, h in candidates_list:
                cx = x + w / 2.0
                cy = y + h / 2.0

                col_dists = np.abs(np.array(answer_cols_x, dtype=float) - cx)
                local_col = int(np.argmin(col_dists))
                if col_dists[local_col] > col_tol:
                    continue

                # Descarta candidato que está claramente mais próximo da âncora do que
                # da coluna de resposta — é o índice da questão, não uma bolha.
                # Margem avg_w*0.4: evita descartar bolha A quando índice e A são
                # detectados na mesma posição X (folha Anchieta: ~14px de separação).
                dist_to_anchor = abs(cx - anchor_x)
                if dist_to_anchor < col_dists[local_col] - avg_w * 0.4:
                    continue

                row_dists_arr = np.abs(rp_arr - cy)
                nr = int(np.argmin(row_dists_arr))
                if row_dists_arr[nr] > row_tol:
                    continue

                global_row = pi * n_per_panel + nr
                if global_row >= n_questions:
                    continue

                crop = gray[max(0, y): y + h, max(0, x): x + w]
                if crop.size == 0:
                    continue

                fill = min(1.0, _compute_fill_ratio(crop, panel_bg) * fill_scale)
                key = (global_row, local_col)
                if key not in g or col_dists[local_col] < g[key][6]:
                    g[key] = (x, y, w, h, fill, crop.copy(), float(col_dists[local_col]))
            return g

        # Primeira passagem: atribuição inicial com row_pos estimado
        panel_grid = _assign_to_grid(panel_candidates, row_pos_arr, row_spacing)

        # Recalibração de colunas: recalcula answer_cols_x[c] como mediana X real
        # das células atribuídas à coluna c. Corrige deriva de perspectiva trapezoidal
        # onde colunas X deslocam horizontalmente conforme Y aumenta.
        col_xs: dict[int, list[float]] = {}
        for (_, local_col), (x, y, w, h, *_rest) in panel_grid.items():
            col_xs.setdefault(local_col, []).append(x + w / 2.0)

        calibrated_cols = list(answer_cols_x)
        for col_idx, xs in col_xs.items():
            if 0 <= col_idx < len(calibrated_cols) and len(xs) >= 3:
                calibrated_cols[col_idx] = float(np.median(xs))

        # Interpola colunas sem células suficientes
        cal_col_indices = sorted(c for c, xs in col_xs.items() if len(xs) >= 3 and 0 <= c < len(calibrated_cols))
        if len(cal_col_indices) >= 2:
            for c in range(len(calibrated_cols)):
                if c not in cal_col_indices:
                    lo = max((ci for ci in cal_col_indices if ci < c), default=None)
                    hi = min((ci for ci in cal_col_indices if ci > c), default=None)
                    if lo is not None and hi is not None:
                        t = (c - lo) / (hi - lo)
                        calibrated_cols[c] = calibrated_cols[lo] + t * (calibrated_cols[hi] - calibrated_cols[lo])
                    elif lo is not None:
                        calibrated_cols[c] = calibrated_cols[lo] + (c - lo) * col_spacing
                    elif hi is not None:
                        calibrated_cols[c] = calibrated_cols[hi] - (hi - c) * col_spacing

            col_delta = max(abs(calibrated_cols[c] - answer_cols_x[c]) for c in range(len(answer_cols_x)))
            if col_delta > 1.0:
                logger.info("Painel %d: answer_cols_x recalibrado (max_delta=%.1fpx)", pi, col_delta)
                answer_cols_x = calibrated_cols
                # Segunda passagem com colunas recalibradas
                panel_grid = _assign_to_grid(panel_candidates, row_pos_arr, row_spacing)

        # Recalibração: recalcula row_pos[i] como mediana Y real das células
        # atribuídas à linha i. Corrige drift acumulado da regressão linear.
        row_ys: dict[int, list[float]] = {}
        for (global_row, _), (x, y, w, h, *_rest) in panel_grid.items():
            local_row = global_row - pi * n_per_panel
            row_ys.setdefault(local_row, []).append(y + h / 2.0)

        calibrated = row_pos_arr.copy()
        for local_row, ys in row_ys.items():
            if 0 <= local_row < len(calibrated) and len(ys) >= 2:
                new_y = float(np.median(ys))
                # Rejeita recalibração se mediana está longe demais do valor esperado:
                # indica que a linha absorveu candidatos da linha vizinha (drift).
                # Limite: 30% do spacing — acima disso a linha está "roubando" do vizinho.
                if abs(new_y - float(calibrated[local_row])) <= row_spacing * 0.30:
                    calibrated[local_row] = new_y

        # Propaga calibração para linhas sem células via interpolação linear
        # entre vizinhos calibrados, preservando spacing uniforme.
        calibrated_indices = sorted(
            r for r, ys in row_ys.items()
            if len(ys) >= 2
            and 0 <= r < len(calibrated)
            and abs(float(np.median(ys)) - float(row_pos_arr[r])) <= row_spacing * 0.30
        )
        if len(calibrated_indices) >= 2:
            for i in range(len(calibrated)):
                if i not in calibrated_indices:
                    # interpola/extrapola a partir dos dois vizinhos calibrados mais próximos
                    lo = max((r for r in calibrated_indices if r < i), default=None)
                    hi = min((r for r in calibrated_indices if r > i), default=None)
                    if lo is not None and hi is not None:
                        t = (i - lo) / (hi - lo)
                        calibrated[i] = calibrated[lo] + t * (calibrated[hi] - calibrated[lo])
                    elif lo is not None:
                        calibrated[i] = calibrated[lo] + (i - lo) * row_spacing
                    elif hi is not None:
                        calibrated[i] = calibrated[hi] - (hi - i) * row_spacing

            row_spacing_cal = float(np.median(np.diff(calibrated)))
            if row_spacing_cal > avg_h * 0.8:
                row_spacing = row_spacing_cal
                logger.info("Painel %d: row_pos recalibrado (max_delta=%.1fpx)", pi,
                            float(np.max(np.abs(calibrated - row_pos_arr))))
                row_pos_arr = calibrated

            # Segunda passagem com row_pos recalibrado
            panel_grid = _assign_to_grid(panel_candidates, row_pos_arr, row_spacing)

        # Redistribui células de linhas sobrecarregadas usando row_pos_arr deste painel
        panel_grid = _redistribute_orphan_rows(
            panel_grid, n_per_panel, 1, n_alternatives, row_pos_arr, row_spacing,
            global_row_offset=pi * n_per_panel,
        )

        # Gap-fill: linhas sem nenhuma célula → amostra diretamente a posição esperada.
        # Cobre candidatos que não foram detectados (contraste fraco) ou perderam
        # a tolerância de linha por drift de regressão.
        panel_grid = _gap_fill_missing_rows(
            panel_grid=panel_grid,
            gray=gray,
            answer_cols_x=answer_cols_x,
            row_pos_arr=row_pos_arr,
            n_per_panel=n_per_panel,
            n_alternatives=n_alternatives,
            avg_w=avg_w,
            avg_h=avg_h,
            panel_bg=panel_bg,
            fill_scale=fill_scale,
            global_row_offset=pi * n_per_panel,
            panel_candidates=panel_candidates,
        )
        grid.update(panel_grid)

    return [
        BubbleCell(row=r, col=c, x=x, y=y, w=w, h=h, fill_ratio=fill, crop=crop)
        for (r, c), (x, y, w, h, fill, crop, _) in grid.items()
    ]


def _gap_fill_missing_rows(
    panel_grid: dict[tuple[int, int], tuple],
    gray: np.ndarray,
    answer_cols_x: list[float],
    row_pos_arr: np.ndarray,
    n_per_panel: int,
    n_alternatives: int,
    avg_w: float,
    avg_h: float,
    panel_bg: float,
    fill_scale: float,
    global_row_offset: int,
    panel_candidates: Optional[list[tuple[int, int, int, int]]] = None,
) -> dict[tuple[int, int], tuple]:
    """
    Duas correções em sequência:

    1. REDISTRIBUIÇÃO POR Y REAL (antes do gap-fill):
       Células atribuídas à linha errada por drift de row_pos nas últimas filas.
       Para cada célula onde dist(cy, row_pos[assigned]) > dist(cy, row_pos[neighbor]),
       move a célula para a linha correta — mesmo que nenhuma linha esteja sobrecarregada.

    2. GAP-FILL (linhas ainda sem células):
       Amostra diretamente a posição esperada (row_pos_arr[i], answer_cols_x[c]).
       Cobre candidatos não detectados (contraste fraco) ou completamente ausentes.
    """
    half_w = max(3, int(avg_w / 2))
    half_h = max(3, int(avg_h / 2))
    img_h, img_w = gray.shape[:2]

    if len(row_pos_arr) < 2:
        return panel_grid

    # ── Passo 1: redistribuição por Y real ───────────────────────────────────
    # Para cada célula no grid, verifica se a linha vizinha (±1) está mais
    # próxima do Y real da célula do que a linha atribuída. Se sim, move.
    # Itera até convergência (máx 3 passes) para cobrir drifts acumulados.
    for _pass in range(3):
        moved = False
        for key in list(panel_grid.keys()):
            global_row, col_idx = key
            local_row = global_row - global_row_offset
            if local_row < 0 or local_row >= len(row_pos_arr):
                continue

            cell_data = panel_grid[key]
            x, y, w, h = cell_data[0], cell_data[1], cell_data[2], cell_data[3]
            cy = y + h / 2.0

            assigned_dist = abs(cy - float(row_pos_arr[local_row]))

            for delta in (-1, +1):
                neighbor_local = local_row + delta
                if neighbor_local < 0 or neighbor_local >= len(row_pos_arr):
                    continue
                neighbor_global = global_row_offset + neighbor_local
                neighbor_dist = abs(cy - float(row_pos_arr[neighbor_local]))

                # Move apenas se diferença for significativa (>30% do spacing).
                # 10% era muito sensível: célula equidistante por 1px causava
                # redistribuição incorreta (Q66→Q67 com spacing=35px, diff=1px).
                spacing = abs(float(row_pos_arr[1]) - float(row_pos_arr[0])) if len(row_pos_arr) >= 2 else avg_h * 1.8
                if neighbor_dist < assigned_dist - spacing * 0.30:
                    # Só move se não há célula melhor já na linha destino
                    existing = panel_grid.get((neighbor_global, col_idx))
                    if existing is not None:
                        ex_cy = existing[1] + existing[3] / 2.0
                        if abs(ex_cy - float(row_pos_arr[neighbor_local])) <= neighbor_dist:
                            continue  # destino já tem célula mais próxima

                    del panel_grid[key]
                    panel_grid[(neighbor_global, col_idx)] = cell_data
                    logger.info(
                        "Y-redistrib: Q%d col%d → Q%d (cy=%.1f dist_old=%.1f dist_new=%.1f)",
                        global_row + 1, col_idx, neighbor_global + 1, cy, assigned_dist, neighbor_dist,
                    )
                    moved = True
                    break  # célula já movida, sai do loop de deltas

        if not moved:
            break

    # ── Passo 2: gap-fill para colunas faltantes em cada linha ──────────────
    # Preenche células individualmente ausentes — não apenas linhas totalmente vazias.
    # Linha com 1 célula detectada mas 4 faltando (ex: drift de perspectiva) ainda
    # precisa ter as colunas ausentes amostradas diretamente na posição esperada.
    #
    # RESTRIÇÃO: só amostra se NÃO existe candidato NMS próximo dessa posição que
    # ainda não foi atribuído. Candidato próximo mas não atribuído indica erro de
    # tolerância — não deve gerar célula fantasma numa posição diferente.
    row_spacing = float(row_pos_arr[1] - row_pos_arr[0]) if len(row_pos_arr) >= 2 else avg_h * 1.8
    # Proximidade: candidato dentro de meio-spacing em Y e meia-largura em X
    # é considerado "existente" — gap-fill não deve criar célula nova nessa posição.
    gap_guard_y = row_spacing * 0.45
    gap_guard_x = avg_w * 1.5

    for local_row in range(n_per_panel):
        global_row = global_row_offset + local_row
        if local_row >= len(row_pos_arr):
            continue

        cy = float(row_pos_arr[local_row])
        added = 0

        for col_idx, cx in enumerate(answer_cols_x[:n_alternatives]):
            if (global_row, col_idx) in panel_grid:
                continue  # célula já atribuída, pula

            # Bloqueia gap-fill se existe candidato NMS que está mais próximo desta
            # linha do que de qualquer outra linha. Evita células fantasmas sem
            # bloquear gap-fill legítimo quando o candidato pertence a linha vizinha.
            if panel_candidates:
                near_and_closest = False
                for pc in panel_candidates:
                    pc_cx = pc[0] + pc[2] / 2.0
                    pc_cy = pc[1] + pc[3] / 2.0
                    if abs(pc_cx - cx) > gap_guard_x:
                        continue
                    dist_current = abs(pc_cy - cy)
                    if dist_current > gap_guard_y:
                        continue
                    # Verifica se esta linha é a mais próxima para este candidato
                    closer_row = any(
                        abs(pc_cy - float(row_pos_arr[r])) < dist_current
                        for r in range(len(row_pos_arr))
                        if r != local_row
                    )
                    if not closer_row:
                        near_and_closest = True
                        break
                if near_and_closest:
                    continue

            x1 = max(0, int(cx - half_w))
            x2 = min(img_w, int(cx + half_w))
            y1 = max(0, int(cy - half_h))
            y2 = min(img_h, int(cy + half_h))

            if x2 <= x1 or y2 <= y1:
                continue

            crop = gray[y1:y2, x1:x2]
            if crop.size == 0:
                continue

            fill = min(1.0, _compute_fill_ratio(crop, panel_bg) * fill_scale)
            panel_grid[(global_row, col_idx)] = (x1, y1, x2 - x1, y2 - y1, fill, crop.copy(), 0.0)
            added += 1

        if added > 0:
            total = sum(1 for c in range(n_alternatives) if (global_row, c) in panel_grid)
            logger.info(
                "Gap-fill: Q%d (local=%d) → %d células amostradas em row_pos=%.1f",
                global_row + 1, local_row, total, cy,
            )

    return panel_grid


def _redistribute_orphan_rows(
    grid: dict[tuple[int, int], tuple],
    n_per_panel: int,
    n_panels: int,
    n_alternatives: int,
    row_pos_arr: np.ndarray,
    row_spacing: float,
    global_row_offset: int = 0,
) -> dict[tuple[int, int], tuple]:
    """
    Detecta linhas vazias adjacentes a linhas sobrecarregadas e redistribui
    as células pelo Y real de cada bolinha.

    Caso típico: Q13 tem espaçamento Y maior (número "13s" ocupa mais altura)
    → B,C,D,E da Q13 caem em Q14. Q13 fica com ≤1 célula, Q14 com 8-10.
    Fix: para cada linha vazia com vizinho sobrecarregado, move as células
    cujo Y real está mais próximo da linha vazia do que da linha sobrecarregada.

    global_row_offset: quando chamado por painel, row_pos_arr contém posições
    locais (índice 0 = primeira questão do painel). global_row_offset converte
    de índice global para local ao indexar row_pos_arr.
    """
    n_questions = n_per_panel * n_panels
    tol = row_spacing * 0.75

    for _ in range(5):  # no máximo 5 passes
        row_counts: dict[int, int] = {}
        for (r, _c) in grid:
            row_counts[r] = row_counts.get(r, 0) + 1

        moved_any = False
        for row in range(global_row_offset, global_row_offset + n_questions):
            if row_counts.get(row, 0) > 0:
                continue  # linha tem células, ok

            for neighbor in [row - 1, row + 1]:
                if neighbor < global_row_offset or neighbor >= global_row_offset + n_questions:
                    continue
                if row_counts.get(neighbor, 0) <= n_alternatives:
                    continue  # vizinho não está sobrecarregado

                local_row = row - global_row_offset
                local_neighbor = neighbor - global_row_offset
                if local_row >= len(row_pos_arr) or local_neighbor >= len(row_pos_arr):
                    continue

                row_y = float(row_pos_arr[local_row])
                neighbor_y = float(row_pos_arr[local_neighbor])

                for col in range(n_alternatives):
                    if (neighbor, col) not in grid:
                        continue
                    cell_data = grid[(neighbor, col)]
                    x, y, w, h = cell_data[0], cell_data[1], cell_data[2], cell_data[3]
                    cy = y + h / 2.0

                    dist_row = abs(cy - row_y)
                    dist_neighbor = abs(cy - neighbor_y)

                    if dist_row < dist_neighbor and dist_row <= tol:
                        del grid[(neighbor, col)]
                        grid[(row, col)] = cell_data
                        row_counts[neighbor] = row_counts.get(neighbor, 1) - 1
                        row_counts[row] = row_counts.get(row, 0) + 1
                        moved_any = True
                        logger.info(
                            "Redistribuição: col=%d Q%d→Q%d (cy=%.1f dist_row=%.1f dist_nb=%.1f)",
                            col, neighbor + 1, row + 1, cy, dist_row, dist_neighbor,
                        )

        if not moved_any:
            break

    return grid


def _robust_spacing(gaps: list[float], avg_h: float) -> float:
    """
    Spacing robusto mesmo quando linhas intermediárias não foram detectadas.

    Usa median(valid) como base em vez de min(valid).
    min_g falha quando existe um gap fantasma ligeiramente menor que o real
    (ex: phantom a 30px numa grade de 40px): ratio=40/30=1.33, round=1,
    abs(0.33)>0.25 → todos os gaps reais são excluídos e spacing=30 (errado).
    Com median como base, gaps reais ficam ratio≈1 e são incluídos corretamente.
    """
    valid = [g for g in gaps if g > avg_h * 0.5]
    if not valid:
        return max(avg_h * 1.6, 1.0)

    base = float(np.median(valid))
    normalized: list[float] = []
    for g in valid:
        ratio = g / base
        n = max(1, round(ratio))
        if abs(ratio - n) < 0.35:
            normalized.append(g / n)

    return float(np.median(normalized)) if normalized else base


def _build_rows_from_anchor_positions(
    anchor_y: list[float],
    n_rows: int,
    y_min_bound: float,
    avg_h: float,
) -> np.ndarray:
    """
    Reconstrói grade de n_rows linhas a partir dos picos da coluna âncora.

    Bug1 (linha pulada): best_top sem tiebreaker ficava em first_peak mesmo quando
    o topo real era first_peak - spacing → todas as linhas deslocadas +1.
    Fix: tiebreaker por proximidade a y_min_bound quando scores empatam.

    Bug2 (última linha sumindo): spacing acumulado divergia das posições reais.
    Fix: regressão linear (≥4 pontos) calibra slope e intercept reais.
    """
    if not anchor_y:
        return np.array([], dtype=float)

    anchor_y = sorted(anchor_y)

    # Deduplication: two detections on the same visual line produce a near-zero
    # gap that collapses the computed spacing and places multiple grid rows on
    # the same physical line.  Remove entries within avg_h * 0.6 of the previous.
    deduped: list[float] = [anchor_y[0]]
    for y in anchor_y[1:]:
        if y - deduped[-1] >= avg_h * 0.6:
            deduped.append(y)
    anchor_y = deduped

    # ── Spacing robusto (normaliza gaps duplos/triplos) ───────────────────────
    if len(anchor_y) >= 2:
        gaps = [anchor_y[i + 1] - anchor_y[i] for i in range(len(anchor_y) - 1)]
        spacing = _robust_spacing(gaps, avg_h)
    else:
        spacing = max(avg_h * 1.6, 1.0)

    spacing = max(spacing, avg_h * 0.8)

    # ── Regressão linear: calibra spacing e posição de referência ────────────
    ref_y = anchor_y[0]

    if len(anchor_y) >= 4:
        # Usa y_min_bound como origem em vez de anchor_y[0].
        # Quando anchor_y[0] é um phantom próximo de y_min_bound (ex: +20px),
        # usar anchor_y[0] como y0 causa colisões de índice por arredondamento
        # bancário: phantom e Q1 real ambos mapeiam para índice 0, Q1 real é
        # descartado do seen, e a regressão recebe pontos com espaçamento dobrado
        # → slope errado → drift acumulado → questão pulada no meio do painel.
        y0 = y_min_bound
        raw_indices = [round((y - y0) / spacing) for y in anchor_y]

        seen: dict[int, float] = {}
        for idx, y in zip(raw_indices, anchor_y):
            if idx not in seen:
                seen[idx] = y

        if len(seen) >= 3:
            idx_arr = np.array(list(seen.keys()), dtype=float)
            y_arr = np.array(list(seen.values()), dtype=float)
            slope, intercept = np.polyfit(idx_arr, y_arr, 1)
            if slope > avg_h * 0.8:
                spacing = float(slope)
                ref_y = float(intercept)

    # ── best_top via ref_y da regressão ──────────────────────────────────────
    # Usar first_peak como âncora falha quando os primeiros picos não foram
    # detectados: best_top sobe demais e a grade não cobre as últimas linhas.
    # ref_y (intercept da regressão) considera TODOS os picos detectados →
    # posição mais precisa, cobre melhor o intervalo completo do painel.
    tol = spacing * 0.40

    # Avança ref_y em steps de spacing até a primeira linha dentro do painel
    raw_offset = (y_min_bound - ref_y) / spacing
    start_k = max(0, int(np.floor(raw_offset)))
    best_top = ref_y + start_k * spacing

    # Sanidade: best_top não pode estar muito antes de y_min_bound
    while best_top < y_min_bound - spacing * 0.55:
        best_top += spacing

    # Ajuste fino: maximiza picos cobertos.
    # ±1 não é suficiente quando Q1..Qk estão em branco (sem pico na âncora):
    # âncora começa em Q(k+1), best_top inicial aponta para Q(k+1), e é necessário
    # recuar k passos para alinhar row=0 com Q1.
    def _score(top: float) -> tuple[int, float]:
        matched = sum(
            1 for p in anchor_y
            if abs(p - (top + round((p - top) / spacing) * spacing)) <= tol
        )
        return (matched, -abs(top - y_min_bound))

    max_search = min(n_rows // 4 + 2, 10)
    best_top_score = _score(best_top)
    for k in range(-max_search, max_search + 1):
        if k == 0:
            continue
        candidate = best_top + k * spacing
        if candidate < y_min_bound - spacing * 0.55:
            continue
        s = _score(candidate)
        if s > best_top_score:
            best_top_score = s
            best_top = candidate

    # Post-adjustment: the y_min_bound tiebreaker can pick a top that is exactly
    # one spacing *before* the first actual anchor when all rows are detected
    # (e.g., best_top=y_Q25 beats y_Q26 because y_Q25 is closer to crop_y1).
    # Fix: if best_top sits > 0.55 spacing before the first detected anchor AND
    # shifting one step forward lands on that anchor, prefer the shifted position.
    if anchor_y:
        first_anchor = float(min(anchor_y))
        shifted = best_top + spacing
        if (first_anchor - best_top > spacing * 0.55
                and abs(shifted - first_anchor) <= tol):
            s_shifted = _score(shifted)
            if s_shifted[0] >= best_top_score[0]:
                best_top = shifted
                best_top_score = s_shifted
                logger.info(
                    "best_top ajustado +1 linha (%.1f → %.1f): primeiro âncora em %.1f",
                    best_top - spacing, best_top, first_anchor,
                )

    return np.array([best_top + k * spacing for k in range(n_rows)], dtype=float)

def _assign_histogram(
    candidates: list[tuple[int, int, int, int]],
    gray: np.ndarray,
    n_questions: int,
    n_alternatives: int,
    bg_brightness: float = 255.0,
    grid_top_y: int = 0,
) -> list[BubbleCell]:
    """
    Atribuição por histograma com garantia de preenchimento de TODAS as linhas.
    Detecta picos, mas se faltar, extrapola para garantir n_questions linhas.
    """
    if not candidates:
        return []

    avg_w = float(np.median([c[2] for c in candidates]))
    avg_h = float(np.median([c[3] for c in candidates]))
    cx_all = np.array([c[0] + c[2] / 2.0 for c in candidates], dtype=float)
    cy_all = np.array([c[1] + c[3] / 2.0 for c in candidates], dtype=float)

    # Detecta picos de colunas
    col_pos = _histogram_peaks(cx_all, n_alternatives, bandwidth=avg_w * 2.0)

    # Detecta picos de linhas com bandwidth adaptativo
    estimated_row_spacing = (cy_all.max() - cy_all.min()) / max(n_questions - 1, 1)
    row_bandwidth = avg_h * (3.5 if estimated_row_spacing > avg_h * 3 else 1.5)

    # Busca MAIS picos do que n_questions para depois filtrar os melhores
    row_pos_raw = _histogram_peaks(cy_all, min(n_questions + 10, len(cy_all)), bandwidth=row_bandwidth)

    if col_pos is None:
        logger.warning("Histograma: não encontrou picos de coluna")
        return []

    if row_pos_raw is None or len(row_pos_raw) < 2:
        logger.warning("Histograma: %d picos de linha detectados → grade uniforme",
                       len(row_pos_raw) if row_pos_raw is not None else 0)
        row_pos = np.linspace(float(cy_all.min()), float(cy_all.max()), n_questions)
    else:
        rp = sorted(row_pos_raw.tolist())
        gaps_rp = [rp[i + 1] - rp[i] for i in range(len(rp) - 1)]
        spacing = _robust_spacing(gaps_rp, avg_h)

        # Deduplicate peaks on the same visual line before rebuilding the grid.
        deduped_rp: list[float] = [rp[0]]
        for p in rp[1:]:
            if p - deduped_rp[-1] >= avg_h * 0.6:
                deduped_rp.append(p)
        rp = deduped_rp

        # Reconstrói grade completa ancorada no topo físico da seção de respostas.
        row_pos = np.array(
            _prune_to_grid(sorted(rp), n_questions, spacing, float(grid_top_y)),
            dtype=float,
        )

    logger.info("_assign_histogram: %d linhas finais (esperado %d)", len(row_pos), n_questions)

    # ── TOLERÂNCIAS DINÂMICAS ────────────────────────────────────────────────
    if len(col_pos) >= 2:
        col_gaps = np.diff(np.sort(col_pos))
        col_spacing = float(np.median(col_gaps)) if len(col_gaps) > 0 else avg_w * 2.5
    else:
        col_spacing = avg_w * 2.5

    if len(row_pos) >= 2:
        row_gaps = np.diff(row_pos)
        row_spacing = float(np.median(row_gaps)) if len(row_gaps) > 0 else estimated_row_spacing
    else:
        row_spacing = estimated_row_spacing

    # Tolerâncias: 45% do espaçamento real
    col_tol = max(avg_w * 1.2, col_spacing * 0.6)
    row_tol = max(avg_h * 1.2, row_spacing * 0.6)

    logger.info("Tolerâncias: col_tol=%.1f (gap=%.1f) | row_tol=%.1f (gap=%.1f)",
                col_tol, col_spacing, row_tol, row_spacing)

    # ── Atribuição de candidatos à grade ─────────────────────────────────────
    grid: dict[tuple[int, int], tuple] = {}
    for x, y, w, h in candidates:
        cx_c, cy_c = x + w / 2.0, y + h / 2.0

        # Encontra coluna mais próxima
        col_dists = np.abs(col_pos - cx_c)
        nc = int(np.argmin(col_dists))

        # Encontra linha mais próxima
        row_dists = np.abs(row_pos - cy_c)
        nr = int(np.argmin(row_dists))

        crop = gray[max(0, y): y + h, max(0, x): x + w]
        if crop.size == 0:
            continue
        fill = _compute_fill_ratio(crop, bg_brightness)

        key = (nr, nc)
        # Mantém o candidato com maior fill ratio para cada célula
        if key not in grid or fill > grid[key][4]:
            grid[key] = (x, y, w, h, fill, crop.copy())

    logger.info("_assign_histogram: %d candidatos → %d células", len(candidates), len(grid))
    return [BubbleCell(row=r, col=c, x=x, y=y, w=w, h=h, fill_ratio=fill, crop=crop)
            for (r, c), (x, y, w, h, fill, crop) in grid.items()]


# ─── Grade fixa (fallback) ────────────────────────────────────────────────────

def _detect_separators(strip: np.ndarray, n_gaps: int, min_gap_px: int = 3) -> list[int]:
    """
    Detecta posições de separadores verticais via projeção de colunas.
    Retorna lista de n_gaps posições X (em coordenadas de strip) dos centros dos separadores.
    strip: imagem em escala de cinza (apenas a região de interesse).
    """
    # Projeção: soma de pixels escuros por coluna (quanto mais escuro = mais separador/linha)
    dark = (255 - strip.astype(np.float32))
    col_proj = dark.mean(axis=0)

    # Suaviza levemente para remover ruído de bolhas individuais
    kernel = np.ones(3, dtype=float) / 3.0
    col_proj = np.convolve(col_proj, kernel, mode="same")

    _, w = strip.shape
    nominal_gap = w // (n_gaps + 1)

    separators: list[int] = []
    for i in range(n_gaps):
        # Janela de busca centrada no ponto nominal de cada separador
        center = (i + 1) * nominal_gap
        lo = max(0, center - nominal_gap // 3)
        hi = min(w, center + nominal_gap // 3)
        if hi <= lo:
            separators.append(center)
            continue
        local = col_proj[lo:hi]
        peak = int(np.argmax(local)) + lo
        separators.append(peak)

    logger.debug("Separadores detectados: %s (nominal cada %dpx)", separators, nominal_gap)
    return separators


def _assign_fixed(
    gray: np.ndarray,
    n_questions: int,
    n_alternatives: int,
    n_panels: int,
    top_r: float, bottom_r: float, left_r: float, right_r: float,
    bg_brightness: float = 255.0,
) -> list[BubbleCell]:
    h, w = gray.shape
    top, bottom = int(h * top_r), int(h * bottom_r)
    left, right = int(w * left_r), int(w * right_r)
    n_per_panel = n_questions // n_panels

    # ── Detecta fronteiras reais dos painéis via separadores verticais ─────────
    grid_strip = gray[top:bottom, left:right]
    grid_w = right - left

    if n_panels > 1:
        sep_positions = _detect_separators(grid_strip, n_panels - 1)
        # Fronteiras: left, sep0, sep1, ..., right
        boundaries = [0] + sep_positions + [grid_w]
        panel_ranges = [(boundaries[i], boundaries[i + 1]) for i in range(n_panels)]
    else:
        panel_ranges = [(0, grid_w)]

    logger.info("Grade fixa: painéis detectados em %s", [(left + a, left + b) for a, b in panel_ranges])

    cells: list[BubbleCell] = []
    for panel_idx, (pl_local, pr_local) in enumerate(panel_ranges):
        pl = left + pl_local
        pr = left + pr_local
        pi = gray[top:bottom, pl:pr]
        ph, pw = pi.shape
        if pw < n_alternatives + 1 or ph < n_per_panel:
            continue

        cell_h = ph // n_per_panel
        # Coluna do número da questão ocupa ~1/(n_alt+1) da largura; bolhas preenchem o resto.
        # Detecta o separador interno (QUESTÃO|RESPOSTA) via projeção local.
        internal_seps = _detect_separators(pi, 1, min_gap_px=1)
        q_col_end = internal_seps[0] if internal_seps else pw // (n_alternatives + 1)
        bubble_w = pw - q_col_end
        cell_w = bubble_w // n_alternatives if n_alternatives > 0 else pw // (n_alternatives + 1)

        if cell_h < 3 or cell_w < 3:
            continue

        logger.debug(
            "Painel %d: x=[%d:%d] pw=%d q_col_end=%d bubble_w=%d cell_w=%d cell_h=%d",
            panel_idx, pl, pr, pw, q_col_end, bubble_w, cell_w, cell_h,
        )

        for row in range(n_per_panel):
            for col in range(n_alternatives):
                y1 = row * cell_h
                x1 = q_col_end + col * cell_w
                cell = pi[y1: y1 + cell_h, x1: x1 + cell_w]
                if cell.size == 0:
                    continue
                my1, my2 = int(cell_h * 0.2), int(cell_h * 0.8)
                mx1, mx2 = int(cell_w * 0.2), int(cell_w * 0.8)
                inner = cell[my1:my2, mx1:mx2]
                src = inner if inner.size > 0 else cell
                fill = _compute_fill_ratio(src, bg_brightness)
                global_row = panel_idx * n_per_panel + row
                cells.append(BubbleCell(
                    row=global_row, col=col,
                    x=pl + x1, y=top + y1, w=cell_w, h=cell_h,
                    fill_ratio=fill, crop=cell.copy(),
                ))
    return cells


# ─── Seleção de grade por comb-filter ────────────────────────────────────────

def _prune_to_grid(rp: list[float], n: int, spacing: float, y_min_bound: float = 0.0) -> list[float]:
    """
    Reconstrói grade completa de n posições ancorada no topo físico da seção (y_min_bound).

    Problema anterior: retornava rp[best_start:best_start+n] — janela de picos detectados.
    Se Q1-Q6 tinham bolhas fracas (sem pico), primeiro pico = Q7 virava row=0, deslocando tudo.

    Solução: testa todos os offsets plausíveis para o primeiro pico detectado.
    Quando scores empatam (linhas faltando no topo), prefere o top mais próximo de y_min_bound.
    Retorna sempre exatamente n posições — extrapola acima E abaixo quando necessário.
    """
    if not rp or n <= 0:
        return [y_min_bound + k * spacing for k in range(n)]

    first_peak = min(rp)
    tol = spacing * 0.40

    # Máximo de linhas que podem estar faltando acima do primeiro pico detectado
    max_offset = max(0, int((first_peak - y_min_bound) / spacing) + 2)
    max_offset = min(max_offset, n - 1)

    best_top = first_peak
    best_score = -1
    best_top_dist = float('inf')

    for offset in range(max_offset + 1):
        top = first_peak - offset * spacing
        # Não permite grade começar acima do topo da seção de respostas
        if top < y_min_bound - spacing * 0.5:
            continue
        grid = [top + k * spacing for k in range(n)]
        score = sum(
            1 for p in rp
            if any(abs(p - g) <= tol for g in grid)
        )
        top_dist = abs(top - y_min_bound)
        # Desempate: prefere top mais próximo de y_min_bound (âncora no topo físico)
        if score > best_score or (score == best_score and top_dist < best_top_dist):
            best_score = score
            best_top = top
            best_top_dist = top_dist

    return [best_top + k * spacing for k in range(n)]


# ─── Histograma de picos ──────────────────────────────────────────────────────

def _histogram_peaks(coords: np.ndarray, n_peaks: int, bandwidth: float) -> Optional[np.ndarray]:
    if len(coords) < n_peaks:
        return None
    min_v, max_v = float(np.min(coords)), float(np.max(coords))
    span = max_v - min_v
    if span < bandwidth:
        return None
    n_bins = max(300, int(span / max(bandwidth * 0.15, 1.0)))
    hist, bin_edges = np.histogram(coords, bins=n_bins, range=(min_v, max_v))
    bin_centers = (bin_edges[:-1] + bin_edges[1:]) / np.float64(2.0)
    sigma_bins = max(1, int(bandwidth / (span / n_bins)))
    ks = sigma_bins * 4 + 1
    kernel = np.exp(-0.5 * (np.linspace(-2.0, 2.0, ks) ** 2))
    kernel /= kernel.sum()
    smoothed = np.convolve(hist.astype(float), kernel, mode="same")
    peaks: list[tuple[float, float]] = []
    n = len(smoothed)
    for i in range(n):
        # Trata bordas como vizinhos com valor 0 para detectar picos na primeira/última linha
        left = smoothed[i - 1] if i > 0 else 0.0
        right = smoothed[i + 1] if i < n - 1 else 0.0
        if smoothed[i] > left and smoothed[i] > right and smoothed[i] > 0:
            peaks.append((float(smoothed[i]), float(bin_centers[i])))
    if not peaks:
        return None
    peaks.sort(key=lambda p: -p[0])
    return np.array(sorted(p[1] for p in peaks[:n_peaks]), dtype=float)


# ─── Fill ratio ───────────────────────────────────────────────────────────────

def _compute_fill_ratio(cell: np.ndarray, bg_brightness: float = 255.0) -> float:
    """
    Mede escuridão do núcleo interno (25%–75%) normalizada pelo fundo da folha.
    fill = (bg - mean_inner) / bg
    • bg_brightness = percentil 90 da região de respostas (papel branco ≈ 220–250).
    • Bolha vazia com letra impressa: mean_inner ≈ bg → fill ≈ 0.05–0.15.
    • Bolha preenchida a lápis:       mean_inner muito menor → fill ≈ 0.30–0.60.
    Normalizar pelo fundo torna o resultado independente do brilho do scan.
    """
    if cell.size == 0:
        return 0.0
    h, w = cell.shape[:2]
    y1, y2 = max(0, int(h * 0.25)), min(h, int(h * 0.75))
    x1, x2 = max(0, int(w * 0.25)), min(w, int(w * 0.75))
    inner = cell[y1:y2, x1:x2]
    if inner.size < 4:
        inner = cell
    mean_val = float(np.mean(inner.astype(np.float32)))
    ref = max(bg_brightness, 1.0)
    return max(0.0, (ref - mean_val) / ref)


# ─── Auto-calibração de thresholds ───────────────────────────────────────────

def _autocalibrate_thresholds(
    cells: list[BubbleCell],
    default_empty: float,
    default_filled: float,
) -> tuple[float, float]:
    """
    Ajusta thresholds empty/filled para a imagem atual usando KMeans bimodal.

    Fotos de celular em distâncias/iluminações variadas geram distribuições
    de fill_ratio deslocadas. Thresholds fixos falham nesses casos.

    Estratégia:
    - Coleta todos os fill_ratios das células detectadas
    - Se distribuição bimodal clara (2 clusters separados), estima thresholds
      como ponto médio entre os dois centróides
    - Aplica apenas se o resultado for mais conservador que os defaults
      (não amplia zona ambígua além do necessário)
    - Rejeita calibração se n_cells < 20 (amostra insuficiente)
    """
    if len(cells) < 20:
        return default_empty, default_filled

    fills = np.array([c.fill_ratio for c in cells], dtype=np.float32).reshape(-1, 1)

    # Filtra outliers extremos antes de clustering
    p2, p98 = float(np.percentile(fills, 2)), float(np.percentile(fills, 98))
    fills_clean = fills[(fills[:, 0] >= p2) & (fills[:, 0] <= p98)]

    if len(fills_clean) < 10:
        return default_empty, default_filled

    try:
        from sklearn.cluster import KMeans
        km = KMeans(n_clusters=2, n_init=5, random_state=42)
        km.fit(fills_clean)
        c0, c1 = float(km.cluster_centers_[0][0]), float(km.cluster_centers_[1][0])
        low_center = min(c0, c1)
        high_center = max(c0, c1)
    except Exception:
        return default_empty, default_filled

    # Bimodalidade insuficiente: centróides muito próximos → não calibrar
    separation = high_center - low_center
    if separation < 0.10:
        logger.info("Auto-calibração: centróides próximos (%.2f/%.2f) → mantém defaults", low_center, high_center)
        return default_empty, default_filled

    midpoint = (low_center + high_center) / 2.0

    # cal_empty: 40% do midpoint — zona claramente abaixo da fronteira
    cal_empty = midpoint * 0.40
    cal_empty = float(np.clip(cal_empty, 0.05, 0.25))

    # cal_filled: p10 do cluster alto = 90% das bolhas marcadas passam mesmo no painel
    # com fill_scale < 1.0 (perspectiva, caneta fraca). Nunca sobe acima de default_filled
    # para não tornar o threshold mais restritivo que o configurado.
    labels = km.labels_
    high_label = 0 if float(km.cluster_centers_[0][0]) > float(km.cluster_centers_[1][0]) else 1
    high_fills = fills_clean[labels == high_label, 0]
    p10_high = float(np.percentile(high_fills, 10)) if len(high_fills) >= 3 else high_center * 0.85
    cal_filled = min(p10_high * 0.90, default_filled)
    cal_filled = float(np.clip(cal_filled, cal_empty + 0.08, default_filled))

    logger.info(
        "Auto-calibração: clusters=[%.2f, %.2f] sep=%.2f p10_high=%.2f → empty=%.2f filled=%.2f (defaults: %.2f/%.2f)",
        low_center, high_center, separation, p10_high, cal_empty, cal_filled, default_empty, default_filled,
    )

    return cal_empty, cal_filled


# ─── Classificação ────────────────────────────────────────────────────────────

def _classify_question(
    questao: int,
    row_cells: list[BubbleCell],
    threshold_empty: float,
    threshold_filled: float,
) -> QuestionResult:

    if not row_cells:
        return QuestionResult(questao=questao, resposta=None, status="em_branco", confianca=0.0)

    sorted_cells = sorted(row_cells, key=lambda c: c.fill_ratio, reverse=True)

    best = sorted_cells[0]
    second = sorted_cells[1] if len(sorted_cells) > 1 else None

    # 1. Se nem a melhor passou do mínimo → branco
    if best.fill_ratio < threshold_empty:
        return QuestionResult(
            questao=questao,
            resposta=None,
            status="em_branco",
            confianca=1.0
        )

    # 2. Se está entre vazio e preenchido → verificar ruído uniforme ou ambígua
    if best.fill_ratio < threshold_filled:
        # Ruído uniforme: letras impressas dentro de bolhas vazias geram fills similares
        # em todas as alternativas (std baixo). Quando isso ocorre, trata como em_branco.
        if len(row_cells) >= 3:
            all_fills = np.array([c.fill_ratio for c in row_cells], dtype=np.float32)
            if float(np.std(all_fills)) < 0.08:
                return QuestionResult(
                    questao=questao,
                    resposta=None,
                    status="em_branco",
                    confianca=0.8,
                )
        return QuestionResult(
            questao=questao,
            resposta=None,
            status="ambigua",
            confianca=0.5,
            ambiguous_crop=best.crop
        )

    # 3. Comparação com a segunda melhor
    if second is not None:
        diff = best.fill_ratio - second.fill_ratio

        # Ruído uniforme acima do threshold: sombra/papel amassado eleva todos os fills
        # para zona preenchida de forma homogênea. Detecta quando nenhuma alternativa
        # domina claramente (std baixo E diff entre melhor e segunda < 0.15).
        if len(row_cells) >= 3:
            all_fills = np.array([c.fill_ratio for c in row_cells], dtype=np.float32)
            if float(np.std(all_fills)) < 0.10 and diff < 0.15:
                return QuestionResult(
                    questao=questao,
                    resposta=None,
                    status="em_branco",
                    confianca=0.7,
                )

        # Dupla marcação REAL
        if second.fill_ratio >= threshold_filled and diff <= 0.10:
            return QuestionResult(
                questao=questao,
                resposta=None,
                status="dupla_marcacao",
                confianca=0.6,
                filled_cols=[best.col, second.col]
            )

        # Muito próximo → ambígua
        if diff < 0.12:
            return QuestionResult(
                questao=questao,
                resposta=None,
                status="ambigua",
                confianca=0.5,
                ambiguous_crop=best.crop
            )

    # 4. Caso normal
    letra = ALTERNATIVES[best.col] if best.col < len(ALTERNATIVES) else str(best.col)

    return QuestionResult(
        questao=questao,
        resposta=letra,
        status="ok",
        confianca=min(1.0, 0.6 + (best.fill_ratio - threshold_filled)),
        filled_cols=[best.col]
    )

def _confidence(fill_ratio: float, threshold: float) -> float:
    return min(1.0, 0.60 + ((fill_ratio - threshold) / max(0.40, 1e-6)) * 0.40)


# ─── Debug ────────────────────────────────────────────────────────────────────

def _save_debug(
    original: np.ndarray,
    candidates: list[tuple],
    cells: list[BubbleCell],
    crop_y1: int, crop_y2: int, crop_x1: int, crop_x2: int,
    debug_dir: str,
) -> None:
    Path(debug_dir).mkdir(parents=True, exist_ok=True)
    dbg = (original.copy() if len(original.shape) == 3
           else cv2.cvtColor(original, cv2.COLOR_GRAY2BGR))

    # Salva variantes de brilho para ajuste visual
    _gray_dbg = cv2.cvtColor(dbg, cv2.COLOR_BGR2GRAY) if len(dbg.shape) == 3 else dbg.copy()
    for _clip, _label in [(2.0, "clahe_2"), (3.5, "clahe_35"), (6.0, "clahe_6")]:
        _c = cv2.createCLAHE(clipLimit=_clip, tileGridSize=(16, 16))
        _bright = cv2.cvtColor(_c.apply(_gray_dbg), cv2.COLOR_GRAY2BGR)
        cv2.imwrite(str(Path(debug_dir) / f"brightness_{_label}.jpg"), _bright)
    # Gamma escuro→claro: gamma=0.5 clareia sombras sem saturar brancos
    _gamma = np.array([((i / 255.0) ** 0.5) * 255 for i in range(256)], dtype=np.uint8)
    cv2.imwrite(str(Path(debug_dir) / "brightness_gamma05.jpg"), cv2.LUT(dbg, _gamma))

    # Região de respostas → retângulo vermelho
    cv2.rectangle(dbg, (crop_x1, crop_y1), (crop_x2, crop_y2), (0, 0, 255), 3)

    # Candidatos → azul fino
    for x, y, w, h in candidates:
        cv2.rectangle(dbg, (x, y), (x + w, y + h), (255, 100, 0), 1)

    # Células detectadas → verde com Q+letra+fill%; preenchidas em laranja
    for cell in cells:
        letra = ALTERNATIVES[cell.col] if cell.col < len(ALTERNATIVES) else str(cell.col)
        is_high = cell.fill_ratio >= 0.50  # realça candidatas a preenchidas
        color = (0, 140, 255) if is_high else (50, 200, 50)
        thickness = 3 if is_high else 1
        cv2.rectangle(dbg, (cell.x, cell.y), (cell.x + cell.w, cell.y + cell.h), color, thickness)
        # Linha superior: número da questão
        q_label = f"Q{cell.row + 1}"
        cv2.putText(dbg, q_label, (cell.x + 1, cell.y + 8),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.22, (100, 0, 200), 1)
        # Linha inferior: letra + fill%
        label = f"{letra}{int(cell.fill_ratio * 100)}"
        cv2.putText(dbg, label, (cell.x + 1, cell.y + cell.h - 2),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.28, (0, 0, 180), 1)

    # Linha onde as respostas terminam → Y máximo do bottom das células
    if cells:
        answers_bottom_y = max(cell.y + cell.h for cell in cells)
        cv2.line(dbg, (crop_x1, answers_bottom_y), (crop_x2, answers_bottom_y), (255, 0, 0), 2)
        cv2.putText(dbg, f"answers_end y={answers_bottom_y}", (crop_x1 + 5, answers_bottom_y - 6),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 0, 0), 2)

    import time as _time
    ts = int(_time.time())
    out_path = Path(debug_dir) / f"debug_{ts}.jpg"
    cv2.imwrite(str(out_path), dbg)
    logger.info("Debug salvo: %s | %d candidatos | %d células", out_path, len(candidates), len(cells))


def annotate_results(
    image: np.ndarray,
    cells: list[BubbleCell],
    results: list[QuestionResult],
    fill_threshold_filled: float = 0.38,
) -> np.ndarray:
    """
    Gera imagem anotada com contornos das bolhas detectadas.
    - Verde: resposta marcada (ok)
    - Laranja: ambígua / dupla marcação
    - Cinza: em branco
    """
    out = image.copy() if len(image.shape) == 3 else cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
    result_map = {r.questao: r for r in results}

    for cell in cells:
        q_num = cell.row + 1
        res = result_map.get(q_num)
        letra = ALTERNATIVES[cell.col] if cell.col < len(ALTERNATIVES) else str(cell.col)

        is_selected = (
            res is not None
            and res.resposta == letra
            and res.status == "ok"
        )
        is_ambiguous = (
            res is not None
            and res.status in ("ambigua", "dupla_marcacao")
            and cell.fill_ratio >= fill_threshold_filled * 0.6
        )

        if is_selected:
            color = (0, 210, 80)
            thickness = 3
        elif is_ambiguous:
            color = (0, 140, 255)
            thickness = 2
        else:
            color = (120, 120, 120)
            thickness = 1

        cv2.rectangle(out, (cell.x, cell.y), (cell.x + cell.w, cell.y + cell.h), color, thickness)

        if is_selected or is_ambiguous:
            cv2.putText(out, letra, (cell.x + 1, cell.y + cell.h - 2),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.30, color, 1)

    return out