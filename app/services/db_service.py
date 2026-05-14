from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class AlunoInfo:
    ra: str
    nome: str


@dataclass
class ModeloGabarito:
    id: str
    descricao: str
    n_panels: int
    n_alternativas: int
    n_questoes: int
    grid_top_ratio: float
    grid_bottom_ratio: float
    grid_left_ratio: float
    grid_right_ratio: float
    fill_threshold_empty: float
    fill_threshold_filled: float
    disable_auto_top: bool
    ativo: bool = True
    ra_n_digits: Optional[int] = None
    ra_fill_threshold_empty: Optional[float] = None
    ra_fill_threshold_filled: Optional[float] = None
    ra_region_top: Optional[float] = None
    ra_region_bottom: Optional[float] = None
    ra_region_left: Optional[float] = None
    ra_region_right: Optional[float] = None


@dataclass
class CadastroProva:
    id: int
    descricao: str
    modelo_id: str
    gabarito: list[dict]


def _build_conn_str(server: str, db: str, user: str, password: str) -> str:
    if user:
        return (
            f"DRIVER={{ODBC Driver 17 for SQL Server}};"
            f"SERVER={server};DATABASE={db};"
            f"UID={user};PWD={password};"
        )
    return (
        f"DRIVER={{ODBC Driver 17 for SQL Server}};"
        f"SERVER={server};DATABASE={db};"
        f"Trusted_Connection=yes;"
    )


def _get_conn_str() -> str:
    import os
    return _build_conn_str(
        server=os.getenv("DB_SERVER", ""),
        db=os.getenv("DB_NAME", ""),
        user=os.getenv("DB_USER", ""),
        password=os.getenv("DB_PASSWORD", ""),
    )


def _get_BD2_conn_str() -> str:
    import os
    return _build_conn_str(
        server=os.getenv("", os.getenv("DB_SERVER", "")),
        db=os.getenv("", ""),
        user=os.getenv("", os.getenv("DB_USER", "")),
        password=os.getenv("", os.getenv("DB_PASSWORD", "")),
    )


def _get_conn():
    try:
        import pyodbc
    except ImportError:
        raise RuntimeError("pyodbc não instalado")
    return pyodbc.connect(_get_conn_str(), timeout=5)


# ── Aluno ──────────────────────────────────────────────────────────────────────

def buscar_aluno_por_ra(ra: str) -> Optional[AlunoInfo]:
    """Busca nome do aluno em tb_aluno pelo RA detectado no gabarito."""
    if not ra or ra.strip("?") == "":
        return None

    ra_digits = ra.strip()

    try:
        import pyodbc
    except ImportError:
        logger.error("pyodbc não instalado — DB lookup indisponível")
        return None

    try:
        with pyodbc.connect(_get_BD2_conn_str(), timeout=5) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT TOP 1 ALUNO, NOME_COMPL "
                "FROM tb_aluno "
                "WHERE ALUNO = ?",
                ra_digits,
            )
            row = cursor.fetchone()
            if row:
                logger.info("DB lookup RA '%s' → '%s'", ra_digits, row[1])
                return AlunoInfo(ra=str(row[0]).strip(), nome=str(row[1]).strip())
            else:
                logger.info("DB lookup RA '%s' → não encontrado", ra_digits)
                return None
    except Exception as exc:
        logger.warning("DB lookup falhou para RA '%s': %s", ra_digits, exc)
        return None


# ── Modelos / Gabarito ─────────────────────────────────────────────────────────

