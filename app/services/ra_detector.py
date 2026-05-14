from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import cv2
import numpy as np

from app.services.bubble_detector import _compute_fill_ratio, _find_bubble_candidates, _histogram_peaks

logger = logging.getLogger(__name__)

DIGITS = ["0", "1", "2", "3", "4", "5", "6", "7", "8", "9"]
N_COLS = 10  # always 0–9


@dataclass
class RAResult:
    ra: Optional[str]      # e.g. "1234567" or None if detection failed
    confidence: float      # mean confidence across digits


def detect_ra(
    aligned_image: np.ndarray,
    n_digits: int,
    region_top_ratio: float = 0.05,
    region_bottom_ratio: float = 0.23,
    region_left_ratio: float = 0.62,
    region_right_ratio: float = 0.95,
    fill_threshold_empty: float = 0.05,
    fill_threshold_filled: float = 0.10,
    debug_dir: Optional[str] = None,
) -> RAResult:
    """
    Detect RA (student ID) from the mini bubble grid in the top-right corner.

    Layout:
      - Rows    = digits of the RA (n_digits rows)
      - Columns = 0–9 (10 columns, always)
      - Each row has exactly one filled bubble → that digit's value

    Uses fixed uniform grid over the ROI — works reliably when the ROI
    is cropped tightly to only the bubble area (no labels, no header).
    """
    gray = (cv2.cvtColor(aligned_image, cv2.COLOR_BGR2GRAY)
            if len(aligned_image.shape) == 3 else aligned_image.copy())

    # CLAHE: normaliza iluminação desigual de fotos de celular antes de medir fill_ratio
    clahe = cv2.createCLAHE(clipLimit=3.5, tileGridSize=(16, 16))
    gray = clahe.apply(gray)

    h_full, w_full = gray.shape
    y1 = int(h_full * region_top_ratio)
    y2 = int(h_full * region_bottom_ratio)
    x1 = int(w_full * region_left_ratio)
    x2 = int(w_full * region_right_ratio)

    roi = gray[y1:y2, x1:x2]
    roi_h, roi_w = roi.shape

    # if debug_dir:
    #     Path(debug_dir).mkdir(parents=True, exist_ok=True)
    #     dbg_full = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
    #     cv2.rectangle(dbg_full, (x1, y1), (x2, y2), (0, 255, 255), 2)
    #     cv2.imwrite(str(Path(debug_dir) / "ra_00_roi.jpg"), dbg_full)

    bg_brightness = float(np.percentile(roi.astype(np.float32), 97))
    logger.info("RA bg_brightness (p97 roi): %.1f", bg_brightness)

    # ── Detecta candidatos a bolhas na ROI ───────────────────────────────────
    candidates_local = _find_bubble_candidates(roi, debug_dir=None)
    logger.info("RA candidatos detectados: %d", len(candidates_local))

    # if debug_dir:
    #     dbg_roi = cv2.cvtColor(roi, cv2.COLOR_GRAY2BGR)
    #     for cx, cy, cw, ch in candidates_local:
    #         cv2.rectangle(dbg_roi, (cx, cy), (cx + cw, cy + ch), (255, 100, 0), 1)
    #     cv2.imwrite(str(Path(debug_dir) / "ra_02_candidates.jpg"), dbg_roi)

    # ── Agrupa candidatos diretamente em linhas × colunas ────────────────────
    # Sem histograma: usa bbox real de cada bolha detectada.
    # Agrupa por Y (linhas), dentro de cada linha ordena por X (colunas).
    # Primeira coluna de cada linha = índice impresso → descarta.
    if len(candidates_local) >= n_digits * N_COLS * 0.25:
        avg_h = float(np.median([c[3] for c in candidates_local]))
        avg_w = float(np.median([c[2] for c in candidates_local]))

        # Agrupa candidatos em linhas: candidatos com cy próximos (< avg_h * 0.6) = mesma linha
        sorted_by_y = sorted(candidates_local, key=lambda c: c[1] + c[3] / 2.0)
        raw_lines: list[list[tuple]] = []
        for cand in sorted_by_y:
            cy = cand[1] + cand[3] / 2.0
            if raw_lines and cy - (raw_lines[-1][-1][1] + raw_lines[-1][-1][3] / 2.0) < avg_h * 0.6:
                raw_lines[-1].append(cand)
            else:
                raw_lines.append([cand])

        logger.info("RA: %d linhas brutas detectadas (esperado %d)", len(raw_lines), n_digits)

        # Mantém só as n_digits linhas com mais candidatos (descarta ruído)
        raw_lines.sort(key=lambda l: len(l), reverse=True)
        best_lines = raw_lines[:n_digits]
        # Reordena por Y (topo→baixo)
        best_lines.sort(key=lambda l: float(np.mean([c[1] + c[3] / 2.0 for c in l])))

        # Dentro de cada linha: ordena por X, descarta primeira coluna (índice impresso),
        # mantém as N_COLS seguintes
        grid_cells: dict[tuple[int, int], tuple] = {}
        row_centers: list[float] = []
        col_centers: list[float] = [0.0] * N_COLS  # acumulado para debug

        for row_idx, line in enumerate(best_lines):
            line_sorted = sorted(line, key=lambda c: c[0] + c[2] / 2.0)
            # Descarta primeira coluna (índice) se linha tem > N_COLS candidatos
            bubble_cols = line_sorted[1:] if len(line_sorted) > N_COLS else line_sorted
            bubble_cols = bubble_cols[:N_COLS]

            rc = float(np.mean([c[1] + c[3] / 2.0 for c in line]))
            row_centers.append(rc)

            for col_idx, (bx, by, bw, bh) in enumerate(bubble_cols):
                cell_img = roi[max(0, by):by + bh, max(0, bx):bx + bw]
                if cell_img.size == 0:
                    continue
                fill = _compute_fill_ratio(cell_img, bg_brightness)
                key = (row_idx, col_idx)
                if key not in grid_cells or fill > grid_cells[key][0]:
                    grid_cells[key] = (fill, cell_img.copy(), bx, by, bw, bh)
                cc = bx + bw / 2.0
                col_centers[col_idx] = (col_centers[col_idx] * row_idx + cc) / (row_idx + 1)

        logger.info("RA row_centers (agrupamento): %s", [f"{c:.1f}" for c in row_centers])
        logger.info("RA col_centers (agrupamento): %s", [f"{c:.1f}" for c in col_centers])

        # Monta fills[row][col]
        fills: list[list[float]] = []
        for row in range(n_digits):
            row_fills: list[float] = []
            for col in range(N_COLS):
                f = grid_cells.get((row, col), (0.0,))[0]
                row_fills.append(f)
            fills.append(row_fills)

    else:
        # ── Fallback: grade uniforme sobre bbox ──────────────────────────────
        logger.warning("RA: poucos candidatos (%d) → fallback grade uniforme", len(candidates_local))
        bubble_y1, bubble_y2, bubble_x1, bubble_x2 = _find_bubble_bbox(roi)
        grid_roi = roi[bubble_y1:bubble_y2, bubble_x1:bubble_x2]
        grid_h, grid_w = grid_roi.shape
        cell_h_fb = grid_h / n_digits
        cell_w_fb = grid_w / N_COLS
        col_centers = [cell_w_fb * 0.5 + i * cell_w_fb for i in range(N_COLS)]
        row_centers = [cell_h_fb * 0.5 + i * cell_h_fb for i in range(n_digits)]
        half_h = cell_h_fb * 0.42
        half_w = cell_w_fb * 0.42
        fills = []
        for row in range(n_digits):
            row_fills = []
            rc = row_centers[row]
            ry1 = max(0, int(rc - half_h))
            ry2 = min(grid_h, int(rc + half_h))
            for col in range(N_COLS):
                cc = col_centers[col]
                cx1 = max(0, int(cc - half_w))
                cx2 = min(grid_w, int(cc + half_w))
                cell = grid_roi[ry1:ry2, cx1:cx2]
                row_fills.append(_compute_fill_ratio(cell, bg_brightness) if cell.size > 0 else 0.0)
            fills.append(row_fills)
        # ajusta col/row_centers para coordenadas da roi para debug
        col_centers = [bubble_x1 + c for c in col_centers]
        row_centers = [bubble_y1 + r for r in row_centers]
        avg_w = grid_w / N_COLS
        avg_h = grid_h / n_digits

    # if debug_dir:
    #     _save_ra_debug(roi, fills, n_digits, row_centers, col_centers, debug_dir)

    # ── Decode ────────────────────────────────────────────────────────────────
    ra_digits: list[str] = []
    confidences: list[float] = []

    for row in range(n_digits):
        row_fills = fills[row]
        best_col = int(np.argmax(row_fills))
        best_fill = row_fills[best_col]

        # Log all fills for this row to aid threshold tuning
        fills_str = " ".join(f"{DIGITS[c]}={row_fills[c]:.2f}" for c in range(N_COLS))
        logger.debug("RA row %d fills: %s", row + 1, fills_str)

        if best_fill < fill_threshold_empty:
            ra_digits.append("?")
            confidences.append(0.0)
            logger.info("RA digit %d: blank (best_fill=%.2f)", row + 1, best_fill)
            continue

        if best_fill < fill_threshold_filled:
            ra_digits.append("?")
            confidences.append(0.5)
            logger.info("RA digit %d: ambiguous (best_fill=%.2f col=%s)", row + 1, best_fill, DIGITS[best_col])
            continue

        sorted_fills = sorted(row_fills, reverse=True)
        second_fill = sorted_fills[1] if len(sorted_fills) > 1 else 0.0
        # Margem adaptativa: quando fills são uniformemente altos (ruído celular),
        # o spread (best - median) é pequeno. Exigimos que o melhor seja pelo menos
        # 35% do spread acima do segundo, garantindo distinção real.
        row_median = float(np.median(row_fills))
        spread = best_fill - row_median
        # Margem mínima 0.08 (scanner limpo), sobe até 0.25 quando spread < 0.15
        adaptive_margin = max(0.08, min(0.25, 0.20 - spread * 0.5))
        if second_fill >= fill_threshold_filled and (best_fill - second_fill) <= adaptive_margin:
            ra_digits.append("?")
            confidences.append(0.3)
            logger.info("RA digit %d: double-mark (%.2f / %.2f)", row + 1, best_fill, second_fill)
            continue

        digit = DIGITS[best_col]
        conf = min(1.0, 0.6 + (best_fill - fill_threshold_filled))
        ra_digits.append(digit)
        confidences.append(conf)
        logger.info("RA digit %d: %s (fill=%.2f conf=%.2f)", row + 1, digit, best_fill, conf)

    ra_str = "".join(ra_digits)
    mean_conf = float(np.mean(confidences)) if confidences else 0.0

    if "?" in ra_str:
        logger.warning("RA detection partial: %s (conf=%.2f)", ra_str, mean_conf)
        if all(d == "?" for d in ra_digits):
            return RAResult(ra=None, confidence=0.0)

    logger.info("RA detectado: %s (conf=%.2f)", ra_str, mean_conf)
    return RAResult(ra=ra_str, confidence=mean_conf)


