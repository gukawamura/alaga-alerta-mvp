"""Publica na API um CSV exportado da tabela Ouro do Databricks.

CSV nativo da Ouro: bairro_id,data_hora,precipitacao_mm,nivel_risco.
CSV no contrato da API (cabeçalho obrigatório):
  bairro_id,hora,chuva_mm[,nivel]
  - bairro_id: o mesmo id usado em GET /bairros (ex.: vila-formosa)
  - hora: ISO 8601 (ex.: 2026-11-19T18:00:00-03:00 ou 2026-11-19T21:00:00Z)
  - chuva_mm: chuva prevista na hora
  - nivel (opcional): baixo | atencao | alto. Se vazio, a API calcula.

Uso:
  python scripts/importar_ouro.py --url https://SEU-MVP --chave SUA_CHAVE --csv ouro_risco.csv
"""
import argparse
import csv
import os
from datetime import datetime, timedelta, timezone

import httpx

BAIRROS_OURO = {
    "SP001": "lapa",
    "SP002": "vila-maria",
    "SP003": "jaguare",
    "SP004": "ipiranga",
    "SP005": "vila-prudente",
    "SP006": "santo-amaro",
    "SP007": "jardim-angela",
    "SP008": "penha",
    "SP009": "pinheiros",
    "SP010": "butanta",
}
NIVEIS_OURO = {"normal": "baixo", "atencao": "atencao", "alto": "alto", "critico": "alto"}
# A coleta atual do Databricks usa o horário local de São Paulo (UTC−03 em 2026).
FUSO_OURO = timezone(timedelta(hours=-3))


def ler_csv(caminho: str) -> list[dict]:
    with open(caminho, encoding="utf-8-sig") as f:
        leitor = csv.DictReader(f)
        campos = set(leitor.fieldnames or [])
        formato_ouro = {"bairro_id", "data_hora", "precipitacao_mm", "nivel_risco"} <= campos
        if not formato_ouro and not {"bairro_id", "hora", "chuva_mm"} <= campos:
            raise SystemExit("CSV sem o cabeçalho da tabela Ouro ou do contrato da API.")
        linhas = []
        for linha in leitor:
            try:
                bairro = (linha["bairro_id"] or "").strip()
                if formato_ouro:
                    hora = datetime.fromisoformat((linha["data_hora"] or "").strip())
                    if hora.tzinfo is None:
                        hora = hora.replace(tzinfo=FUSO_OURO)
                    item = {
                        "bairro_id": BAIRROS_OURO[bairro],
                        "hora": hora.isoformat(),
                        "chuva_mm": float(linha["precipitacao_mm"] or ""),
                        "nivel": NIVEIS_OURO[(linha["nivel_risco"] or "").strip()],
                    }
                else:
                    item = {"bairro_id": bairro, "hora": (linha["hora"] or "").strip(),
                            "chuva_mm": float(linha["chuva_mm"] or "")}
                    if nivel := (linha.get("nivel") or "").strip():
                        item["nivel"] = nivel
                linhas.append({**item, "fonte": "ouro"})
            except (ValueError, KeyError) as erro:
                raise SystemExit(f"Linha {leitor.line_num} do CSV inválida: {erro}") from erro
    return linhas


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--url", required=True)
    p.add_argument("--chave", default=os.getenv("API_KEY"), help="Chave da API (padrão: variável API_KEY)")
    p.add_argument("--csv", required=True)
    p.add_argument("--vigente", action="store_true", help="Publicar somente a hora atual e as futuras")
    a = p.parse_args()
    if not a.chave:
        p.error("Defina API_KEY no ambiente ou informe --chave.")
    linhas = ler_csv(a.csv)
    if a.vigente:
        inicio = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
        linhas = [linha for linha in linhas if _hora_utc(linha["hora"]) >= inicio]
        if not linhas:
            raise SystemExit("CSV sem previsão vigente. Gere uma exportação atual da Ouro.")
    with httpx.Client(base_url=a.url.rstrip("/"), headers={"X-API-Key": a.chave}, timeout=60) as api:
        for i in range(0, len(linhas), 5000):
            r = api.post("/risco", json=linhas[i:i + 5000])
            if r.status_code >= 400:
                raise SystemExit(f"Erro {r.status_code}: {r.text}")
    print(f"{len(linhas)} linhas da Ouro publicadas")
    return 0


def _hora_utc(valor: str) -> datetime:
    hora = datetime.fromisoformat(valor)
    return hora.astimezone(timezone.utc) if hora.tzinfo else hora.replace(tzinfo=timezone.utc)


if __name__ == "__main__":
    raise SystemExit(main())