def buscar_modelo_gabarito(modelo_id: str) -> Optional[ModeloGabarito]:
    """Busca configuração + gabarito em modelos_gabarito pelo id."""
    try:
        with _get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT id, descricao, n_panels, n_alternativas, n_questoes,
                       grid_top_ratio, grid_bottom_ratio,
                       grid_left_ratio, grid_right_ratio,
                       fill_threshold_empty, fill_threshold_filled,
                       disable_auto_top, ativo,
                       ra_n_digits,
                       ra_fill_threshold_empty, ra_fill_threshold_filled,
                       ra_region_top, ra_region_bottom,
                       ra_region_left, ra_region_right
                FROM modelos_gabarito
                WHERE id = ?
                """,
                modelo_id,
            )
            row = cursor.fetchone()
            if not row:
                logger.info("Modelo '%s' não encontrado no DB", modelo_id)
                return None

            (
                id_, descricao, n_panels, n_alternativas, n_questoes,
                grid_top, grid_bottom, grid_left, grid_right,
                thr_empty, thr_filled,
                disable_auto_top, ativo,
                ra_n_digits, ra_thr_empty, ra_thr_filled,
                ra_top, ra_bottom, ra_left, ra_right,
            ) = row

            logger.info("Modelo '%s' carregado do DB (%d questões)", id_, n_questoes)
            return ModeloGabarito(
                id=str(id_),
                descricao=str(descricao),
                n_panels=int(n_panels),
                n_alternativas=int(n_alternativas),
                n_questoes=int(n_questoes),
                grid_top_ratio=float(grid_top),
                grid_bottom_ratio=float(grid_bottom),
                grid_left_ratio=float(grid_left),
                grid_right_ratio=float(grid_right),
                fill_threshold_empty=float(thr_empty),
                fill_threshold_filled=float(thr_filled),
                disable_auto_top=bool(disable_auto_top),
                ativo=bool(ativo),
                ra_n_digits=int(ra_n_digits) if ra_n_digits is not None else None,
                ra_fill_threshold_empty=float(ra_thr_empty) if ra_thr_empty is not None else None,
                ra_fill_threshold_filled=float(ra_thr_filled) if ra_thr_filled is not None else None,
                ra_region_top=float(ra_top) if ra_top is not None else None,
                ra_region_bottom=float(ra_bottom) if ra_bottom is not None else None,
                ra_region_left=float(ra_left) if ra_left is not None else None,
                ra_region_right=float(ra_right) if ra_right is not None else None,
            )
    except Exception as exc:
        logger.warning("buscar_modelo_gabarito('%s') falhou: %s", modelo_id, exc)
        return None


# ── CRUD modelos ──────────────────────────────────────────────────────────────

def listar_modelos() -> dict[str, str]:
    """Retorna {id: descricao} dos modelos ativos no banco."""
    try:
        with _get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id, descricao FROM modelos_gabarito WHERE ativo = 1")
            return {str(row[0]): str(row[1]) for row in cursor.fetchall()}
    except Exception as exc:
        logger.warning("listar_modelos falhou: %s", exc)
        return {}


def listar_modelos_completo() -> list[dict]:
    """Retorna lista de modelos ativos com campos para o frontend."""
    try:
        with _get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT id, descricao, n_panels, n_alternativas, n_questoes
                FROM modelos_gabarito
                WHERE ativo = 1
                ORDER BY descricao
                """
            )
            return [
                {
                    "id": str(row[0]),
                    "descricao": str(row[1]),
                    "n_panels": int(row[2]),
                    "n_alternativas": int(row[3]),
                    "n_questoes": int(row[4]),
                }
                for row in cursor.fetchall()
            ]
    except Exception as exc:
        logger.warning("listar_modelos_completo falhou: %s", exc)
        return []


def obter_modelo_detalhes(modelo_id: str) -> Optional[dict]:
    """Retorna todos os campos de um modelo como dict, ou None se não encontrado."""
    modelo = buscar_modelo_gabarito(modelo_id)
    if modelo is None:
        return None
    return {
        "descricao": modelo.descricao,
        "n_panels": modelo.n_panels,
        "n_alternativas": modelo.n_alternativas,
        "n_questoes": modelo.n_questoes,
        "grid_top_ratio": modelo.grid_top_ratio,
        "grid_bottom_ratio": modelo.grid_bottom_ratio,
        "grid_left_ratio": modelo.grid_left_ratio,
        "grid_right_ratio": modelo.grid_right_ratio,
        "fill_threshold_empty": modelo.fill_threshold_empty,
        "fill_threshold_filled": modelo.fill_threshold_filled,
        "disable_auto_top": modelo.disable_auto_top,
        "ativo": modelo.ativo,
        "ra_n_digits": modelo.ra_n_digits,
        "ra_fill_threshold_empty": modelo.ra_fill_threshold_empty,
        "ra_fill_threshold_filled": modelo.ra_fill_threshold_filled,
        "ra_region_top": modelo.ra_region_top,
        "ra_region_bottom": modelo.ra_region_bottom,
        "ra_region_left": modelo.ra_region_left,
        "ra_region_right": modelo.ra_region_right,
    }


