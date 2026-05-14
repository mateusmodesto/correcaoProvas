from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

import cv2
import numpy as np

from app.utils.image_utils import four_point_transform, order_points, resize_with_aspect

logger = logging.getLogger(__name__)

OUTPUT_WIDTH = 1240
OUTPUT_HEIGHT = 1754


@dataclass
class AlignmentResult:
    aligned: np.ndarray
    sheet_found: bool
    rotation_deg: float = 0.0
    corners: Optional[np.ndarray] = None


def _fix_orientation(image: np.ndarray) -> np.ndarray:
    """Rotaciona landscape → portrait antes do alinhamento."""
    h, w = image.shape[:2]
    if w > h:
        logger.info("Imagem landscape (%dx%d) → rotacionando -90°", w, h)
        return cv2.rotate(image, cv2.ROTATE_90_COUNTERCLOCKWISE)
    return image


def align_sheet(image: np.ndarray) -> AlignmentResult:
    """
    Pipeline de alinhamento em 3 tentativas, da mais para a menos precisa:
    1. Detecção do contorno da folha + warpPerspective (melhor)
    2. Só correção de rotação via Hough lines (sem perspectiva)
    3. Sem correção — usa a imagem como está
    """
    image = _fix_orientation(image)

    # Tenta perspectiva completa
    result = _try_perspective_correction(image)
    if result is not None:
        logger.info("Alinhamento: perspectiva completa (rotação=%.1f°)", result.rotation_deg)
        return result

    # Tenta apenas deskew por rotação
    result = _try_deskew_only(image)
    if result is not None:
        logger.info("Alinhamento: só rotação corrigida (%.1f°)", result.rotation_deg)
        return result

    # Sem correção
    logger.warning("Alinhamento: nenhuma correção aplicada — imagem usada como está")
    resized = cv2.resize(image, (OUTPUT_WIDTH, OUTPUT_HEIGHT))
    return AlignmentResult(aligned=resized, sheet_found=False, rotation_deg=0.0)


# ─── Estratégia 1: perspectiva completa ───────────────────────────────────────

