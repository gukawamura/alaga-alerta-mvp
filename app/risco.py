"""Regras de risco por bairro.

O risco base vem da tabela Ouro (chuva prevista x sensibilidade do bairro).
Sobre ele, a API aplica dois sinais de campo que só ela vê juntos:
a leitura mais recente do sensor no bueiro e as ocorrências confirmadas.
"""
from datetime import datetime, timedelta, timezone

# Limiares do score (mm/h ponderados pela sensibilidade do bairro).
# Referência: chuva acima de ~10 mm/h já é "moderada a forte" e acima de
# ~20 mm/h costuma gerar alagamento em pontos críticos de drenagem.
LIMIAR_ATENCAO = 10.0
LIMIAR_ALTO = 20.0

ORDEM = {"baixo": 0, "atencao": 1, "alto": 2}

ORIENTACAO = {
    "baixo": "Sem risco de alagamento previsto para as próximas horas.",
    "atencao": (
        "Pode alagar nas próximas horas. Evite ruas que costumam encher e "
        "acompanhe os avisos antes de sair."
    ),
    "alto": (
        "Risco alto de alagamento. Se puder, adie a saída. Nunca atravesse "
        "rua alagada a pé ou de carro. Procure um lugar alto e seguro."
    ),
}

TIPOS_QUE_ALAGAM = {"rua_alagada", "veiculo_submerso"}


def agora() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat()


def hora_cheia(dt: datetime) -> datetime:
    return dt.astimezone(timezone.utc).replace(minute=0, second=0, microsecond=0)


def parse(valor: str) -> datetime:
    dt = datetime.fromisoformat(valor.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def nivel_por_score(score: float) -> str:
    if score >= LIMIAR_ALTO:
        return "alto"
    if score >= LIMIAR_ATENCAO:
        return "atencao"
    return "baixo"


def maior(a: str, b: str) -> str:
    return a if ORDEM[a] >= ORDEM[b] else b


def combinar(
    previsao: list[dict],
    leitura: dict | None,
    ocorrencias: list[dict],
    referencia: datetime | None = None,
    nivel_alerta_rpa: str | None = None,
) -> dict:
    """Combina previsão das próximas 3 horas, sensor, ocorrências e alerta ativo do RPA.

    Retorna nível final, motivos em linguagem simples e a orientação.
    """
    ref = referencia or agora()
    nivel = "baixo"
    motivos: list[str] = []

    if previsao:
        pior = max(previsao, key=lambda r: ORDEM[r["nivel"]])
        if ORDEM[pior["nivel"]] > 0:
            hora_local = parse(pior["hora"]).astimezone(
                timezone(timedelta(hours=-3))
            )
            motivos.append(
                f"Previsão de {pior['chuva_mm']:.0f} mm de chuva por volta das "
                f"{hora_local:%H}h"
            )
        nivel = maior(nivel, pior["nivel"])

    if leitura and ref - timedelta(minutes=60) <= parse(leitura["medido_em"]) <= ref:
        if leitura["classificacao"] == "perigo":
            nivel = "alto"
            motivos.append(f"Sensor no bueiro marca {leitura['nivel_cm']:.0f} cm (perigo)")
        elif leitura["classificacao"] == "atencao":
            nivel = maior(nivel, "atencao")
            motivos.append(f"Sensor no bueiro marca {leitura['nivel_cm']:.0f} cm (atenção)")

    confirmadas = [
        o for o in ocorrencias
        if o["status"] == "confirmada" and ref - timedelta(hours=2) <= parse(o["criado_em"]) <= ref
    ]
    if any(o["tipo"] in TIPOS_QUE_ALAGAM for o in confirmadas):
        nivel = "alto"
        motivos.append("Alagamento confirmado no bairro nas últimas 2 horas")
    elif confirmadas:
        nivel = maior(nivel, "atencao")
        motivos.append("Bueiro entupido relatado no bairro")

    if nivel_alerta_rpa:
        nivel = maior(nivel, nivel_alerta_rpa)
        nivel_texto = "alto" if nivel_alerta_rpa == "alto" else "de atenção"
        motivos.append(f"Alerta emitido pela automação: risco {nivel_texto}")

    if not previsao and nivel == "baixo":
        return {
            "nivel": "indisponivel",
            "motivos": motivos,
            "orientacao": "Não há previsão disponível para este bairro. Acompanhe os avisos da Defesa Civil.",
        }
    return {"nivel": nivel, "motivos": motivos, "orientacao": ORIENTACAO[nivel]}
