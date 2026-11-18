"""Roteiro de demonstração de ponta a ponta (para gravar os vídeos).

Faz, pela API e com a X-API-Key, exatamente o que os componentes reais
fazem, na ordem do pitch:
  1. Big Data publica previsão de chuva forte para a zona leste
  2. RPA dispara o alerta para Vila Formosa
  3. Robô no bueiro envia leitura "perigo"
  4. Visão registra foto confirmada de rua alagada na Penha
  5. RPA registra o boletim do CGE

Quando os componentes reais estiverem integrados, cada passo pode ser
substituído pelo componente de verdade. Use --passo para rodar só um passo
e --calmo para voltar o mapa ao estado sem chuva.

Uso:
  python scripts/simular_evento.py --url https://SEU-MVP --chave SUA_CHAVE
  python scripts/simular_evento.py --url http://localhost:8000 --chave dev --pausa 8
  python scripts/simular_evento.py --url ... --chave ... --calmo
"""
import argparse
import sys
import time
from datetime import datetime, timedelta, timezone

import httpx

BAIRROS_TEMPORAL = {"vila-formosa": 30.0, "penha": 26.0, "aricanduva": 24.0, "mooca": 12.0}


def hora_cheia(dt: datetime) -> datetime:
    return dt.replace(minute=0, second=0, microsecond=0)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--url", required=True, help="URL base do MVP, sem barra no final")
    p.add_argument("--chave", required=True, help="Valor de API_KEY do servidor")
    p.add_argument("--pausa", type=float, default=5.0, help="Segundos entre os passos")
    p.add_argument("--passo", type=int, choices=range(1, 6), help="Rodar só um passo")
    p.add_argument("--calmo", action="store_true", help="Zerar a chuva prevista (volta ao mapa calmo)")
    p.add_argument("--painel", action="store_true", help="Publicar exemplos de alertas e leituras de bueiros")
    a = p.parse_args()

    cli = httpx.Client(base_url=a.url.rstrip("/"), headers={"X-API-Key": a.chave}, timeout=30)
    agora = datetime.now(timezone.utc)
    base = hora_cheia(agora)

    def enviar(metodo: str, rota: str, json) -> dict:
        r = cli.request(metodo, rota, json=json)
        if r.status_code >= 400:
            print(f"  ERRO {r.status_code} em {rota}: {r.text}")
            sys.exit(1)
        return r.json()

    if a.painel:
        for bairro, nivel, mensagem in [
            ("vila-formosa", "alto", "Cenário de teste com elevação rápida da água no bueiro."),
            ("penha", "atencao", "Cenário de teste com aumento gradual do nível da água."),
        ]:
            enviar("POST", "/alertas", {
                "bairro_id": bairro, "nivel": nivel, "mensagem": mensagem, "origem": "demo",
            })
        for bairro, cm, classificacao in [
            ("vila-formosa", 42, "perigo"), ("penha", 24, "atencao"), ("aricanduva", 8, "normal"),
        ]:
            enviar("POST", "/leituras", {
                "sensor_id": f"demo-{bairro}", "bairro_id": bairro,
                "nivel_cm": cm, "classificacao": classificacao,
            })
        print("Painel atualizado com 2 alertas e 3 leituras simuladas.")
        return 0

    if a.calmo:
        bairros = [b["id"] for b in cli.get("/bairros").json()]
        linhas = [
            {"bairro_id": b, "hora": (base + timedelta(hours=h)).isoformat(), "chuva_mm": 0.5, "fonte": "demo"}
            for b in bairros for h in range(-1, 6)
        ]
        print(enviar("POST", "/risco", linhas))
        print("Mapa de volta ao estado calmo (alertas e ocorrências antigos expiram sozinhos).")
        return 0

    passos = {
        1: ("Big Data publica previsão de chuva forte na zona leste", lambda: enviar("POST", "/risco", [
            {"bairro_id": b, "hora": (base + timedelta(hours=h)).isoformat(),
             "chuva_mm": mm * (1.0 if h == 1 else 0.5), "fonte": "demo"}
            for b, mm in BAIRROS_TEMPORAL.items() for h in range(0, 3)
        ])),
        2: ("RPA dispara alerta para Vila Formosa", lambda: enviar("POST", "/alertas", {
            "bairro_id": "vila-formosa", "nivel": "alto", "origem": "demo", "canais": "telegram",
            "mensagem": "Risco alto de alagamento na Vila Formosa na próxima hora. Evite a Av. Regente "
                        "Feijó e não atravesse água acima do meio da roda.",
        })),
        3: ("Robô no bueiro envia leitura de perigo", lambda: enviar("POST", "/leituras", {
            "sensor_id": "demo-vila-formosa", "bairro_id": "vila-formosa", "nivel_cm": 42, "classificacao": "perigo",
        })),
        4: ("Visão confirma rua alagada em foto da Penha", lambda: enviar("POST", "/deteccoes", {
            "bairro_id": "penha", "imagem_anonimizada": True, "simulada": True,
            "deteccoes": [{"classe": "rua_alagada", "confianca": 0.87}],
        })),
        5: ("RPA registra boletim do CGE em Aricanduva", lambda: enviar("POST", "/ocorrencias", {
            "bairro_id": "aricanduva", "tipo": "rua_alagada", "fonte": "cge", "status": "confirmada",
            "detalhe": "Ponto de alagamento intransitável (boletim CGE - demonstração)",
        })),
    }
    escolhidos = [a.passo] if a.passo else list(passos)
    for n in escolhidos:
        titulo, acao = passos[n]
        print(f"[{n}/5] {titulo}...")
        print("  ", acao())
        if n != escolhidos[-1]:
            time.sleep(a.pausa)
    print("Pronto. Abra o MVP: o mapa, os alertas, os sensores e as ocorrências já mostram o evento.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