def _try_perspective_correction(image: np.ndarray) -> Optional[AlignmentResult]:
    working = resize_with_aspect(image, max_side=1600)
    scale_x = image.shape[1] / working.shape[1]
    scale_y = image.shape[0] / working.shape[0]

    gray = cv2.cvtColor(working, cv2.COLOR_BGR2GRAY) if len(working.shape) == 3 else working.copy()
    gray = cv2.fastNlMeansDenoising(gray, h=7, templateWindowSize=7, searchWindowSize=21)
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)

    close_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5))
    blurred = cv2.morphologyEx(blurred, cv2.MORPH_CLOSE, close_kernel)

    for lo, hi in [(30, 120), (50, 150), (20, 80), (10, 50)]:
        edged = cv2.Canny(blurred, lo, hi)
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
        edged = cv2.dilate(edged, kernel, iterations=2)

        contours, _ = cv2.findContours(edged, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        contours = sorted(contours, key=cv2.contourArea, reverse=True)

        min_area = working.shape[0] * working.shape[1] * 0.30

        for cnt in contours[:15]:
            if cv2.contourArea(cnt) < min_area:
                break
            peri = cv2.arcLength(cnt, True)

            # Tenta epsilon progressivo: fotos de celular com perspectiva precisam
            # de epsilon maior para aproximar o contorno em 4 pontos
            for eps_factor in [0.02, 0.03, 0.04, 0.05]:
                approx = cv2.approxPolyDP(cnt, eps_factor * peri, True)
                if len(approx) == 4:
                    break

            if len(approx) != 4:
                continue

            corners = approx.reshape(4, 2).astype(np.float32)

            if not _is_valid_quad(corners, working.shape):
                continue

            corners[:, 0] *= scale_x
            corners[:, 1] *= scale_y

            warped = four_point_transform(image, corners)
            aligned = cv2.resize(warped, (OUTPUT_WIDTH, OUTPUT_HEIGHT))
            rect = order_points(corners)
            angle = _angle_from_corners(rect)

            return AlignmentResult(
                aligned=aligned,
                sheet_found=True,
                rotation_deg=angle,
                corners=corners,
            )

    return None


def _is_valid_quad(corners: np.ndarray, img_shape: tuple) -> bool:
    """
    Aceita quadrilátero levemente não-convexo (perspectiva de celular gera trapézios):
    - área mínima 25% da imagem
    - ângulos internos entre 50° e 130°
    - solidity > 0.92
    """
    h, w = img_shape[:2]
    area = cv2.contourArea(corners)
    if area < w * h * 0.25:
        return False

    pts = corners.reshape(4, 2)
    for i in range(4):
        p0 = pts[(i - 1) % 4]
        p1 = pts[i]
        p2 = pts[(i + 1) % 4]
        v1 = p0 - p1
        v2 = p2 - p1
        cos_a = np.dot(v1, v2) / (np.linalg.norm(v1) * np.linalg.norm(v2) + 1e-6)
        angle_deg = float(np.degrees(np.arccos(np.clip(cos_a, -1.0, 1.0))))
        if not (50.0 <= angle_deg <= 130.0):
            return False

    hull = cv2.convexHull(corners.astype(np.int32))
    hull_area = cv2.contourArea(hull)
    if hull_area > 0 and area / hull_area < 0.92:
        return False

    return True


# ─── Estratégia 2: deskew por rotação ────────────────────────────────────────

def _try_deskew_only(image: np.ndarray) -> Optional[AlignmentResult]:
    """
    Detecta o ângulo de inclinação da imagem usando:
    1. Hough lines sobre as bordas
    2. Projeção mínima de pixels (método clássico de deskew)
    Aplica rotação para corrigir e retorna imagem sem distorção de perspectiva.
    """
    angle = _detect_skew_angle(image)

    if abs(angle) < 0.3:
        # Inclinação desprezível — redimensiona e retorna
        resized = cv2.resize(image, (OUTPUT_WIDTH, OUTPUT_HEIGHT))
        return AlignmentResult(aligned=resized, sheet_found=False, rotation_deg=angle)

    if abs(angle) > 45:
        # Ângulo muito grande — provavelmente erro de detecção
        logger.warning("Ângulo de rotação suspeito (%.1f°) — ignorando", angle)
        return None

    corrected = _rotate_image(image, angle)
    resized = cv2.resize(corrected, (OUTPUT_WIDTH, OUTPUT_HEIGHT))
    return AlignmentResult(aligned=resized, sheet_found=False, rotation_deg=angle)


def _detect_skew_angle(image: np.ndarray) -> float:
    """
    Estima o ângulo de inclinação via Hough Lines.
    Retorna graus (positivo = sentido horário).
    """
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if len(image.shape) == 3 else image.copy()
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)
    edged = cv2.Canny(blurred, 50, 150)

    lines = cv2.HoughLinesP(
        edged,
        rho=1,
        theta=np.pi / 180,
        threshold=100,
        minLineLength=max(100, min(image.shape[:2]) // 4),
        maxLineGap=20,
    )

    if lines is None:
        return 0.0

    angles: list[float] = []
    for line in lines:
        x1, y1, x2, y2 = line[0]
        if x2 == x1:
            continue
        angle = float(np.degrees(np.arctan2(y2 - y1, x2 - x1)))
        # Considera apenas linhas próximas do horizontal (±30°)
        if abs(angle) <= 30:
            angles.append(angle)

    if not angles:
        return 0.0

    # Mediana é mais robusta que média
    median_angle = float(np.median(angles))
    logger.debug("Ângulo de inclinação detectado: %.2f° (de %d linhas)", median_angle, len(angles))
    return median_angle


def _rotate_image(image: np.ndarray, angle_deg: float) -> np.ndarray:
    """Rotaciona a imagem em torno do centro sem cortar conteúdo."""
    h, w = image.shape[:2]
    cx, cy = w // 2, h // 2

    M = cv2.getRotationMatrix2D((cx, cy), angle_deg, 1.0)

    # Calcula novo tamanho para não cortar
    cos_a = abs(M[0, 0])
    sin_a = abs(M[0, 1])
    new_w = int(h * sin_a + w * cos_a)
    new_h = int(h * cos_a + w * sin_a)

    M[0, 2] += (new_w / 2) - cx
    M[1, 2] += (new_h / 2) - cy

    rotated = cv2.warpAffine(
        image, M, (new_w, new_h),
        flags=cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_REPLICATE,
    )
    return rotated


def _angle_from_corners(rect: np.ndarray) -> float:
    """Calcula ângulo de rotação a partir dos 4 cantos ordenados."""
    tl, tr = rect[0], rect[1]
    if tr[0] == tl[0]:
        return 0.0
    return float(np.degrees(np.arctan2(tr[1] - tl[1], tr[0] - tl[0])))
