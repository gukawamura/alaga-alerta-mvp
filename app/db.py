"""Banco de dados SQLite compartilhado.

Todos os componentes (Big Data, RPA, Visão, robô ESP32, assistente) gravam
e leem por meio da API, nunca direto no arquivo. Isso mantém um único
contrato e permite trocar SQLite por Postgres sem mudar os componentes.
"""
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path

from .config import config

_lock = threading.Lock()

SCHEMA = """
CREATE TABLE IF NOT EXISTS bairros (
    id TEXT PRIMARY KEY,
    nome TEXT NOT NULL,
    zona TEXT NOT NULL,
    lat REAL NOT NULL,
    lon REAL NOT NULL,
    populacao INTEGER NOT NULL,
    sensibilidade REAL NOT NULL DEFAULT 1.0
);

-- Espelho da tabela Ouro de risco por bairro e hora (Big Data).
CREATE TABLE IF NOT EXISTS risco_bairro_hora (
    bairro_id TEXT NOT NULL REFERENCES bairros(id),
    hora TEXT NOT NULL,              -- ISO 8601 UTC, início da hora
    chuva_mm REAL NOT NULL,          -- chuva prevista na hora (mm)
    score REAL NOT NULL,             -- chuva ponderada pela sensibilidade
    nivel TEXT NOT NULL CHECK (nivel IN ('baixo','atencao','alto')),
    fonte TEXT NOT NULL,             -- 'ouro', 'open-meteo', 'simulado'
    PRIMARY KEY (bairro_id, hora)
);

-- Alertas disparados pelo RPA.
CREATE TABLE IF NOT EXISTS alertas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    bairro_id TEXT NOT NULL REFERENCES bairros(id),
    nivel TEXT NOT NULL CHECK (nivel IN ('atencao','alto')),
    mensagem TEXT NOT NULL,
    criado_em TEXT NOT NULL,
    valido_ate TEXT NOT NULL,
    origem TEXT NOT NULL,            -- 'rpa', 'simulado', 'demo'
    canais TEXT NOT NULL DEFAULT ''  -- ex.: 'telegram,whatsapp'
);

-- Ocorrências: boletins do CGE, fotos de cidadãos validadas, sensores.
CREATE TABLE IF NOT EXISTS ocorrencias (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    bairro_id TEXT NOT NULL REFERENCES bairros(id),
    tipo TEXT NOT NULL,              -- rua_alagada, veiculo_submerso, bueiro_entupido
    fonte TEXT NOT NULL,             -- cge, cidadao, sensor
    status TEXT NOT NULL CHECK (status IN ('confirmada','pendente','descartada')),
    confianca REAL,
    criado_em TEXT NOT NULL,
    detalhe TEXT NOT NULL DEFAULT ''
);

-- Leituras do robô (ESP32) com classificação da IA embarcada.
CREATE TABLE IF NOT EXISTS leituras (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sensor_id TEXT NOT NULL,
    bairro_id TEXT NOT NULL REFERENCES bairros(id),
    nivel_cm REAL NOT NULL,
    classificacao TEXT NOT NULL CHECK (classificacao IN ('normal','atencao','perigo')),
    medido_em TEXT NOT NULL,
    recebido_em TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_alertas_bairro ON alertas(bairro_id, criado_em);
CREATE INDEX IF NOT EXISTS idx_ocorr_bairro ON ocorrencias(bairro_id, criado_em);
CREATE INDEX IF NOT EXISTS idx_leituras_bairro ON leituras(bairro_id, medido_em);
CREATE INDEX IF NOT EXISTS idx_risco_hora ON risco_bairro_hora(hora);
"""


def conectar() -> sqlite3.Connection:
    Path(config.DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(config.DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


@contextmanager
def transacao(*, imediata: bool = False):
    with _lock:
        conn = conectar()
        try:
            if imediata:
                conn.execute("BEGIN IMMEDIATE")
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()


def criar_schema() -> None:
    with transacao() as conn:
        conn.executescript(SCHEMA)


def consultar(sql: str, params: tuple = ()) -> list[dict]:
    with transacao() as conn:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]


def banco_vazio() -> bool:
    return consultar("SELECT COUNT(*) AS n FROM bairros")[0]["n"] == 0