def _detect_col_centers(roi: np.ndarray, n_cols: int, approx_cell_w: float) -> list[float]:
    """
    Detecta centros reais das n_cols colunas de bolhas via projeção vertical.
    Fallback para grade uniforme se não encontrar picos suficientes.
    """
    h, w = roi.shape
    clahe = cv2.createCLAHE(clipLimit=3.5, tileGridSize=(8, 8))
    eq = clahe.apply(roi)
    _, thresh = cv2.threshold(eq, 0, 255, cv2.THRESH_BINARY_INV | cv2.THRESH_OTSU)

    v_proj = thresh.sum(axis=0).astype(float)
    k = np.ones(5) / 5.0
    v_proj = np.convolve(v_proj, k, mode="same")

    # Ignora bordas (10% esq/dir) — linha do retângulo RA gera pico espúrio
    border = max(3, int(w * 0.10))
    min_dist = max(3, int(approx_cell_w * 0.6))
    threshold = v_proj.max() * 0.25
    peaks: list[int] = []
    for i in range(border, len(v_proj) - border):
        if v_proj[i] > threshold and v_proj[i] >= v_proj[i-1] and v_proj[i] >= v_proj[i+1]:
            if not peaks or i - peaks[-1] >= min_dist:
                peaks.append(i)

    logger.info("RA col_centers detectados: %d picos para %d colunas", len(peaks), n_cols)

    if len(peaks) >= n_cols:
        nms_dist = max(3, int(approx_cell_w * 0.9))
        nms_peaks: list[int] = []
        for p in sorted(peaks, key=lambda x: v_proj[x], reverse=True):
            if not nms_peaks or all(abs(p - q) >= nms_dist for q in nms_peaks):
                nms_peaks.append(p)
            if len(nms_peaks) == n_cols:
                break
        if len(nms_peaks) == n_cols:
            return [float(p) for p in sorted(nms_peaks)]

    # Fallback: grade uniforme
    start = approx_cell_w * 0.5
    return [start + i * approx_cell_w for i in range(n_cols)]


