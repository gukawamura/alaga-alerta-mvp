"""Assistente do cidadão.

Se ASSISTENTE_URL estiver configurada, a pergunta vai para o LLM com RAG da
disciplina de Generative AI. Se o serviço não estiver configurado ou falhar,
o MVP responde com uma busca local na base de conhecimento, citando a fonte,
e diz "não consta" quando não encontra resposta. Assim o chat nunca fica
mudo na demonstração.
"""
import json
import re
import unicodedata
from functools import lru_cache

import httpx

from .config import BASE_DIR, config

NAO_CONSTA = (
    "Não consta na minha base de orientações. Em emergência, ligue 199 "
    "(Defesa Civil) ou 193 (Bombeiros)."
)

STOPWORDS = {
    "a", "o", "e", "de", "da", "do", "das", "dos", "um", "uma", "em", "no", "na",
    "nos", "nas", "que", "se", "meu", "minha", "eu", "para", "pra", "por", "com",
    "como", "faco", "fazer", "o que", "qual", "quais", "ou", "ao", "os", "as", "ja",
    "esta", "essa", "esse", "isso", "tem", "ter", "e", "ficar", "fica", "sim", "nao",
}

_PII = [
    (re.compile(r"\b\d{3}\.?\d{3}\.?\d{3}-?\d{2}\b"), "[cpf removido]"),
    (re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+"), "[email removido]"),
    (re.compile(r"(?:\+?55\s?)?\(?\d{2}\)?\s?9?\d{4}[-\s]?\d{4}\b"), "[telefone removido]"),
]


def remover_dados_pessoais(texto: str) -> str:
    """LGPD: nenhum dado pessoal segue para o modelo nem para logs."""
    for padrao, troca in _PII:
        texto = padrao.sub(troca, texto)
    return texto


def _normalizar(texto: str) -> list[str]:
    sem_acento = unicodedata.normalize("NFKD", texto.lower())
    sem_acento = "".join(c for c in sem_acento if not unicodedata.combining(c))
    tokens = re.findall(r"[a-z0-9]+", sem_acento)
    return [t for t in tokens if t not in STOPWORDS and len(t) > 1]


@lru_cache(maxsize=1)
def carregar_base() -> list[dict]:
    caminho = BASE_DIR / "data" / "base_conhecimento.json"
    base = json.loads(caminho.read_text(encoding="utf-8"))
    for item in base:
        item["_tokens"] = set(_normalizar(item["pergunta"])) | set(item["palavras"])
    return base


def responder_local(pergunta: str) -> dict:
    tokens = set(_normalizar(pergunta))
    if not tokens:
        return {"resposta": NAO_CONSTA, "fontes": [], "modo": "local", "consta": False}
    melhor, melhor_score = None, 0.0
    for item in carregar_base():
        comuns = tokens & item["_tokens"]
        score = len(comuns) / len(tokens)
        if score > melhor_score:
            melhor, melhor_score = item, score
    # Limiar: ao menos 2 termos em comum, ou 1 termo numa pergunta curta.
    termos = round(melhor_score * len(tokens)) if melhor else 0
    if melhor and (termos >= 2 or (termos == 1 and len(tokens) <= 2)):
        return {
            "resposta": melhor["resposta"],
            "fontes": [melhor["fonte"]],
            "modo": "local",
            "consta": True,
        }
    return {"resposta": NAO_CONSTA, "fontes": [], "modo": "local", "consta": False}


def responder(pergunta: str) -> dict:
    pergunta = remover_dados_pessoais(pergunta.strip())[:500]
    if config.ASSISTENTE_URL:
        try:
            r = httpx.post(
                config.ASSISTENTE_URL,
                json={"pergunta": pergunta},
                timeout=config.TIMEOUT_SERVICOS,
            )
            r.raise_for_status()
            dados = r.json()
            fontes = dados.get("fontes") or ([dados["fonte"]] if dados.get("fonte") else [])
            return {
                "resposta": str(dados.get("resposta", NAO_CONSTA)),
                "fontes": [str(f) for f in fontes],
                "modo": "llm",
                "consta": bool(dados.get("consta", not dados.get("recusa", False))),
            }
        except Exception:
            # Degrada com elegância: segue com a base local.
            resposta = responder_local(pergunta)
            resposta["modo"] = "local (LLM indisponível)"
            return resposta
    return responder_local(pergunta)
