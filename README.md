# Leitura de Prova API

Pipeline de leitura automática de gabaritos de provas escolares com visão computacional, OCR e validação inteligente.

## Stack

| Componente | Tecnologia |
|---|---|
| API | FastAPI (porta 5040) |
| Visão computacional | OpenCV |
| OCR | Tesseract via pytesseract |
| LLM / validação | Google Gemini 1.5 Flash |
| Orquestração LLM | LangChain |
| Observabilidade | LangSmith |
| PDF | PyMuPDF |

## Pipeline

```
arquivo (PNG/JPG/JPEG/PDF)
    → conversão PDF→imagem (PyMuPDF)
    → pré-processamento (CLAHE, blur)
    → alinhamento / correção de perspectiva (OpenCV warpPerspective)
    → OCR do cabeçalho (nome, número, turma)
    → detecção e classificação de bolhas (fill ratio)
    → validação Gemini (apenas casos ambíguos)
    → JSON estruturado
```

**Regra importante:** OpenCV é a fonte de verdade para bolhas claramente preenchidas ou em branco. O Gemini só é chamado quando o `fill_ratio` cai na zona cinza entre `BUBBLE_EMPTY_THRESHOLD` e `BUBBLE_FILLED_THRESHOLD`.

## Estrutura de Pastas

```
leitura-de-prova/
├── app/
│   ├── main.py                 # Entry point FastAPI
│   ├── api/
│   │   └── routes.py           # POST /api/v1/processar-prova
│   ├── core/
│   │   ├── config.py           # Settings (pydantic-settings)
│   │   └── logging_config.py
│   ├── models/
│   │   └── schemas.py          # Pydantic models
│   ├── services/
│   │   ├── pdf_converter.py    # PDF → numpy
│   │   ├── preprocessor.py     # CLAHE + blur
│   │   ├── aligner.py          # Correção de perspectiva
│   │   ├── ocr_service.py      # Tesseract / cabeçalho
│   │   ├── bubble_detector.py  # Detecção de bolhas OpenCV
│   │   ├── gemini_service.py   # LangChain + Gemini
│   │   └── pipeline.py         # Orquestrador
│   └── utils/
│       └── image_utils.py
├── .env.example
├── requirements.txt
└── README.md
```

## Instalação

### 1. Dependências do sistema

**Linux/macOS:**
```bash
sudo apt-get install tesseract-ocr tesseract-ocr-por   # Debian/Ubuntu
brew install tesseract tesseract-lang                   # macOS
```

**Windows:**
- Baixe o instalador em https://github.com/UB-Mannheim/tesseract/wiki
- Adicione ao PATH ou configure `TESSERACT_CMD` no `.env`

### 2. Ambiente Python

```bash
python -m venv .venv
source .venv/bin/activate        # Linux/macOS
.venv\Scripts\activate           # Windows

pip install -r requirements.txt
```

### 3. Configuração

```bash
cp .env.example .env
```

Edite `.env` com suas chaves:

```env
GOOGLE_API_KEY=sua_chave_gemini
LANGCHAIN_API_KEY=sua_chave_langsmith
TESSERACT_CMD=C:\Program Files\Tesseract-OCR\tesseract.exe   # Windows
```

### 4. Executar

```bash
python -m app.main
# ou
uvicorn app.main:app --host 0.0.0.0 --port 5040 --reload
```

A API estará disponível em:
- **Swagger UI:** http://localhost:5040/docs
- **ReDoc:** http://localhost:5040/redoc

## Endpoint

### `POST /api/v1/processar-prova`

**Form-data:**

| Campo | Tipo | Obrigatório | Descrição |
|---|---|---|---|
| `arquivo` | file | Sim | PNG, JPG, JPEG ou PDF |
| `n_questoes` | int | Não (padrão: 20) | Número de questões |
| `n_alternativas` | int | Não (padrão: 5) | Alternativas por questão |
| `gabarito` | string | Não | Ex: `A,B,C,D,E,...` para calcular acertos |

**Exemplo com curl:**

```bash
curl -X POST http://localhost:5040/api/v1/processar-prova \
  -F "arquivo=@gabarito.jpg" \
  -F "n_questoes=20" \
  -F "n_alternativas=5" \
  -F "gabarito=A,B,C,A,E,B,D,C,A,B,E,C,D,A,B,C,D,E,A,B"
```

**Resposta JSON:**

```json
{
  "aluno": {
    "nome": "João da Silva",
    "numero": "2024001",
    "turma": "3A"
  },
  "prova": "gabarito.jpg",
  "questoes": [
    {
      "questao": 1,
      "resposta": "B",
      "status": "ok",
      "confianca": 0.92,
      "validado_gemini": false
    },
    {
      "questao": 2,
      "resposta": null,
      "status": "ambigua",
      "confianca": 0.5,
      "validado_gemini": false
    },
    {
      "questao": 3,
      "resposta": null,
      "status": "dupla_marcacao",
      "confianca": 0.88,
      "validado_gemini": false
    }
  ],
  "total_questoes": 20,
  "total_respondidas": 18,
  "total_ambiguas": 1,
  "processado_em": "2026-04-22T14:30:00+00:00"
}
```

### Status das questões

| Status | Descrição |
|---|---|
| `ok` | Marcação clara e única |
| `em_branco` | Nenhuma alternativa marcada |
| `dupla_marcacao` | Mais de uma alternativa marcada |
| `ambigua` | Fill ratio na zona cinza — validado por Gemini se disponível |

## Configuração dos Thresholds

Os thresholds de fill ratio controlam quando uma bolha é considerada marcada:

```env
BUBBLE_EMPTY_THRESHOLD=0.12    # abaixo → em_branco
BUBBLE_FILLED_THRESHOLD=0.40   # acima  → ok
                                # entre os dois → ambigua → Gemini
```

Ajuste esses valores conforme a qualidade das cópias/digitalizações da escola.

## LangSmith

Com `LANGCHAIN_TRACING_V2=true` e `LANGCHAIN_API_KEY` configurados, cada chamada ao Gemini aparece automaticamente no dashboard do LangSmith com:
- Input (prompt + imagem)
- Output (JSON de validação)
- Latência e tokens usados
- Rastreio completo da chain

## Calibração da Grade

Por padrão, a grade de bolhas é buscada entre:
- Vertical: 25% a 95% da altura da imagem alinhada
- Horizontal: 5% a 95% da largura

Para gabaritos com layout diferente, ajuste os parâmetros em `detect_answer_grid()`:
```python
grid_top_ratio=0.30,
grid_bottom_ratio=0.92,
grid_left_ratio=0.10,
grid_right_ratio=0.90,
```
