"""Configuração lida de variáveis de ambiente.

Nenhuma credencial fica no código: tudo vem do ambiente (.env local,
GitHub Secrets ou variáveis do provedor de nuvem).
"""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def _env(nome: str, padrao: str = "") -> str:
    return os.environ.get(nome, padrao).strip()


class Config:
    # Banco SQLite compartilhado por todos os componentes (via API).
    DB_PATH: str = _env("DB_PATH", str(BASE_DIR / "data" / "alaga.db"))

    # Chave exigida nas rotas de escrita usadas pelos outros componentes
    # (RPA, Visão, robô ESP32, Big Data). Sem chave definida, as rotas de
    # escrita ficam bloqueadas (falha segura).
    API_KEY: str = _env("API_KEY")

    # Serviços externos opcionais. Vazios = o MVP usa o modo local.
    ASSISTENTE_URL: str = _env("ASSISTENTE_URL")  # LLM da disciplina de GenAI
    VISAO_URL: str = _env("VISAO_URL")  # modelo YOLO da disciplina de Visão
    TIMEOUT_SERVICOS: float = float(_env("TIMEOUT_SERVICOS", "20"))

    # Limiar de confiança para uma detecção virar ocorrência confirmada.
    LIMIAR_CONFIANCA: float = float(_env("LIMIAR_CONFIANCA", "0.60"))

    # Popular o banco com dados simulados documentados quando estiver vazio.
    SEED_AUTOMATICO: bool = _env("SEED_AUTOMATICO", "0") == "1"
    DADOS_DEMO: bool = _env("DADOS_DEMO", "0") == "1"
    FONTES_PUBLICAS: bool = _env("FONTES_PUBLICAS", "1") == "1"
    SIMULAR_BUEIROS: bool = _env("SIMULAR_BUEIROS", "1") == "1"

    # Origens permitidas para CORS (separadas por vírgula). Vazio = só a
    # própria origem do site.
    CORS_ORIGINS: list[str] = [o for o in _env("CORS_ORIGINS").split(",") if o]

    # Limites por IP para rotas públicas (requisições por minuto).
    LIMITE_ASSISTENTE: int = int(_env("LIMITE_ASSISTENTE", "20"))
    LIMITE_FOTOS: int = int(_env("LIMITE_FOTOS", "6"))

    TAMANHO_MAX_FOTO: int = int(_env("TAMANHO_MAX_FOTO_MB", "5")) * 1024 * 1024


config = Config()
