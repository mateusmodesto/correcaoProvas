from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


class DetalheComparacao(BaseModel):
    resposta_aluno: Optional[str] = None
    gabarito: str
    acerto: bool
    anulada: bool = False
    disciplina: Optional[str] = None


class ComparacaoGabarito(BaseModel):
    total_acertos: int
    total_erros: int
    total_em_branco: int
    total_anuladas: int = 0
    total_questoes: int
    porcentagem_acerto: float = Field(..., ge=0.0, le=100.0)
    detalhes: dict[str, DetalheComparacao]
    acertos_por_disciplina: dict[str, int] = Field(default_factory=dict)
    erros_por_disciplina: dict[str, int] = Field(default_factory=dict)


class StatusQuestao(str, Enum):
    ok = "ok"
    em_branco = "em_branco"
    dupla_marcacao = "dupla_marcacao"
    ambigua = "ambigua"


class RespostaQuestao(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    resposta: Optional[str] = Field(None, description="Letra marcada (A-E) ou None se em branco")
    status: StatusQuestao

    @field_validator("resposta")
    @classmethod
    def resposta_uppercase(cls, v: Optional[str]) -> Optional[str]:
        return v.upper() if v else None


class DadosAluno(BaseModel):
    nome: Optional[str] = None
    numero: Optional[str] = None
    turma: Optional[str] = None
    ra: Optional[str] = None


class ResultadoProva(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    prova: Optional[str] = None
    dados_aluno: Optional[DadosAluno] = Field(
        None, description="Dados extraídos do cabeçalho (nome, número, turma) via OCR"
    )
    respostas: dict[str, RespostaQuestao] = Field(
        description="Detalhes de cada questão: status e resposta"
    )
    respostas_gemini: Optional[dict[str, Optional[str]]] = Field(
        None, description="Respostas com validação Gemini (presente apenas quando Gemini foi utilizado)"
    )
    comparacao: Optional[ComparacaoGabarito] = Field(
        None, description="Comparação com gabarito oficial (presente se gabarito enviado)"
    )
    total_questoes: int
    total_respondidas: int = Field(0, description="Questões com resposta detectada (exclui em branco)")
    imagem_anotada: Optional[str] = Field(None, description="JPEG anotado em base64")
    info_alinhamento: Optional[dict] = Field(
        None, description="Sheet_found, rotation_deg e outras métricas de alinhamento"
    )
    processado_em: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


class ProcessarProvaRequest(BaseModel):
    """Parâmetros opcionais enviados via form-data junto com o arquivo."""
    n_questoes: int = Field(100, ge=1, le=500, description="Total de questões no gabarito")
    n_alternativas: int = Field(5, ge=2, le=10, description="Alternativas por questão (A-E = 5)")
    n_paineis: int = Field(
        4, ge=1, le=10,
        description=(
            "Número de colunas de questões no gabarito. "
            "Ex: gabarito 100 questões em 4 colunas de 25 → n_paineis=4"
        ),
    )
    gabarito: Optional[list[str]] = Field(
        None, description="Gabarito oficial (lista de letras) para calcular acertos"
    )


class ErroResponse(BaseModel):
    erro: str
    detalhe: Optional[str] = None