def _detect_row_centers(roi: np.ndarray, n_rows: int, approx_cell_h: float) -> list[float]:
    """
    Detecta centros reais das n_rows linhas de bolhas via projeção horizontal.
    Fallback para grade uniforme se não encontrar picos suficientes.
    """
    h, w = roi.shape
    clahe = cv2.createCLAHE(clipLimit=3.5, tileGridSize=(8, 8))
    eq = clahe.apply(roi)
    _, thresh = cv2.threshold(eq, 0, 255, cv2.THRESH_BINARY_INV | cv2.THRESH_OTSU)

    h_proj = thresh.sum(axis=1).astype(float)
    k = np.ones(5) / 5.0
    h_proj = np.convolve(h_proj, k, mode="same")

    # Ignora bordas (10% topo/base) — linha do retângulo RA gera pico espúrio
    border = max(3, int(h * 0.10))
    min_dist = max(3, int(approx_cell_h * 0.6))
    threshold = h_proj.max() * 0.25
    peaks: list[int] = []
    for i in range(border, len(h_proj) - border):
        if h_proj[i] > threshold and h_proj[i] >= h_proj[i-1] and h_proj[i] >= h_proj[i+1]:
            if not peaks or i - peaks[-1] >= min_dist:
                peaks.append(i)

    logger.info("RA row_centers detectados: %d picos para %d linhas", len(peaks), n_rows)

    if len(peaks) >= n_rows:
        # NMS com distância mínima = 1 spacing: garante 1 pico por linha real.
        # Pegar top-N por valor falha quando picos espúrios têm valor alto e
        # deslocam a seleção, pulando linhas reais.
        nms_dist = max(3, int(approx_cell_h * 0.9))
        nms_peaks: list[int] = []
        for p in sorted(peaks, key=lambda x: h_proj[x], reverse=True):
            if not nms_peaks or all(abs(p - q) >= nms_dist for q in nms_peaks):
                nms_peaks.append(p)
            if len(nms_peaks) == n_rows:
                break
        if len(nms_peaks) == n_rows:
            return [float(p) for p in sorted(nms_peaks)]

    # Fallback: grade uniforme centrada no roi
    start = approx_cell_h * 0.5
    return [start + i * approx_cell_h for i in range(n_rows)]