def upsert_modelo_gabarito(modelo_id: str, dados: dict) -> bool:
    """
    INSERT ou UPDATE em modelos_gabarito.
    gabarito deve ser string CSV (ex: 'A,B,C,...').
    Retorna True se bem-sucedido.
    """
    try:
        with _get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                MERGE modelos_gabarito AS target
                USING (SELECT ? AS id) AS source ON target.id = source.id
                WHEN MATCHED THEN UPDATE SET
                    descricao                = ?,
                    n_panels                 = ?,
                    n_alternativas           = ?,
                    n_questoes               = ?,
                    grid_top_ratio           = ?,
                    grid_bottom_ratio        = ?,
                    grid_left_ratio          = ?,
                    grid_right_ratio         = ?,
                    fill_threshold_empty     = ?,
                    fill_threshold_filled    = ?,
                    disable_auto_top         = ?,
                    ativo                    = ?,
                    ra_n_digits              = ?,
                    ra_fill_threshold_empty  = ?,
                    ra_fill_threshold_filled = ?,
                    ra_region_top            = ?,
                    ra_region_bottom         = ?,
                    ra_region_left           = ?,
                    ra_region_right          = ?
                WHEN NOT MATCHED THEN INSERT (
                    id, descricao, n_panels, n_alternativas, n_questoes,
                    grid_top_ratio, grid_bottom_ratio, grid_left_ratio, grid_right_ratio,
                    fill_threshold_empty, fill_threshold_filled,
                    disable_auto_top, ativo,
                    ra_n_digits, ra_fill_threshold_empty, ra_fill_threshold_filled,
                    ra_region_top, ra_region_bottom, ra_region_left, ra_region_right
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                """,
                # USING
                modelo_id,
                # UPDATE
                dados["descricao"],
                dados["n_panels"],
                dados.get("n_alternativas", 5),
                dados.get("n_questoes", 0),
                dados["grid_top_ratio"],
                dados["grid_bottom_ratio"],
                dados["grid_left_ratio"],
                dados["grid_right_ratio"],
                dados["fill_threshold_empty"],
                dados["fill_threshold_filled"],
                dados.get("disable_auto_top", False),
                dados.get("ativo", True),
                dados.get("ra_n_digits"),
                dados.get("ra_fill_threshold_empty"),
                dados.get("ra_fill_threshold_filled"),
                dados.get("ra_region_top"),
                dados.get("ra_region_bottom"),
                dados.get("ra_region_left"),
                dados.get("ra_region_right"),
                # INSERT
                modelo_id,
                dados["descricao"],
                dados["n_panels"],
                dados.get("n_alternativas", 5),
                dados.get("n_questoes", 0),
                dados["grid_top_ratio"],
                dados["grid_bottom_ratio"],
                dados["grid_left_ratio"],
                dados["grid_right_ratio"],
                dados["fill_threshold_empty"],
                dados["fill_threshold_filled"],
                dados.get("disable_auto_top", False),
                dados.get("ativo", True),
                dados.get("ra_n_digits"),
                dados.get("ra_fill_threshold_empty"),
                dados.get("ra_fill_threshold_filled"),
                dados.get("ra_region_top"),
                dados.get("ra_region_bottom"),
                dados.get("ra_region_left"),
                dados.get("ra_region_right"),
            )
            conn.commit()
            logger.info("Modelo '%s' salvo no DB", modelo_id)
            return True
    except Exception as exc:
        logger.warning("upsert_modelo_gabarito('%s') falhou: %s", modelo_id, exc)
        return False


def deletar_modelo_gabarito(modelo_id: str) -> bool:
    """Remove modelo do banco. Retorna True se linha deletada."""
    try:
        with _get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM modelos_gabarito WHERE id = ?", modelo_id)
            deleted = cursor.rowcount
            conn.commit()
            if deleted:
                logger.info("Modelo '%s' deletado do DB", modelo_id)
                return True
            logger.warning("deletar_modelo_gabarito: '%s' não encontrado", modelo_id)
            return False
    except Exception as exc:
        logger.warning("deletar_modelo_gabarito('%s') falhou: %s", modelo_id, exc)
        return False


# ── Cadastro de provas ────────────────────────────────────────────────────────

def _parse_gabarito(gabarito_raw: str) -> list[dict]:
    """Retorna lista de dicts com 'resp' e 'disc' (disciplina pode ser None)."""
    gabarito_str = (gabarito_raw or "").strip()
    if gabarito_str.startswith("{"):
        raw_dict: dict = json.loads(gabarito_str)
        result = []
        for i in range(1, len(raw_dict) + 1):
            key = str(i)
            if key not in raw_dict:
                continue
            entry = raw_dict[key]
            if isinstance(entry, dict):
                result.append({"resp": entry.get("resp", ""), "disc": entry.get("disc")})
            else:
                result.append({"resp": str(entry), "disc": None})
        return result
    return [{"resp": c.strip(), "disc": None} for c in gabarito_str.split(",") if c.strip()]


def listar_provas() -> list[dict]:
    """Retorna lista de provas ativas com modelo associado."""
    try:
        with _get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT p.id, p.descricao, p.modelo_id, m.descricao AS modelo_descricao,
                       m.n_questoes, m.n_alternativas
                FROM cadastro_prova p
                JOIN modelos_gabarito m ON m.id = p.modelo_id
                WHERE m.ativo = 1
                ORDER BY p.descricao
                """
            )
            return [
                {
                    "id": int(row[0]),
                    "descricao": str(row[1]),
                    "modelo_id": str(row[2]),
                    "modelo_descricao": str(row[3]),
                    "n_questoes": int(row[4]),
                    "n_alternativas": int(row[5]),
                }
                for row in cursor.fetchall()
            ]
    except Exception as exc:
        logger.warning("listar_provas falhou: %s", exc)
        return []


