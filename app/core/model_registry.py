from __future__ import annotations

import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class ModelConfig:
    n_panels: int = 4
    n_alternativas: int = 5
    n_questoes: int = 0
    grid_top_ratio: float = 0.35
    grid_bottom_ratio: float = 0.99
    grid_left_ratio: float = 0.02
    grid_right_ratio: float = 0.98
    fill_threshold_empty: float = 0.12
    fill_threshold_filled: float = 0.40
    disable_auto_top: bool = False
    descricao: str = ""
    output_width: int | None = None
    output_height: int | None = None
    gabarito_path: str | None = None
    ra_n_digits: int | None = None
    ra_fill_threshold_empty: float = 0.05
    ra_fill_threshold_filled: float = 0.10
    ra_region: dict | None = None

    def validate(self) -> list[str]:
        errors = []
        if self.n_panels < 1 or self.n_panels > 10:
            errors.append("n_panels deve estar entre 1 e 10")
        if not (0.0 <= self.grid_top_ratio < self.grid_bottom_ratio <= 1.0):
            errors.append("grid_top_ratio deve estar entre 0.0 e grid_bottom_ratio")
        if not (0.0 <= self.grid_left_ratio < self.grid_right_ratio <= 1.0):
            errors.append("grid_left_ratio deve estar entre 0.0 e grid_right_ratio")
        if not (0.0 <= self.fill_threshold_empty <= self.fill_threshold_filled <= 1.0):
            errors.append("fill_threshold_empty deve ser <= fill_threshold_filled")
        return errors


def get_model_config(modelo: str | None) -> ModelConfig:
    """Carrega ModelConfig do banco. Retorna defaults se modelo não informado ou não encontrado."""
    if not modelo:
        return ModelConfig()

    try:
        from app.services.db_service import buscar_modelo_gabarito
        db = buscar_modelo_gabarito(modelo)
        if db is None:
            raise ValueError(f"Modelo '{modelo}' não encontrado no banco de dados")

        ra_region = None
        if db.ra_region_top is not None:
            ra_region = {
                "top": db.ra_region_top,
                "bottom": db.ra_region_bottom,
                "left": db.ra_region_left,
                "right": db.ra_region_right,
            }

        cfg = ModelConfig(
            n_panels=db.n_panels,
            n_alternativas=db.n_alternativas,
            n_questoes=db.n_questoes,
            grid_top_ratio=db.grid_top_ratio,
            grid_bottom_ratio=db.grid_bottom_ratio,
            grid_left_ratio=db.grid_left_ratio,
            grid_right_ratio=db.grid_right_ratio,
            fill_threshold_empty=db.fill_threshold_empty,
            fill_threshold_filled=db.fill_threshold_filled,
            disable_auto_top=db.disable_auto_top,
            descricao=db.descricao,
            ra_n_digits=db.ra_n_digits,
            ra_fill_threshold_empty=db.ra_fill_threshold_empty or 0.05,
            ra_fill_threshold_filled=db.ra_fill_threshold_filled or 0.10,
            ra_region=ra_region,
        )

        errors = cfg.validate()
        if errors:
            logger.warning("Modelo '%s' tem problemas: %s", modelo, "; ".join(errors))

        return cfg

    except ValueError:
        raise
    except Exception as exc:
        logger.error("get_model_config('%s') falhou: %s", modelo, exc)
        raise ValueError(f"Erro ao carregar modelo '{modelo}': {exc}")


def list_models() -> dict[str, str]:
    """Retorna {id: descricao} de todos os modelos no banco."""
    try:
        from app.services.db_service import listar_modelos
        return listar_modelos()
    except Exception as exc:
        logger.error("list_models falhou: %s", exc)
        return {}


def get_model_details(modelo: str) -> dict | None:
    """Retorna todos os campos de um modelo como dict, ou None se não encontrado."""
    try:
        from app.services.db_service import obter_modelo_detalhes
        return obter_modelo_detalhes(modelo)
    except Exception as exc:
        logger.error("get_model_details('%s') falhou: %s", modelo, exc)
        return None


def save_model_config(modelo: str, config: ModelConfig) -> dict:
    """Persiste ModelConfig no banco. Retorna dict com 'sucesso', 'erros', 'avisos'."""
    result: dict = {"sucesso": False, "erros": [], "avisos": [], "modelo": modelo}

    errors = config.validate()
    if errors:
        result["avisos"] = errors
        logger.warning("Modelo '%s' contém avisos: %s", modelo, "; ".join(errors))

    dados = {
        "descricao": config.descricao,
        "n_panels": config.n_panels,
        "grid_top_ratio": config.grid_top_ratio,
        "grid_bottom_ratio": config.grid_bottom_ratio,
        "grid_left_ratio": config.grid_left_ratio,
        "grid_right_ratio": config.grid_right_ratio,
        "fill_threshold_empty": config.fill_threshold_empty,
        "fill_threshold_filled": config.fill_threshold_filled,
        "disable_auto_top": config.disable_auto_top,
        "ra_n_digits": config.ra_n_digits,
        "ra_fill_threshold_empty": config.ra_fill_threshold_empty,
        "ra_fill_threshold_filled": config.ra_fill_threshold_filled,
        "ra_region_top": config.ra_region.get("top") if config.ra_region else None,
        "ra_region_bottom": config.ra_region.get("bottom") if config.ra_region else None,
        "ra_region_left": config.ra_region.get("left") if config.ra_region else None,
        "ra_region_right": config.ra_region.get("right") if config.ra_region else None,
    }

    try:
        from app.services.db_service import upsert_modelo_gabarito
        ok = upsert_modelo_gabarito(modelo, dados)
        result["sucesso"] = ok
        if not ok:
            result["erros"].append("Falha ao salvar no banco de dados")
    except Exception as exc:
        result["erros"].append(str(exc))
        logger.error("save_model_config('%s') falhou: %s", modelo, exc)

    return result


def delete_model_config(modelo: str) -> dict:
    """Remove modelo do banco."""
    result: dict = {"sucesso": False, "modelo": modelo}

    try:
        from app.services.db_service import deletar_modelo_gabarito
        ok = deletar_modelo_gabarito(modelo)
        if ok:
            result["sucesso"] = True
        else:
            result["erro"] = f"Modelo '{modelo}' não encontrado"
    except Exception as exc:
        result["erro"] = str(exc)
        logger.error("delete_model_config('%s') falhou: %s", modelo, exc)

    return result
