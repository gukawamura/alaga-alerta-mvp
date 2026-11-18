"""Coleta a previsão horária de chuva do Open-Meteo para cada bairro e
publica na API (POST /risco).

Serve como fonte de previsão real enquanto a tabela Ouro do Big Data não
estiver publicando direto na API. Pode rodar de hora em hora (cron, GitHub
Actions agendado ou o próprio RPA).

Uso:
  python scripts/coletar_previsao.py --url https://SEU-MVP --chave SUA_CHAVE
"""
import argparse
from datetime import datetime, timedelta, timezone

import httpx

OPEN_METEO = "https://api.open-meteo.com/v1/forecast"


def montar_linhas(
    bairro_id: str, dados: dict, horas: int = 12, referencia: datetime | None = None,
) -> list[dict]:
    """Converte a resposta do Open-Meteo em linhas do contrato POST /risco."""
    horarios = dados["hourly"]["time"]
    chuva = dados["hourly"]["precipitation"]
    inicio = (referencia or datetime.now(timezone.utc)).replace(minute=0, second=0, microsecond=0)
    fim = inicio + timedelta(hours=horas)
    linhas = []
    for t, mm in zip(horarios, chuva, strict=True):
        # Pedimos timezone=GMT, então o horário vem em UTC sem sufixo.
        hora = datetime.fromisoformat(t)
        if hora.tzinfo is None:
            hora = hora.replace(tzinfo=timezone.utc)
        if mm is None or not inicio <= hora < fim:
            continue
        linhas.append({
            "bairro_id": bairro_id,
            "hora": hora.isoformat(),
            "chuva_mm": float(mm),
            "fonte": "open-meteo",
        })
    return linhas


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--url", required=True)
    p.add_argument("--chave", required=True)
    p.add_argument("--horas", type=int, default=12)
    a = p.parse_args()

    api = httpx.Client(base_url=a.url.rstrip("/"), headers={"X-API-Key": a.chave}, timeout=30)
    bairros = api.get("/bairros").json()
    total = 0
    with httpx.Client(timeout=30) as om:
        for b in bairros:
            r = om.get(OPEN_METEO, params={
                "latitude": b["lat"], "longitude": b["lon"], "hourly": "precipitation",
                "forecast_days": 2, "timezone": "GMT",
            })
            r.raise_for_status()
            linhas = montar_linhas(b["id"], r.json(), a.horas)
            resp = api.post("/risco", json=linhas)
            resp.raise_for_status()
            total += len(linhas)
            print(f"{b['nome']}: {len(linhas)} horas publicadas")
    print(f"Total: {total} linhas")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