def buscar_prova(prova_id: int) -> Optional[CadastroProva]:
    """Busca prova por id, retorna CadastroProva com gabarito parseado."""
    try:
        with _get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT id, descricao, modelo_id, gabarito FROM cadastro_prova WHERE id = ?",
                prova_id,
            )
            row = cursor.fetchone()
            if not row:
                logger.info("Prova '%s' não encontrada no DB", prova_id)
                return None
            id_, descricao, modelo_id, gabarito_raw = row
            return CadastroProva(
                id=int(id_),
                descricao=str(descricao),
                modelo_id=str(modelo_id),
                gabarito=_parse_gabarito(gabarito_raw or ""),
            )
    except Exception as exc:
        logger.warning("buscar_prova('%s') falhou: %s", prova_id, exc)
        return None


def upsert_prova(prova_id: Optional[int], descricao: str, modelo_id: str, gabarito_csv: str) -> Optional[int]:
    """INSERT ou UPDATE em cadastro_prova. Retorna id da prova ou None em caso de erro."""
    try:
        with _get_conn() as conn:
            cursor = conn.cursor()
            if prova_id is not None:
                cursor.execute(
                    "UPDATE cadastro_prova SET descricao=?, modelo_id=?, gabarito=? WHERE id=?",
                    descricao, modelo_id, gabarito_csv, prova_id,
                )
                conn.commit()
                logger.info("Prova '%s' atualizada", prova_id)
                return prova_id
            else:
                cursor.execute(
                    "INSERT INTO cadastro_prova (descricao, modelo_id, gabarito) OUTPUT INSERTED.id VALUES (?, ?, ?)",
                    descricao, modelo_id, gabarito_csv,
                )
                row = cursor.fetchone()
                conn.commit()
                new_id = int(row[0])
                logger.info("Prova criada com id=%s", new_id)
                return new_id
    except Exception as exc:
        logger.warning("upsert_prova falhou: %s", exc)
        return None


def deletar_prova(prova_id: int) -> bool:
    """Remove prova do banco. Retorna True se deletada."""
    try:
        with _get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM cadastro_prova WHERE id = ?", prova_id)
            deleted = cursor.rowcount
            conn.commit()
            if deleted:
                logger.info("Prova '%s' deletada", prova_id)
                return True
            logger.warning("deletar_prova: '%s' não encontrada", prova_id)
            return False
    except Exception as exc:
        logger.warning("deletar_prova('%s') falhou: %s", prova_id, exc)
        return False


# ── Grid de máscara ───────────────────────────────────────────────────────────

