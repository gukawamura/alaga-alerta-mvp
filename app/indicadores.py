"""Indicadores de impacto calculados a partir dos dados (não digitados).

Mesmas definições do documento do pitch:
- antecedência média: minutos entre o alerta e a 1ª ocorrência confirmada
  de alagamento no mesmo bairro, dentro da validade do alerta;
- taxa de acerto: alertas seguidos de ocorrência confirmada / total;
- cobertura: ocorrências confirmadas precedidas de alerta / total;
- população em bairros monitorados (IBGE, via Big Data).
"""
from . import db
from .config import config

FONTES_INDICADORES = """
WITH alertas_visiveis AS (
    SELECT * FROM alertas WHERE ? OR origem NOT IN ('demo','simulado')
), ocorrencias_visiveis AS (
    SELECT * FROM ocorrencias WHERE ? OR (detalhe NOT LIKE '%demonstração%' AND detalhe!='histórico simulado')
)
"""

SQL_ACERTOS = """
SELECT a.id, a.criado_em,
       (SELECT MIN(o.criado_em) FROM ocorrencias_visiveis o
         WHERE o.bairro_id = a.bairro_id
           AND o.status = 'confirmada'
           AND o.tipo IN ('rua_alagada','veiculo_submerso')
           AND o.criado_em >= a.criado_em
           AND o.criado_em <= a.valido_ate) AS primeira_ocorrencia
FROM alertas_visiveis a
"""

SQL_COBERTURA = """
SELECT o.id,
       EXISTS (SELECT 1 FROM alertas_visiveis a
                WHERE a.bairro_id = o.bairro_id
                  AND a.criado_em <= o.criado_em
                  AND a.valido_ate >= o.criado_em) AS teve_alerta
FROM ocorrencias_visiveis o
WHERE o.status = 'confirmada' AND o.tipo IN ('rua_alagada','veiculo_submerso')
"""


def _minutos(inicio: str, fim: str) -> float:
    from .risco import parse
    return (parse(fim) - parse(inicio)).total_seconds() / 60


def calcular() -> dict:
    filtros = (config.DADOS_DEMO, config.DADOS_DEMO)
    acertos = db.consultar(FONTES_INDICADORES + SQL_ACERTOS, filtros)
    total_alertas = len(acertos)
    com_ocorrencia = [a for a in acertos if a["primeira_ocorrencia"]]
    antecedencias = [_minutos(a["criado_em"], a["primeira_ocorrencia"]) for a in com_ocorrencia]

    cobertura = db.consultar(FONTES_INDICADORES + SQL_COBERTURA, filtros)
    total_ocorr = len(cobertura)
    cobertas = sum(1 for c in cobertura if c["teve_alerta"])

    pop = db.consultar("SELECT COALESCE(SUM(populacao),0) AS p, COUNT(*) AS n FROM bairros")[0]
    cidadao = db.consultar(
        FONTES_INDICADORES +
        "SELECT COUNT(*) AS n FROM ocorrencias_visiveis WHERE fonte='cidadao' AND status='confirmada'", filtros
    )[0]["n"]
    perigo = db.consultar(
        "SELECT COUNT(*) AS n FROM leituras WHERE classificacao='perigo' AND (? OR sensor_id NOT LIKE 'demo-%')",
        (config.DADOS_DEMO,),
    )[0]["n"]
    periodo = db.consultar(
        FONTES_INDICADORES + "SELECT MIN(criado_em) AS ini, MAX(criado_em) AS fim FROM alertas_visiveis", filtros
    )[0]
    simulados = db.consultar(
        FONTES_INDICADORES + "SELECT COUNT(*) AS n FROM alertas_visiveis WHERE origem IN ('simulado','demo')", filtros
    )[0]["n"]

    def pct(a: int, b: int) -> float | None:
        return round(100 * a / b, 1) if b else None

    return {
        "antecedencia_media_min": round(sum(antecedencias) / len(antecedencias), 1) if antecedencias else None,
        "taxa_acerto_pct": pct(len(com_ocorrencia), total_alertas),
        "cobertura_ocorrencias_pct": pct(cobertas, total_ocorr),
        "alertas_total": total_alertas,
        "alertas_com_ocorrencia": len(com_ocorrencia),
        "ocorrencias_confirmadas": total_ocorr,
        "ocorrencias_com_alerta_antes": cobertas,
        "populacao_monitorada": pop["p"],
        "bairros_monitorados": pop["n"],
        "ocorrencias_cidadaos_confirmadas": cidadao,
        "leituras_perigo": perigo,
        "periodo": {"inicio": periodo["ini"], "fim": periodo["fim"]},
        "inclui_dados_simulados": simulados > 0,
    }
