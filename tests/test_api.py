"""Testes da API central do Alaga Alerta (rodar com: pytest -q)."""
import io
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
sys.path.insert(0, str(RAIZ / "scripts"))

from app import assistente, db, fontes, main  # noqa: E402
from app.config import config  # noqa: E402
from app.risco import agora, hora_cheia  # noqa: E402

CHAVE = "chave-de-teste"
H = {"X-API-Key": CHAVE}
PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 500

@pytest.fixture(autouse=True)
def config_teste(monkeypatch):
    monkeypatch.setattr(config, "FONTES_PUBLICAS", False)
    monkeypatch.setattr(config, "DADOS_DEMO", True)
    monkeypatch.setattr(config, "SEED_AUTOMATICO", True)

@pytest.fixture()
def cliente(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", str(tmp_path / "teste.db"))
    monkeypatch.setattr(config, "API_KEY", CHAVE)
    monkeypatch.setattr(config, "ASSISTENTE_URL", "")
    monkeypatch.setattr(config, "VISAO_URL", "")
    monkeypatch.setattr(config, "SEED_AUTOMATICO", True)
    main._janelas.clear()
    with TestClient(main.app) as c:
        yield c


# ------------------------------------------------------------- básico
def test_health_e_site(cliente):
    assert cliente.get("/health").json()["status"] == "ok"
    r = cliente.get("/")
    assert r.status_code == 200 and "Alaga Alerta" in r.text
    assert "Content-Security-Policy" in r.headers
    assert r.headers["X-Content-Type-Options"] == "nosniff"
    assert cliente.get("/vendor/leaflet/leaflet.js").status_code == 200
    assert cliente.get("/app.js").status_code == 200


def test_documentacao_interativa(cliente):
    r = cliente.get("/docs")
    assert r.status_code == 200 and "Content-Security-Policy" not in r.headers
    assert "/leituras" in cliente.get("/openapi.json").text


def test_metrics(cliente):
    cliente.get("/health")
    corpo = cliente.get("/metrics").text
    assert "alaga_http_requests_total" in corpo and "alaga_http_latency_seconds" in corpo


def test_bairros_carregados(cliente):
    bairros = cliente.get("/bairros").json()
    assert len(bairros) == 22
    assert {"jabaquara", "santo-amaro"} <= {b["id"] for b in bairros}
    assert {"id", "nome", "zona", "lat", "lon", "populacao"} <= set(bairros[0])


def test_estado_inicial_calmo(cliente):
    risco = cliente.get("/risco/agora").json()
    assert len(risco) == 22
    assert all(r["nivel"] == "baixo" for r in risco)
    assert all(not r["sem_previsao"] for r in risco)


def test_risco_sem_previsao_preserva_alerta_do_sensor(cliente):
    with db.transacao() as conn:
        conn.execute("DELETE FROM risco_bairro_hora WHERE bairro_id='penha'")
    risco = next(r for r in cliente.get("/risco/agora").json() if r["bairro_id"] == "penha")
    assert risco["nivel"] == "indisponivel"
    assert risco["sem_previsao"] and risco["chuva_prevista_mm"] is None
    assert risco["fontes_previsao"] == []

    r = cliente.post("/leituras", headers=H, json={
        "sensor_id": "s1", "bairro_id": "penha", "nivel_cm": 45, "classificacao": "perigo",
    })
    assert r.status_code == 201
    risco = next(r for r in cliente.get("/risco/agora").json() if r["bairro_id"] == "penha")
    assert risco["nivel"] == "alto" and risco["sem_previsao"]


def test_banco_existente_recebe_novos_bairros(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", str(tmp_path / "anterior.db"))
    monkeypatch.setattr(config, "API_KEY", CHAVE)
    carregar = main.seed.carregar_bairros
    com_catalogo_anterior = [b for b in carregar() if b["id"] != "jabaquara"]
    with monkeypatch.context() as contexto:
        contexto.setattr(main.seed, "carregar_bairros", lambda: com_catalogo_anterior)
        with TestClient(main.app) as anterior:
            assert all(b["id"] != "jabaquara" for b in anterior.get("/bairros").json())
            alertas = anterior.get("/indicadores").json()["alertas_total"]
            ouro = [{"bairro_id": "penha", "hora": hora_cheia(agora()).isoformat(), "chuva_mm": 12, "fonte": "ouro"}]
            assert anterior.post("/risco", headers=H, json=ouro).status_code == 200
    with TestClient(main.app) as reiniciado:
        assert any(b["id"] == "jabaquara" for b in reiniciado.get("/bairros").json())
        assert reiniciado.get("/indicadores").json()["alertas_total"] == alertas
        assert reiniciado.get("/risco/penha").json()["previsao"][0]["fonte"] == "ouro"


def test_sem_seed_carrega_catalogo_sem_previsao(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", str(tmp_path / "novo.db"))
    monkeypatch.setattr(config, "SEED_AUTOMATICO", False)
    with TestClient(main.app) as c:
        risco = c.get("/risco/agora").json()
        assert len(risco) == 22
        assert all(r["nivel"] == "indisponivel" for r in risco)


def test_modo_real_oculta_registros_demo_sem_apagar(cliente, monkeypatch):
    assert cliente.post("/alertas", headers=H, json={
        "bairro_id": "penha", "nivel": "alto", "mensagem": "Alerta de teste", "origem": "demo",
    }).status_code == 201
    assert cliente.post("/leituras", headers=H, json={
        "bairro_id": "penha", "sensor_id": "demo-penha", "nivel_cm": 42, "classificacao": "perigo",
    }).status_code == 201
    monkeypatch.setattr(config, "DADOS_DEMO", False)
    assert cliente.get("/alertas").json() == cliente.get("/leituras").json() == []
    assert cliente.get("/indicadores").json()["alertas_total"] == 0
    assert all(r["nivel"] == "indisponivel" for r in cliente.get("/risco/agora").json())
    assert db.consultar("SELECT COUNT(*) AS n FROM leituras")[0]["n"] == 1


def test_simulacao_bueiro_responde_a_previsao_sem_gravar(cliente, monkeypatch):
    monkeypatch.setattr(config, "DADOS_DEMO", False)
    monkeypatch.setattr(config, "SIMULAR_BUEIROS", True)
    assert cliente.get("/leituras/simuladas").json() == []
    base = hora_cheia(agora())
    for chuva, esperado in [(0, "normal"), (25, "perigo")]:
        assert cliente.post("/risco", headers=H, json=[{
            "bairro_id": "penha", "hora": base.isoformat(), "chuva_mm": chuva, "fonte": "open-meteo",
        }]).status_code == 200
        leitura, = cliente.get("/leituras/simuladas").json()
        assert leitura["simulada"] and leitura["classificacao"] == esperado
        assert leitura["chuva_prevista_mm"] == chuva
    assert cliente.get("/leituras").json() == []
    assert cliente.get("/indicadores").json()["leituras_perigo"] == 0
    assert cliente.post("/leituras", headers=H, json={
        "sensor_id": "esp32-01", "bairro_id": "penha", "nivel_cm": 12, "classificacao": "normal",
    }).status_code == 201
    assert cliente.get("/leituras/simuladas").json() == []


def test_idap_filtra_validade_area_e_cancelamento():
    ref = datetime.fromisoformat("2026-11-17T19:00:00-03:00")

    def aviso(id_, area, expira="22:00"):
        return f"""<cap:alert><cap:identifier>{id_}</cap:identifier><cap:sender>SEDEC</cap:sender>
        <cap:sent>2026-11-17T18:00:00-03:00</cap:sent><cap:status>Actual</cap:status>
        <cap:scope>Public</cap:scope><cap:msgType>Alert</cap:msgType><cap:info>
        <cap:language>pt-BR</cap:language><cap:expires>2026-11-17T{expira}:00-03:00</cap:expires>
        <cap:senderName>Defesa Civil</cap:senderName><cap:headline>Chuva intensa</cap:headline>
        <cap:area><cap:areaDesc>{area}</cap:areaDesc></cap:area></cap:info></cap:alert>"""

    feed = f"""<feed xmlns="http://www.w3.org/2005/Atom" xmlns:cap="{fontes.CAP[1:-1]}">
        {aviso("1", "São Paulo/SP")} {aviso("2", "São Paulo/SP", "18:30")}
        {aviso("3", "São Paulo do Potengi/RN")} {aviso("4", "São Paulo/SP")}
        <cap:alert><cap:sent>2026-11-17T18:30:00-03:00</cap:sent><cap:status>Actual</cap:status>
        <cap:scope>Public</cap:scope><cap:msgType>Cancel</cap:msgType>
        <cap:references>SEDEC,4,2026-11-17T18:00:00-03:00</cap:references></cap:alert></feed>"""
    resultado = fontes.ler_avisos(feed, ref)
    assert [a["id"] for a in resultado] == ["1"]
    assert resultado[0]["emissor"] == "Defesa Civil"


def test_idap_usa_poligono_quando_area_textual_diz_sao_paulo():
    from xml.etree.ElementTree import fromstring

    area = fromstring(f"""<area xmlns="{fontes.CAP[1:-1]}">
        <areaDesc>SÃO PAULO/SP</areaDesc>
        <polygon>-20.2,-50.3 -20.2,-50.0 -20.6,-50.0 -20.6,-50.3 -20.2,-50.3</polygon>
    </area>""")
    assert not fontes._area_capital(area, [(-23.56, -46.55)])
    assert fontes._area_capital(area, [(-20.4, -50.2)])


def test_indicadores_do_historico_simulado(cliente):
    i = cliente.get("/indicadores").json()
    assert i["alertas_total"] > 20 and i["ocorrencias_confirmadas"] > 20
    assert 15 <= i["antecedencia_media_min"] <= 120
    assert 40 <= i["taxa_acerto_pct"] <= 100
    assert 40 <= i["cobertura_ocorrencias_pct"] <= 100
    assert i["populacao_monitorada"] == sum(b["populacao"] for b in cliente.get("/bairros").json())
    assert i["inclui_dados_simulados"] is True


def test_historico_reprodutivel(tmp_path, monkeypatch):
    """Mesma semente = mesmos indicadores em qualquer máquina."""
    resultados = []
    for n in range(2):
        monkeypatch.setattr(config, "DB_PATH", str(tmp_path / f"r{n}.db"))
        monkeypatch.setattr(config, "API_KEY", CHAVE)
        with TestClient(main.app) as c:
            i = c.get("/indicadores").json()
            resultados.append((i["alertas_total"], i["ocorrencias_confirmadas"], i["taxa_acerto_pct"]))
    assert resultados[0] == resultados[1]


# ------------------------------------------------------------- segurança
def test_escrita_exige_chave(cliente):
    corpo = {"sensor_id": "s1", "bairro_id": "penha", "nivel_cm": 10, "classificacao": "normal"}
    assert cliente.post("/leituras", json=corpo).status_code == 401
    assert cliente.post("/leituras", json=corpo, headers={"X-API-Key": "errada"}).status_code == 401
    assert cliente.post("/leituras", json=corpo, headers=H).status_code == 201


def test_sem_api_key_configurada_bloqueia(cliente, monkeypatch):
    monkeypatch.setattr(config, "API_KEY", "")
    r = cliente.post("/alertas", json={"bairro_id": "penha", "nivel": "alto", "mensagem": "teste"}, headers=H)
    assert r.status_code == 503


def test_validacoes(cliente):
    assert cliente.post("/leituras", headers=H, json={
        "sensor_id": "s1", "bairro_id": "nao-existe", "nivel_cm": 10, "classificacao": "normal"}).status_code == 404
    assert cliente.post("/leituras", headers=H, json={
        "sensor_id": "s1", "bairro_id": "penha", "nivel_cm": 10, "classificacao": "inventada"}).status_code == 422
    assert cliente.post("/risco", headers=H, json=[
        {"bairro_id": "penha", "hora": "ontem", "chuva_mm": 3}]).status_code == 422


def test_deteccao_sem_anonimizar_e_recusada(cliente):
    r = cliente.post("/deteccoes", headers=H, json={
        "bairro_id": "penha", "imagem_anonimizada": False,
        "deteccoes": [{"classe": "rua_alagada", "confianca": 0.9}]})
    assert r.status_code == 422 and "LGPD" in r.text


def test_limite_de_requisicoes(cliente, monkeypatch):
    for _ in range(config.LIMITE_ASSISTENTE):
        assert cliente.post("/assistente", json={"pergunta": "telefone de emergência"}).status_code == 200
    assert cliente.post("/assistente", json={"pergunta": "telefone de emergência"}).status_code == 429


# ------------------------------------------------------------- fluxo de ponta a ponta
def test_fluxo_de_ponta_a_ponta(cliente):
    base = hora_cheia(agora())
    # 1. Big Data publica chuva forte na zona leste
    linhas = [{"bairro_id": b, "hora": (base + timedelta(hours=1)).isoformat(), "chuva_mm": mm}
              for b, mm in {"vila-formosa": 30, "penha": 5, "mooca": 9}.items()]
    assert cliente.post("/risco", headers=H, json=linhas).json() == {"gravadas": 3}
    risco = {r["bairro_id"]: r for r in cliente.get("/risco/agora").json()}
    assert risco["vila-formosa"]["nivel"] == "alto"
    assert risco["mooca"]["nivel"] == "atencao"  # 9 mm x 1.2 = 10.8
    assert risco["penha"]["nivel"] == "baixo"
    assert "Previsão de 30 mm" in risco["vila-formosa"]["motivos"][0]

    # 2. RPA dispara o alerta
    r = cliente.post("/alertas", headers=H, json={
        "bairro_id": "vila-formosa", "nivel": "alto", "mensagem": "Risco alto na Vila Formosa", "canais": "telegram"})
    assert r.status_code == 201
    ativos = cliente.get("/alertas").json()
    assert ativos[0]["bairro_id"] == "vila-formosa" and ativos[0]["bairro_nome"] == "Vila Formosa"

    # 3. Robô envia leitura de perigo em Ipiranga (sem chuva prevista)
    cliente.post("/leituras", headers=H, json={
        "sensor_id": "esp32-01", "bairro_id": "ipiranga", "nivel_cm": 45, "classificacao": "perigo"})
    # 4. Visão confirma rua alagada na Penha
    d = cliente.post("/deteccoes", headers=H, json={
        "bairro_id": "penha", "imagem_anonimizada": True,
        "deteccoes": [{"classe": "rua_alagada", "confianca": 0.88}]}).json()
    assert d["registradas"][0]["status"] == "confirmada"

    risco = {r["bairro_id"]: r for r in cliente.get("/risco/agora").json()}
    assert risco["ipiranga"]["nivel"] == "alto"
    assert any("Sensor" in m for m in risco["ipiranga"]["motivos"])
    assert risco["penha"]["nivel"] == "alto"
    assert any("confirmado" in m for m in risco["penha"]["motivos"])

    # 5. Ocorrência confirmada logo depois do alerta conta como acerto
    antes = cliente.get("/indicadores").json()
    cliente.post("/ocorrencias", headers=H, json={
        "bairro_id": "vila-formosa", "tipo": "rua_alagada", "fonte": "cge"})
    depois = cliente.get("/indicadores").json()
    assert depois["alertas_com_ocorrencia"] == antes["alertas_com_ocorrencia"] + 1
    assert depois["ocorrencias_com_alerta_antes"] == antes["ocorrencias_com_alerta_antes"] + 1
    assert depois["leituras_perigo"] == 1
    assert len(cliente.get("/leituras").json()) == 1
    assert len(cliente.get("/ocorrencias?horas=1").json()) >= 2


def test_deteccao_de_baixa_confianca_fica_pendente(cliente):
    d = cliente.post("/deteccoes", headers=H, json={
        "bairro_id": "lapa", "imagem_anonimizada": True,
        "deteccoes": [{"classe": "rua_alagada", "confianca": 0.3}]}).json()
    assert d["registradas"][0]["status"] == "pendente"
    assert {r["bairro_id"]: r for r in cliente.get("/risco/agora").json()}["lapa"]["nivel"] == "baixo"


def test_alerta_ativo_rpa_deduplica_e_eleva_risco(cliente):
    alerta = {"bairro_id": "jabaquara", "nivel": "alto", "mensagem": "Alerta novo do RPA", "origem": "rpa"}
    novo = cliente.post("/alertas", headers=H, json=alerta)
    repetido = cliente.post("/alertas", headers=H, json={**alerta, "mensagem": "Nova tentativa"})
    assert novo.status_code == 201 and novo.json()["duplicado"] is False
    assert repetido.status_code == 200 and repetido.json() == {**novo.json(), "duplicado": True}
    ativos = [a for a in cliente.get("/alertas").json() if a["bairro_id"] == "jabaquara"]
    assert len(ativos) == 1 and ativos[0]["mensagem"] == alerta["mensagem"]

    risco = next(r for r in cliente.get("/risco/agora").json() if r["bairro_id"] == "jabaquara")
    assert risco["nivel"] == "alto"
    assert "Alerta emitido pela automação: risco alto" in risco["motivos"]


def test_alerta_expirado_permite_novo_e_outra_origem_nao_eleva_risco(cliente):
    ref = agora()
    base = {"bairro_id": "santo-amaro", "nivel": "alto", "mensagem": "Aviso de teste", "origem": "rpa"}
    expirado = cliente.post("/alertas", headers=H, json={
        **base, "criado_em": (ref - timedelta(hours=2)).isoformat(),
        "valido_ate": (ref - timedelta(hours=1)).isoformat(),
    })
    outra_origem = cliente.post("/alertas", headers=H, json={**base, "origem": "manual"})
    assert expirado.status_code == outra_origem.status_code == 201
    risco = next(r for r in cliente.get("/risco/agora").json() if r["bairro_id"] == "santo-amaro")
    assert risco["nivel"] == "baixo"
    novo = cliente.post("/alertas", headers=H, json=base)
    assert novo.status_code == 201 and novo.json()["duplicado"] is False


def test_risco_por_bairro(cliente):
    r = cliente.get("/risco/santana?horas=6").json()
    assert r["bairro"]["nome"] == "Santana" and len(r["previsao"]) == 7
    assert cliente.get("/risco/inexistente").status_code == 404


# ------------------------------------------------------------- fotos
def test_foto_sem_servico_de_visao_retorna_indisponivel(cliente):
    r = cliente.post("/fotos", data={"bairro_id": "penha"},
                     files={"arquivo": ("rua.png", io.BytesIO(PNG), "image/png")})
    assert r.status_code == 503
    assert "indisponível" in r.json()["detail"]
    assert cliente.get("/ocorrencias?horas=1").json() == []


def test_foto_tipo_invalido(cliente):
    r = cliente.post("/fotos", data={"bairro_id": "penha"},
                     files={"arquivo": ("x.txt", io.BytesIO(b"oi" * 100), "text/plain")})
    assert r.status_code == 415


def test_foto_com_servico_de_visao(cliente, monkeypatch):
    class Resposta:
        def raise_for_status(self): pass
        def json(self): return {"deteccoes": [{"classe": "veiculo_submerso", "confianca": 0.91}]}

    class ClienteFalso:
        def __init__(self, *a, **k): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): pass
        async def post(self, url, files=None, data=None):
            assert url == "http://visao/deteccoes" and data["bairro_id"] == "se-anhangabau"
            return Resposta()

    monkeypatch.setattr(config, "VISAO_URL", "http://visao/deteccoes")
    monkeypatch.setattr(main.httpx, "AsyncClient", ClienteFalso)
    r = cliente.post("/fotos", data={"bairro_id": "se-anhangabau"},
                     files={"arquivo": ("rua.png", io.BytesIO(PNG), "image/png")}).json()
    assert r["status"] == "analisada" and r["deteccoes"][0]["status"] == "confirmada"
    risco = {x["bairro_id"]: x for x in cliente.get("/risco/agora").json()}
    assert risco["se-anhangabau"]["nivel"] == "alto"


def test_foto_com_visao_fora_do_ar(cliente, monkeypatch):
    monkeypatch.setattr(config, "VISAO_URL", "http://127.0.0.1:9/nada")
    monkeypatch.setattr(config, "TIMEOUT_SERVICOS", 1.0)
    r = cliente.post("/fotos", data={"bairro_id": "penha"},
                     files={"arquivo": ("rua.png", io.BytesIO(PNG), "image/png")})
    assert r.status_code == 502


# ------------------------------------------------------------- assistente
@pytest.mark.parametrize("pergunta,trecho", [
    ("o que faço se meu carro ficar preso na água?", "lugar alto"),
    ("Posso atravessar a rua alagada a pé?", "Não."),
    ("qual o telefone da defesa civil?", "199"),
    ("como recebo os alertas por sms?", "40199"),
    ("vi um bueiro entupido", "156"),
])
def test_assistente_responde_com_fonte(cliente, pergunta, trecho):
    r = cliente.post("/assistente", json={"pergunta": pergunta}).json()
    assert r["consta"] is True and trecho in r["resposta"] and r["fontes"]


def test_assistente_diz_nao_consta(cliente):
    r = cliente.post("/assistente", json={"pergunta": "Qual é a capital da França?"}).json()
    assert r["consta"] is False and "Não consta" in r["resposta"]


def test_assistente_com_llm_fora_do_ar_degrada(cliente, monkeypatch):
    monkeypatch.setattr(config, "ASSISTENTE_URL", "http://127.0.0.1:9/assistente")
    monkeypatch.setattr(config, "TIMEOUT_SERVICOS", 1.0)
    r = cliente.post("/assistente", json={"pergunta": "telefone de emergência"}).json()
    assert r["modo"].startswith("local") and "199" in r["resposta"]


def test_assistente_preserva_recusa_do_genai(cliente, monkeypatch):
    monkeypatch.setattr(config, "ASSISTENTE_URL", "http://127.0.0.1:8001/assistente")

    def recusar(url, **opcoes):
        return main.httpx.Response(
            200, request=main.httpx.Request("POST", url),
            json={"resposta": "Não consta.", "fonte": None, "recusa": True},
        )

    monkeypatch.setattr(assistente.httpx, "post", recusar)
    dados = cliente.post("/assistente", json={"pergunta": "Qual é a capital da França?"}).json()
    assert dados["modo"] == "llm" and not dados["consta"] and dados["fontes"] == []


def test_remove_dados_pessoais():
    t = assistente.remover_dados_pessoais("meu cpf 123.456.789-09, tel (11) 98765-4321, a@b.com")
    assert "123.456" not in t and "98765" not in t and "a@b.com" not in t


# ------------------------------------------------------------- scripts
def test_montar_linhas_open_meteo():
    import coletar_previsao
    dados = {"hourly": {
        "time": ["2026-11-19T17:00", "2026-11-19T18:00", "2026-11-19T19:00", "2026-11-19T20:00"],
        "precipitation": [36, 12.5, None, 0],
    }}
    linhas = coletar_previsao.montar_linhas(
        "penha", dados, referencia=datetime.fromisoformat("2026-11-19T18:20:00+00:00"),
    )
    assert linhas == [
        {"bairro_id": "penha", "hora": "2026-11-19T18:00:00+00:00", "chuva_mm": 12.5, "fonte": "open-meteo"},
        {"bairro_id": "penha", "hora": "2026-11-19T20:00:00+00:00", "chuva_mm": 0.0, "fonte": "open-meteo"},
    ]


def test_importar_csv_da_ouro(tmp_path, cliente):
    import importar_ouro
    csv_ = tmp_path / "ouro.csv"
    base = hora_cheia(agora())
    csv_.write_text(
        "bairro_id,hora,chuva_mm,nivel\n"
        f"lapa,{(base + timedelta(hours=1)).isoformat()},25,\n"
        f"pinheiros,{(base + timedelta(hours=1)).isoformat()},2,alto\n",
        encoding="utf-8",
    )
    linhas = importar_ouro.ler_csv(str(csv_))
    assert linhas[0]["fonte"] == "ouro" and "nivel" not in linhas[0] and linhas[1]["nivel"] == "alto"
    assert cliente.post("/risco", headers=H, json=linhas).status_code == 200
    risco = {r["bairro_id"]: r["nivel"] for r in cliente.get("/risco/agora").json()}
    assert risco["lapa"] == "alto" and risco["pinheiros"] == "alto"


def test_importar_csv_nativo_da_ouro(tmp_path, cliente):
    import importar_ouro

    base = hora_cheia(agora())
    hora_local = base.astimezone(importar_ouro.FUSO_OURO).replace(tzinfo=None)
    bairros = importar_ouro.BAIRROS_OURO
    csv_ = tmp_path / "fato_risco_bairro_hora.csv"
    csv_.write_text(
        "bairro_id,data_hora,precipitacao_mm,nivel_risco\n"
        + "".join(f"{bairro},{hora_local.isoformat()},30,critico\n" for bairro in bairros),
        encoding="utf-8",
    )
    linhas = importar_ouro.ler_csv(str(csv_))
    assert cliente.post("/risco", headers=H, json=linhas).json() == {"gravadas": 10}
    risco = {r["bairro_id"]: r for r in cliente.get("/risco/agora").json()}
    for bairro in bairros.values():
        assert risco[bairro]["nivel"] == "alto"
        assert "ouro" in risco[bairro]["fontes_previsao"]
        assert cliente.get(f"/risco/{bairro}").json()["previsao"][0]["hora"] == base.isoformat()
