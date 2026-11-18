"""Dados simulados com geração documentada (ver docs/DADOS_SIMULADOS.md).

Gera um histórico de janeiro de 2026 para os bairros monitorados e uma
janela "calma" ao redor do horário atual. A semente é fixa (2026), então o
mesmo histórico é gerado em qualquer máquina: os indicadores do pitch são
reprodutíveis.
"""
import csv
import random
from datetime import datetime, timedelta, timezone

from . import db
from .config import BASE_DIR
from .risco import LIMIAR_ALTO, hora_cheia, iso, nivel_por_score, agora

SEMENTE = 2026
INICIO_HISTORICO = datetime(2026, 1, 1, tzinfo=timezone.utc)
DIAS_HISTORICO = 31
LIMIAR_OCORRENCIA = 24.0  # score real que gera alagamento registrado


def carregar_bairros() -> list[dict]:
    caminho = BASE_DIR / "data" / "bairros.csv"
    with caminho.open(encoding="utf-8") as f:
        linhas = list(csv.DictReader(f))
    for b in linhas:
        b["lat"] = float(b["lat"])
        b["lon"] = float(b["lon"])
        b["populacao"] = int(b["populacao"])
        b["sensibilidade"] = float(b["sensibilidade"])
    return linhas


def inserir_bairros(conn, bairros: list[dict]) -> None:
    conn.executemany(
        "INSERT INTO bairros VALUES (:id,:nome,:zona,:lat,:lon,:populacao,:sensibilidade)"
        " ON CONFLICT(id) DO NOTHING",
        bairros,
    )


def gerar_historico(conn, bairros: list[dict]) -> dict:
    rng = random.Random(SEMENTE)
    zonas = sorted({b["zona"] for b in bairros})
    n_risco = n_alertas = n_ocorr = 0

    for d in range(DIAS_HISTORICO):
        dia = INICIO_HISTORICO + timedelta(days=d)
        tem_temporal = rng.random() < 0.45
        # Temporais de verão em SP: fim de tarde (14h a 18h locais = 17h a 21h UTC).
        inicio_utc = rng.randint(17, 21)
        duracao = rng.randint(1, 3)
        pico = rng.uniform(6, 34)
        mult_zona = {z: rng.uniform(0.35, 1.3) for z in zonas}

        for b in bairros:
            primeira_alto = None
            primeira_ocorr = None
            for h in range(24):
                hora = dia + timedelta(hours=h)
                chuva = rng.uniform(0, 1.5) if rng.random() < 0.15 else 0.0
                if tem_temporal and inicio_utc <= h < inicio_utc + duracao:
                    forma = 1.0 if h == inicio_utc else 0.6
                    chuva = max(chuva, pico * mult_zona[b["zona"]] * forma * rng.uniform(0.85, 1.15))
                score = chuva * b["sensibilidade"]
                nivel = nivel_por_score(score)
                conn.execute(
                    "INSERT OR REPLACE INTO risco_bairro_hora VALUES (?,?,?,?,?,?)",
                    (b["id"], iso(hora), round(chuva, 1), round(score, 1), nivel, "simulado"),
                )
                n_risco += 1
                if nivel == "alto" and primeira_alto is None:
                    primeira_alto = hora
                # Chuva observada = prevista com erro multiplicativo (~30%).
                real = score * rng.lognormvariate(0, 0.3)
                if real >= LIMIAR_OCORRENCIA and primeira_ocorr is None:
                    primeira_ocorr = hora + timedelta(minutes=rng.randint(5, 45))

            if primeira_alto is not None:
                criado = primeira_alto - timedelta(minutes=rng.randint(30, 90))
                conn.execute(
                    "INSERT INTO alertas (bairro_id,nivel,mensagem,criado_em,valido_ate,origem,canais)"
                    " VALUES (?,?,?,?,?,?,?)",
                    (
                        b["id"], "alto",
                        f"Risco alto de alagamento em {b['nome']} nas próximas horas.",
                        iso(criado), iso(primeira_alto + timedelta(hours=3)),
                        "simulado", "telegram",
                    ),
                )
                n_alertas += 1
            if primeira_ocorr is not None:
                fonte = "cidadao" if rng.random() < 0.25 else "cge"
                conn.execute(
                    "INSERT INTO ocorrencias (bairro_id,tipo,fonte,status,confianca,criado_em,detalhe)"
                    " VALUES (?,?,?,?,?,?,?)",
                    (
                        b["id"], "rua_alagada", fonte, "confirmada",
                        round(rng.uniform(0.65, 0.95), 2) if fonte == "cidadao" else None,
                        iso(primeira_ocorr), "histórico simulado",
                    ),
                )
                n_ocorr += 1
    return {"risco": n_risco, "alertas": n_alertas, "ocorrencias": n_ocorr}


def gerar_janela_calma(conn, bairros: list[dict], referencia: datetime | None = None) -> int:
    """Previsão sem chuva relevante de 3h atrás até 12h à frente."""
    rng = random.Random(SEMENTE + 1)
    base = hora_cheia(referencia or agora())
    n = 0
    for b in bairros:
        for h in range(-3, 13):
            hora = base + timedelta(hours=h)
            chuva = round(rng.uniform(0, 2.5), 1)
            score = round(chuva * b["sensibilidade"], 1)
            conn.execute(
                "INSERT OR REPLACE INTO risco_bairro_hora VALUES (?,?,?,?,?,?)",
                (b["id"], iso(hora), chuva, score, nivel_por_score(score), "simulado"),
            )
            n += 1
    return n


def popular(forcar: bool = False) -> dict:
    db.criar_schema()
    if not forcar and not db.banco_vazio():
        return {"populado": False}
    bairros = carregar_bairros()
    with db.transacao() as conn:
        if forcar:
            for tabela in ("leituras", "ocorrencias", "alertas", "risco_bairro_hora", "bairros"):
                conn.execute(f"DELETE FROM {tabela}")
        inserir_bairros(conn, bairros)
        totais = gerar_historico(conn, bairros)
        totais["janela_calma"] = gerar_janela_calma(conn, bairros)
    totais["populado"] = True
    return totais


assert LIMIAR_ALTO < LIMIAR_OCORRENCIA  # alerta precisa vir antes da ocorrência