def _find_bubble_bbox(roi: np.ndarray) -> tuple[int, int, int, int]:
    """
    Find tight bounding box of the bubble grid within the ROI using
    horizontal and vertical dark-pixel projections.
    Returns (y1, y2, x1, x2) in ROI coordinates.
    Falls back to full ROI if detection fails.
    """
    h, w = roi.shape
    # CLAHE antes do threshold: normaliza gradiente de iluminação de fotos de celular
    clahe = cv2.createCLAHE(clipLimit=3.5, tileGridSize=(8, 8))
    roi_eq = clahe.apply(roi)
    blurred = cv2.GaussianBlur(roi_eq, (3, 3), 0)
    _, thresh = cv2.threshold(blurred, 0, 255, cv2.THRESH_BINARY_INV | cv2.THRESH_OTSU)

    # Erosão elimina linhas finas (bordas, separadores) — preserva só blobs de bolhas
    # que são mais espessos. Kernel 3x3 remove ruído sem destruir círculos.
    erode_k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
    thresh_eroded = cv2.erode(thresh, erode_k, iterations=1)

    # Horizontal projection: dark pixels per row
    h_proj = thresh_eroded.sum(axis=1).astype(float)
    # Vertical projection: dark pixels per col
    v_proj = thresh_eroded.sum(axis=0).astype(float)

    # Smooth
    k = np.ones(3) / 3.0
    h_proj = np.convolve(h_proj, k, mode="same")
    v_proj = np.convolve(v_proj, k, mode="same")

    # 0.20: equilibrio entre excluir bordas e incluir bolhas vazias (anel fino)
    h_thresh = h_proj.max() * 0.20
    v_thresh = v_proj.max() * 0.20

    h_active = np.where(h_proj > h_thresh)[0]
    v_active = np.where(v_proj > v_thresh)[0]

    if len(h_active) < 3 or len(v_active) < 3:
        return 0, h, 0, w

    # Add small padding
    pad_y = max(2, int(h * 0.01))
    pad_x = max(2, int(w * 0.01))

    y1 = max(0, int(h_active[0]) - pad_y)
    y2 = min(h, int(h_active[-1]) + pad_y)
    x1 = max(0, int(v_active[0]) - pad_x)
    x2 = min(w, int(v_active[-1]) + pad_x)

    return y1, y2, x1, x2