def salvar_grid_modelo(modelo_id: str, grid_points: dict) -> bool:
    """
    Salva posições absolutas de linhas/colunas do KMeans em modelo_grid.
    Só salva se a tabela ainda não tiver dados para esse modelo.
    grid_points = {"image_w": int, "image_h": int, "panels": [{"painel": 0, "col_centers": [...], "row_centers": [...]}]}
    """
    panels = grid_points.get("panels", [])
    if not panels:
        return False
    try:
        with _get_conn() as conn:
            cursor = conn.cursor()

            # Só salva se ainda não há dados para esse modelo
            cursor.execute("SELECT COUNT(1) FROM modelo_grid WHERE modelo_id = ?", modelo_id)
            if cursor.fetchone()[0] > 0:
                logger.info("Grid modelo '%s' já existe no DB — ignorando", modelo_id)
                return False

            ALTERNATIVES = ["A", "B", "C", "D", "E", "F", "G", "H", "I", "J"]

            rows_to_insert = []
            for panel in panels:
                pi = int(panel["painel"])
                col_centers = panel["col_centers"]  # [idx, A, B, ...]
                row_centers = panel["row_centers"]  # [Q1..Q25]

                for ci, cx in enumerate(col_centers):
                    label = "idx" if ci == 0 else ALTERNATIVES[ci - 1]
                    # indice global de coluna: painel*n_cols + ci
                    indice = pi * len(col_centers) + ci
                    rows_to_insert.append((modelo_id, "V", indice, float(cx), label))

                for ri, ry in enumerate(row_centers):
                    label = f"Q{pi * len(row_centers) + ri + 1}"
                    # indice global de linha = questão global 0-based
                    indice = pi * len(row_centers) + ri
                    rows_to_insert.append((modelo_id, "H", indice, float(ry), label))

            cursor.executemany(
                "INSERT INTO modelo_grid (modelo_id, tipo, indice, posicao_px, label) "
                "VALUES (?, ?, ?, ?, ?)",
                rows_to_insert,
            )
            conn.commit()
            logger.info("Grid modelo '%s' salvo: %d pontos", modelo_id, len(rows_to_insert))
            return True
    except Exception as exc:
        logger.warning("salvar_grid_modelo('%s') falhou: %s", modelo_id, exc)
        return False


def buscar_grid_modelo(modelo_id: str) -> Optional[dict]:
    """Retorna grid_points do banco para o modelo, ou None se não existir."""
    try:
        with _get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT COUNT(1) FROM modelo_grid WHERE modelo_id = ?", modelo_id
            )
            if cursor.fetchone()[0] == 0:
                return None
            cursor.execute(
                "SELECT tipo, indice, posicao_px, label "
                "FROM modelo_grid WHERE modelo_id = ? ORDER BY tipo, indice",
                modelo_id,
            )
            rows = cursor.fetchall()
            if not rows:
                return None
            horizontal = []
            vertical = []
            for tipo, indice, posicao_px, label in rows:
                entry = {"indice": indice, "posicao_px": float(posicao_px), "label": label}
                if tipo == "H":
                    horizontal.append(entry)
                else:
                    vertical.append(entry)
            return {"horizontal": horizontal, "vertical": vertical}
    except Exception as exc:
        logger.warning("buscar_grid_modelo('%s') falhou: %s", modelo_id, exc)
        return None


# ── Salvar resultado ───────────────────────────────────────────────────────────

def salvar_resultado(
    aluno_ra: str,
    modelo_id: str,
    prova_id: int,
    acertos: int,
    erros: int,
    resultado_json: dict,
) -> bool:
    """
    Insere linha em gabaritos_processados.
    resultado_json é serializado como NVARCHAR(MAX).
    Retorna True se inserção bem-sucedida.
    """
    try:
        with _get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO gabaritos_processados
                    (ALUNO, modelo_id, prova_id, acertos, erros, resultado)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                aluno_ra,
                modelo_id,
                prova_id,
                acertos,
                erros,
                json.dumps(resultado_json, ensure_ascii=False),
            )
            conn.commit()
            logger.info(
                "Resultado salvo: ALUNO=%s prova=%s modelo=%s acertos=%d erros=%d",
                aluno_ra, prova_id, modelo_id, acertos, erros,
            )
            return True
    except Exception as exc:
        logger.warning("salvar_resultado falhou: %s", exc)
        return False
