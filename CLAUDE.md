# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Automated reading pipeline for school exam answer sheets. Accepts a scanned image or PDF, detects filled bubbles via OpenCV, extracts student header data via Tesseract OCR, and looks up student identity via SQL Server RA bubble detection.

## Commands

### Running the server

```bash
uvicorn app.main:app --host 0.0.0.0 --port 5041 --reload
```

Auto-reload activates automatically when `DEBUG=true` in `.env`.

### Installing dependencies

```bash
pip install -r requirements.txt
```

Requires Tesseract OCR installed on the system. Windows path: `C:\Program Files\Tesseract-OCR\tesseract.exe`.
Requires ODBC Driver 17 for SQL Server installed for `pyodbc`.

### Manual testing

```bash
curl -X POST http://localhost:5041/api/v1/processar-prova \
  -F "arquivo=@teste/gabarito2.jpg" \
  -F "prova_id=1"
```

Or without a registered exam (ad-hoc):

```bash
curl -X POST http://localhost:5041/api/v1/processar-prova \
  -F "arquivo=@teste/gabarito2.jpg" \
  -F "n_questoes=20" \
  -F "n_alternativas=5"
```

No automated test suite — test files live in `teste/`, debug output goes to `debug/` (timestamped subdirs).

## Architecture

Two orchestration layers: `pipeline.py` calls `omr_service.py`, which calls `aligner.py`, `bubble_detector.py`, and `ra_detector.py`.

### Pipeline stages (in order)

1. **PDF/Image conversion** (`pdf_converter.py`) — PyMuPDF converts to numpy array at 200 DPI
2. **DB config lookup** (`pipeline.py`) — when `prova_id` is supplied, loads exam config + answer key from SQL Server via `db_service.py`; this overrides all `n_questoes`/`n_alternativas` params
3. **Alignment** (`aligner.py`) — 3-level fallback: full perspective warp → rotation-only deskew (Hough lines) → identity. Output always 1240×1754 px
4. **Bubble detection** (`bubble_detector.py`) — horizontal-projection answer section detection; KMeans clustering for multi-panel X-splitting; histogram-based grid line reconstruction; fill_ratio normalized by background brightness; phantom/orphan row correction; annotated debug images when `DEBUG=true`
5. **RA detection** (`ra_detector.py`) — detects student ID from mini bubble grid (0–9 columns) in top-right corner of sheet; uses `cfg.ra_n_digits` + `cfg.ra_region`; skipped when model has no RA config
6. **Header OCR** (`ocr_service.py`) — Tesseract extracts `nome`, `numero`, `turma` via regex
7. **Student lookup** (`db_service.buscar_aluno_por_ra`) — resolves detected RA to full name from `ly_aluno` in the Lyceum DB; `ra_manual` param overrides auto-detected RA

OpenCV is the source of truth for clear cases. Gemini validation has been removed.

### Config priority (highest → lowest)

1. DB model loaded via `prova_id` (builds `ModelConfig` in `pipeline.py`)
2. DB model loaded by `modelo` string key via `get_model_config()`
3. Env vars `BUBBLE_EMPTY_THRESHOLD` / `BUBBLE_FILLED_THRESHOLD` + auto `n_panels` (≥80q → 4)
4. `ModelConfig` dataclass defaults

## Database

Two SQL Server databases accessed via `pyodbc`:

| DB env var | Default | Tables used |
| --- | --- | --- |
| `DB_SERVER` / `DB_NAME` | `192.168.0.9` / `dtb_anchieta_prod` | `anchi_modelos_gabarito`, `anchi_cadastro_prova`, `anchi_gabaritos_processados`, `anchi_modelo_grid` |
| `LYCEUM_DB_SERVER` / `LYCEUM_DB_NAME` | same server / `dtb_lyceum_prod` | `ly_aluno` |

All DB calls in `db_service.py` are silent-fail (returns `None`/`False`/empty on exception) — the pipeline continues without DB data.

## Key Configuration (`.env`)

| Variable | Purpose |
| --- | --- |
| `BUBBLE_EMPTY_THRESHOLD` | fill_ratio below this → empty (default 0.42) |
| `BUBBLE_FILLED_THRESHOLD` | fill_ratio above this → filled (default 0.60) |
| `TESSERACT_CMD` | Path to tesseract binary |
| `API_PORT` | 5041 (5040 reserved by Windows Search) |
| `DEBUG` | Enables auto-reload + saves annotated debug images to `debug/` |
| `DB_SERVER` / `DB_NAME` / `DB_USER` / `DB_PASSWORD` | Main SQL Server connection |
| `LYCEUM_DB_SERVER` / `LYCEUM_DB_NAME` | Lyceum DB for student name lookup |
| `LANGCHAIN_TRACING_V2` / `LANGCHAIN_PROJECT` | LangSmith observability (optional) |

Threshold tuning is the primary lever for accuracy.

## API

Base path: `/api/v1`

### Main endpoint

`POST /processar-prova` — form-data fields:

- `arquivo` — PNG/JPEG/JPG/PDF, max 20 MB
- `prova_id` — (preferred) ID of registered exam; loads model + answer key from DB
- `n_questoes` / `n_alternativas` — used only when `prova_id` not provided
- `ra_manual` — overrides auto-detected RA

Returns `ResultadoProva`: `dados_aluno` (nome/numero/turma/ra), `respostas` (per-question status + letter), `comparacao` (if answer key exists), `imagem_anotada` (base64 JPEG), `info_alinhamento`.

### Model/exam management endpoints

- `GET /modelos` — `{id: descricao}` from DB
- `GET /modelos-lista` — list with id/descricao/n_panels/n_questoes for frontend
- `GET /modelos/{id}` / `POST /modelos` / `PUT /modelos/{id}` / `DELETE /modelos/{id}`
- `GET /provas` / `GET /provas/{id}` / `POST /provas` / `PUT /provas/{id}` / `DELETE /provas/{id}`

## Model Config (`ModelConfig` dataclass)

Defined in `app/core/model_registry.py`. Key fields beyond grid ratios:

- `ra_n_digits` — number of RA digits; when set, enables RA bubble detection
- `ra_region` — dict with `top/bottom/left/right` ratios for the RA grid ROI
- `ra_fill_threshold_empty` / `ra_fill_threshold_filled` — separate thresholds for RA bubbles
- `disable_auto_top` — disables horizontal-projection topo detection in bubble_detector

## Question Status Enum

`StatusQuestao` in `schemas.py`: `ok`, `em_branco`, `dupla_marcacao`, `ambigua`.