def _save_ra_debug(
    roi: np.ndarray,
    fills: list[list[float]],
    n_digits: int,
    row_centers: list[float],
    col_centers: list[float],
    debug_dir: str,
) -> None:
    dbg = cv2.cvtColor(roi, cv2.COLOR_GRAY2BGR)

    col_arr = sorted(c for c in col_centers if c > 0)
    row_arr = sorted(row_centers)
    half_w = (float(np.median(np.diff(col_arr))) * 0.45) if len(col_arr) >= 2 else roi.shape[1] / N_COLS / 2
    half_h = (float(np.median(np.diff(row_arr))) * 0.45) if len(row_arr) >= 2 else roi.shape[0] / n_digits / 2

    for row in range(n_digits):
        if row >= len(row_centers):
            continue
        rc = row_centers[row]
        for col in range(N_COLS):
            if col >= len(col_centers):
                continue
            cc = col_centers[col]
            if cc <= 0:
                continue
            cx1 = int(cc - half_w)
            cx2 = int(cc + half_w)
            ry1 = int(rc - half_h)
            ry2 = int(rc + half_h)
            fill = fills[row][col] if row < len(fills) and col < len(fills[row]) else 0.0
            color = (0, 140, 255) if fill >= 0.38 else (50, 200, 50) if fill >= 0.10 else (180, 180, 180)
            cv2.rectangle(dbg, (cx1, ry1), (cx2, ry2), color, 1)
            label = f"{DIGITS[col]}={int(fill*100)}"
            cv2.putText(dbg, label, (cx1 + 1, ry2 - 2),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.20, (0, 0, 180), 1)

    # Path(debug_dir).mkdir(parents=True, exist_ok=True)
    # cv2.imwrite(str(Path(debug_dir) / "ra_01_grid.jpg"), dbg)
