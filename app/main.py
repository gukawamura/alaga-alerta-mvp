"""API central do Alaga Alerta.

Todos os componentes conversam por aqui:
  Big Data  -> POST /risco          (tabela Ouro de risco por bairro e hora)
  RPA       -> POST /alertas, POST /ocorrencias (boletins do CGE)
  Robô ESP32-> POST /leituras
  Visão     -> POST /deteccoes      (ou a API chama VISAO_URL a partir de /fotos)
  GenAI     <- POST /assistente     (a API chama ASSISTENTE_URL)
  Front     <- GET /risco/agora, /alertas, /ocorrencias, /leituras, /indicadores
"""
import asyncio
import hmac
import logging
import time
from contextlib import asynccontextmanager
from collections import defaultdict, deque
from datetime import timedelta
from typing import Literal

import httpx
from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest
from pydantic import BaseModel, Field, field_validator

from . import assistente, db, fontes, indicadores, seed
from .config import BASE_DIR, config
from .risco import ORIENTACAO, agora, combinar, hora_cheia, iso, nivel_por_score, parse

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("alaga-alerta")

@asynccontextmanager
async def ciclo_de_vida(_app: FastAPI):
    db.criar_schema()
    if config.DADOS_DEMO and config.SEED_AUTOMATICO and db.banco_vazio():
        totais = seed.popular()
        log.info("banco vazio populado com dados simulados: %s", totais)
    else:
        with db.transacao() as conn:
            seed.inserir_bairros(conn, seed.carregar_bairros())
    estado_idap = {"status": "carregando", "atualizado_em": None, "avisos": []}
    _app.state.idap = estado_idap
    tarefas = []
    if config.FONTES_PUBLICAS and not config.DADOS_DEMO:
        tarefas = [
            asyncio.create_task(fontes.atualizar_periodicamente("Open-Meteo", 1800, fontes.coletar_previsao)),
            asyncio.create_task(fontes.atualizar_periodicamente(
                "IDAP", 600, lambda cliente: fontes.coletar_idap(cliente, estado_idap),
                lambda: estado_idap.update(status="indisponivel"),
            )),
        ]
    else:
        estado_idap["status"] = "desativado"
    try:
        yield
    finally:
        for tarefa in tarefas:
            tarefa.cancel()
        await asyncio.gather(*tarefas, return_exceptions=True)


app = FastAPI(
    lifespan=ciclo_de_vida,
    title="Alaga Alerta — API central",
    version="1.0.0",
    description="Risco de alagamento por bairro, alertas, ocorrências, sensores e assistente.",
)

if config.CORS_ORIGINS:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=config.CORS_ORIGINS,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type", "X-API-Key"],
    )

# ---------------------------------------------------------------- métricas
REQS = Counter("alaga_http_requests_total", "Requisições HTTP", ["metodo", "rota", "status"])
LATENCIA = Histogram("alaga_http_latency_seconds", "Latência HTTP", ["rota"])
INTEGRACOES = Counter("alaga_integracao_total", "Chamadas recebidas de cada componente", ["componente"])
FALHAS_EXTERNAS = Counter("alaga_servico_externo_falhas_total", "Falhas ao chamar serviços externos", ["servico"])

CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data: https://tile.openstreetmap.org; connect-src 'self'; "
    "frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
)


@app.middleware("http")
async def observar(request: Request, call_next):
    inicio = time.perf_counter()
    try:
        resposta = await call_next(request)
    except Exception:
        log.exception("erro não tratado em %s", request.url.path)
        resposta = JSONResponse({"detail": "Erro interno"}, status_code=500)
    rota = request.scope.get("route")
    nome = getattr(rota, "path", "estatico")
    REQS.labels(request.method, nome, str(resposta.status_code)).inc()
    LATENCIA.labels(nome).observe(time.perf_counter() - inicio)
    # A documentação interativa (/docs, /redoc) carrega o Swagger de CDN;
    # a CSP restrita vale para o site do cidadão e para a API.
    if not request.url.path.startswith(("/docs", "/redoc")):
        resposta.headers["Content-Security-Policy"] = CSP
    resposta.headers["X-Content-Type-Options"] = "nosniff"
    resposta.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    resposta.headers["Permissions-Policy"] = "geolocation=(), camera=(), microphone=()"
    return resposta


# ---------------------------------------------------------------- segurança
def exigir_chave(x_api_key: str | None = Header(default=None)) -> None:
    """Rotas de escrita dos componentes exigem X-API-Key."""
    if not config.API_KEY:
        raise HTTPException(503, "API_KEY não configurada no servidor")
    if not x_api_key or not hmac.compare_digest(x_api_key, config.API_KEY):
        raise HTTPException(401, "X-API-Key inválida ou ausente")


_janelas: dict[tuple[str, str], deque] = defaultdict(deque)


def limitar(chave: str, limite: int):
    def dependencia(request: Request) -> None:
        ip = request.headers.get("x-forwarded-for", request.client.host if request.client else "?")
        ip = ip.split(",")[0].strip()
        fila = _janelas[(chave, ip)]
        t = time.monotonic()
        while fila and t - fila[0] > 60:
            fila.popleft()
        if len(fila) >= limite:
            raise HTTPException(429, "Muitas requisições. Tente de novo em um minuto.")
        fila.append(t)
    return dependencia


# ---------------------------------------------------------------- modelos
Nivel = Literal["baixo", "atencao", "alto"]
TipoOcorrencia = Literal["rua_alagada", "veiculo_submerso", "bueiro_entupido"]


def _iso_valido(v: str) -> str:
    try:
        return iso(parse(v))
    except ValueError as e:
        raise ValueError("data/hora inválida; use ISO 8601, ex.: 2026-11-19T18:00:00-03:00") from e


class RiscoEntrada(BaseModel):
    bairro_id: str
    hora: str = Field(description="Início da hora, ISO 8601")
    chuva_mm: float = Field(ge=0, le=500)
    nivel: Nivel | None = Field(default=None, description="Se omitido, a API calcula pelo score")
    fonte: str = "ouro"

    _v_hora = field_validator("hora")(_iso_valido)


class AlertaEntrada(BaseModel):
    bairro_id: str
    nivel: Literal["atencao", "alto"]
    mensagem: str = Field(min_length=5, max_length=400)
    criado_em: str | None = None
    valido_ate: str | None = None
    origem: str = "rpa"
    canais: str = ""


class OcorrenciaEntrada(BaseModel):
    bairro_id: str
    tipo: TipoOcorrencia
    fonte: Literal["cge", "cidadao", "sensor"] = "cge"
    status: Literal["confirmada", "pendente", "descartada"] = "confirmada"
    confianca: float | None = Field(default=None, ge=0, le=1)
    criado_em: str | None = None
    detalhe: str = Field(default="", max_length=300)


class LeituraEntrada(BaseModel):
    sensor_id: str = Field(min_length=1, max_length=60)
    bairro_id: str
    nivel_cm: float = Field(ge=0, le=1000)
    classificacao: Literal["normal", "atencao", "perigo"]
    medido_em: str | None = None


class Deteccao(BaseModel):
    classe: TipoOcorrencia
    confianca: float = Field(ge=0, le=1)


class DeteccoesEntrada(BaseModel):
    bairro_id: str
    deteccoes: list[Deteccao]
    imagem_anonimizada: bool = Field(description="Rostos e placas borrados antes de armazenar")
    criado_em: str | None = None
    simulada: bool = False


class Pergunta(BaseModel):
    pergunta: str = Field(min_length=2, max_length=500)


# ---------------------------------------------------------------- utilitários
def _bairro_existe(bairro_id: str) -> dict:
    linhas = db.consultar("SELECT * FROM bairros WHERE id = ?", (bairro_id,))
    if not linhas:
        raise HTTPException(404, f"Bairro '{bairro_id}' não existe. Veja GET /bairros")
    return linhas[0]


def _quando(valor: str | None) -> str:
    return _iso_valido(valor) if valor else iso(agora())


def _registrar_deteccoes(
    bairro_id: str, deteccoes: list[Deteccao], criado_em: str, simulada: bool = False,
) -> list[dict]:
    resultado = []
    detalhe = "detecção por visão computacional"
    if simulada:
        detalhe += " - demonstração"
    with db.transacao() as conn:
        for d in deteccoes:
            status = "confirmada" if d.confianca >= config.LIMIAR_CONFIANCA else "pendente"
            cur = conn.execute(
                "INSERT INTO ocorrencias (bairro_id,tipo,fonte,status,confianca,criado_em,detalhe)"
                " VALUES (?,?,?,?,?,?,?)",
                (bairro_id, d.classe, "cidadao", status, d.confianca, criado_em, detalhe),
            )
            resultado.append({"id": cur.lastrowid, "classe": d.classe, "confianca": d.confianca, "status": status})
    return resultado


# ---------------------------------------------------------------- rotas públicas
@app.get("/health", tags=["operação"])
def health() -> dict:
    db.consultar("SELECT 1")
    return {"status": "ok", "horario": iso(agora())}


@app.get("/metrics", tags=["operação"], include_in_schema=False)
def metrics() -> Response:
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.get("/bairros", tags=["cidadão"])
def listar_bairros() -> list[dict]:
    return db.consultar("SELECT id,nome,zona,lat,lon,populacao FROM bairros ORDER BY nome")


@app.get("/risco/agora", tags=["cidadão"])
def risco_agora() -> list[dict]:
    """Risco final por bairro: previsão das próximas 3h, sensor, ocorrências e RPA."""
    ref = agora()
    inicio, fim = iso(hora_cheia(ref)), iso(hora_cheia(ref) + timedelta(hours=2))
    alertas_rpa = {a["bairro_id"]: a["nivel"] for a in db.consultar(
        "SELECT bairro_id, CASE WHEN MAX(nivel='alto') THEN 'alto' ELSE 'atencao' END AS nivel"
        " FROM alertas WHERE origem='rpa' AND criado_em <= ? AND valido_ate >= ? GROUP BY bairro_id",
        (iso(ref), iso(ref)),
    )}
    saida = []
    for b in db.consultar("SELECT * FROM bairros ORDER BY nome"):
        previsao = db.consultar(
            "SELECT hora,chuva_mm,score,nivel,fonte FROM risco_bairro_hora"
            " WHERE bairro_id=? AND hora BETWEEN ? AND ?"
            " AND (? OR fonte NOT IN ('simulado','demo')) ORDER BY hora",
            (b["id"], inicio, fim, config.DADOS_DEMO),
        )
        leitura = db.consultar(
            "SELECT * FROM leituras WHERE bairro_id=? AND medido_em<=?"
            " AND (? OR sensor_id NOT LIKE 'demo-%') ORDER BY medido_em DESC LIMIT 1",
            (b["id"], iso(ref), config.DADOS_DEMO),
        )
        ocorr = db.consultar(
            "SELECT * FROM ocorrencias WHERE bairro_id=? AND criado_em >= ?"
            " AND (? OR (detalhe NOT LIKE '%demonstração%' AND detalhe!='histórico simulado'))",
            (b["id"], iso(ref - timedelta(hours=2)), config.DADOS_DEMO),
        )
        r = combinar(previsao, leitura[0] if leitura else None, ocorr, ref, alertas_rpa.get(b["id"]))
        saida.append({
            "bairro_id": b["id"], "nome": b["nome"], "zona": b["zona"],
            "lat": b["lat"], "lon": b["lon"],
            "nivel": r["nivel"], "motivos": r["motivos"], "orientacao": r["orientacao"],
            "chuva_prevista_mm": max((p["chuva_mm"] for p in previsao), default=None),
            "sem_previsao": not previsao,
            "fontes_previsao": sorted({p["fonte"] for p in previsao}),
            "sensor_simulado": bool(leitura and leitura[0]["sensor_id"].startswith("demo-")
                                     and leitura[0]["medido_em"] >= iso(ref - timedelta(minutes=60))),
        })
    return saida


@app.get("/risco/{bairro_id}", tags=["cidadão"])
def risco_bairro(bairro_id: str, horas: int = 12) -> dict:
    b = _bairro_existe(bairro_id)
    horas = max(1, min(horas, 48))
    base = hora_cheia(agora())
    linhas = db.consultar(
        "SELECT hora,chuva_mm,score,nivel,fonte FROM risco_bairro_hora"
        " WHERE bairro_id=? AND hora BETWEEN ? AND ?"
        " AND (? OR fonte NOT IN ('simulado','demo')) ORDER BY hora",
        (bairro_id, iso(base), iso(base + timedelta(hours=horas)), config.DADOS_DEMO),
    )
    return {"bairro": b, "previsao": linhas}


@app.get("/alertas", tags=["cidadão"])
def listar_alertas(ativos: bool = True, limite: int = 50) -> list[dict]:
    limite = max(1, min(limite, 500))
    if ativos:
        return db.consultar(
            "SELECT a.*, b.nome AS bairro_nome FROM alertas a JOIN bairros b ON b.id=a.bairro_id"
            " WHERE a.valido_ate >= ? AND a.criado_em <= ?"
            " AND (? OR a.origem NOT IN ('simulado','demo')) ORDER BY a.criado_em DESC LIMIT ?",
            (iso(agora()), iso(agora()), config.DADOS_DEMO, limite),
        )
    return db.consultar(
        "SELECT a.*, b.nome AS bairro_nome FROM alertas a JOIN bairros b ON b.id=a.bairro_id"
        " WHERE (? OR a.origem NOT IN ('simulado','demo')) ORDER BY a.criado_em DESC LIMIT ?",
        (config.DADOS_DEMO, limite),
    )

@app.get("/alertas/oficiais", tags=["cidadão"])
def alertas_oficiais(request: Request) -> dict:
    estado = request.app.state.idap.copy()
    ref = iso(agora())
    estado["avisos"] = [a for a in estado["avisos"] if a["valido_ate"] > ref]
    return estado


@app.get("/ocorrencias", tags=["cidadão"])
def listar_ocorrencias(horas: int = 24) -> list[dict]:
    horas = max(1, min(horas, 24 * 60))
    return db.consultar(
        "SELECT o.*, b.nome AS bairro_nome, b.lat, b.lon FROM ocorrencias o"
        " JOIN bairros b ON b.id=o.bairro_id WHERE o.criado_em >= ?"
        " AND NOT (o.status='pendente' AND o.fonte='cidadao' AND o.confianca IS NULL"
        " AND o.detalhe='foto recebida; serviço de visão não configurado')"
        " AND (? OR (o.detalhe NOT LIKE '%demonstração%' AND o.detalhe!='histórico simulado'))"
        " ORDER BY o.criado_em DESC",
        (iso(agora() - timedelta(hours=horas)), config.DADOS_DEMO),
    )


@app.get("/leituras", tags=["cidadão"])
def listar_leituras(limite: int = 20) -> list[dict]:
    limite = max(1, min(limite, 500))
    return db.consultar(
        "SELECT l.*, b.nome AS bairro_nome FROM leituras l JOIN bairros b ON b.id=l.bairro_id"
        " WHERE (? OR l.sensor_id NOT LIKE 'demo-%') ORDER BY l.medido_em DESC LIMIT ?",
        (config.DADOS_DEMO, limite),
    )


@app.get("/leituras/simuladas", tags=["cidadão"])
def leituras_simuladas() -> list[dict]:
    """Cenários de demonstração calculados sob demanda, sem gravar medições."""
    if not config.SIMULAR_BUEIROS or config.DADOS_DEMO:
        return []
    referencia = agora()
    inicio = hora_cheia(referencia)
    linhas = db.consultar(
        "SELECT b.id AS bairro_id, b.nome AS bairro_nome, b.sensibilidade,"
        " MAX(r.chuva_mm) AS chuva_prevista_mm"
        " FROM bairros b JOIN risco_bairro_hora r ON r.bairro_id=b.id"
        " WHERE b.id IN ('aricanduva','penha','vila-formosa')"
        " AND r.fonte='open-meteo' AND r.hora BETWEEN ? AND ?"
        " AND NOT EXISTS (SELECT 1 FROM leituras l WHERE l.bairro_id=b.id"
        " AND l.sensor_id NOT LIKE 'demo-%' AND l.medido_em BETWEEN ? AND ?)"
        " GROUP BY b.id ORDER BY b.nome",
        (iso(inicio), iso(inicio + timedelta(hours=2)),
         iso(referencia - timedelta(hours=1)), iso(referencia)),
    )
    resultado = []
    for linha in linhas:
        chuva = linha["chuva_prevista_mm"]
        nivel = min(80, round(5 + 1.5 * chuva * linha["sensibilidade"]))
        classificacao = "perigo" if nivel >= 40 else "atencao" if nivel >= 20 else "normal"
        resultado.append({
            "bairro_id": linha["bairro_id"], "bairro_nome": linha["bairro_nome"],
            "nivel_cm": nivel, "classificacao": classificacao, "simulada": True,
            "chuva_prevista_mm": chuva, "fonte_previsao": "open-meteo",
        })
    return resultado


@app.get("/indicadores", tags=["negócio e impacto"])
def obter_indicadores() -> dict:
    return indicadores.calcular()


@app.get("/orientacoes", tags=["cidadão"])
def orientacoes() -> dict:
    return ORIENTACAO


@app.post("/assistente", tags=["cidadão"], dependencies=[Depends(limitar("assistente", config.LIMITE_ASSISTENTE))])
def perguntar(p: Pergunta) -> dict:
    resposta = assistente.responder(p.pergunta)
    if resposta["modo"].startswith("local") and config.ASSISTENTE_URL:
        FALHAS_EXTERNAS.labels("assistente").inc()
    return resposta


@app.post("/fotos", tags=["cidadão"], dependencies=[Depends(limitar("fotos", config.LIMITE_FOTOS))])
async def enviar_foto(bairro_id: str = Form(...), arquivo: UploadFile = File(...)) -> dict:
    """Foto do cidadão -> modelo de visão -> ocorrência no mapa.

    A imagem não é gravada pela API (LGPD): ela vai para o serviço de visão,
    que a anonimiza, e só o resultado (classe, confiança, bairro) fica salvo.
    """
    _bairro_existe(bairro_id)
    if arquivo.content_type not in {"image/jpeg", "image/png", "image/webp"}:
        raise HTTPException(415, "Envie uma foto em JPG, PNG ou WEBP")
    conteudo = await arquivo.read(config.TAMANHO_MAX_FOTO + 1)
    if len(conteudo) > config.TAMANHO_MAX_FOTO:
        raise HTTPException(413, "Foto muito grande")
    if len(conteudo) < 100:
        raise HTTPException(400, "Arquivo vazio ou inválido")

    if not config.VISAO_URL:
        raise HTTPException(503, "A análise de fotos está indisponível. Tente novamente mais tarde.")

    try:
        async with httpx.AsyncClient(timeout=config.TIMEOUT_SERVICOS) as cliente:
            r = await cliente.post(
                config.VISAO_URL,
                files={"arquivo": (arquivo.filename or "foto.jpg", conteudo, arquivo.content_type)},
                data={"bairro_id": bairro_id},
            )
        r.raise_for_status()
        dados = r.json()
        deteccoes = [Deteccao(**d) for d in dados.get("deteccoes", [])]
    except Exception:
        FALHAS_EXTERNAS.labels("visao").inc()
        log.warning("serviço de visão indisponível")
        raise HTTPException(502, "Não conseguimos analisar a foto agora. Tente de novo em instantes.")
    INTEGRACOES.labels("visao").inc()
    registradas = _registrar_deteccoes(bairro_id, deteccoes, iso(agora()))
    confirmadas = [d for d in registradas if d["status"] == "confirmada"]
    if confirmadas:
        msg = "A foto confirmou uma ocorrência. Confira a seção de ocorrências."
    elif registradas:
        msg = "A análise encontrou um indício, mas não conseguiu confirmar a ocorrência."
    else:
        msg = "A análise não identificou ocorrências nesta foto."
    return {"status": "analisada", "mensagem": msg, "deteccoes": registradas}


# ---------------------------------------------------------------- rotas dos componentes (X-API-Key)
def _verificar_demo(simulado: bool) -> None:
    if simulado and not config.DADOS_DEMO:
        raise HTTPException(422, "Dados simulados exigem DADOS_DEMO=1")


@app.post("/risco", tags=["componentes"], dependencies=[Depends(exigir_chave)])
def gravar_risco(linhas: list[RiscoEntrada]) -> dict:
    """Big Data publica aqui a tabela Ouro (upsert por bairro e hora)."""
    if len(linhas) > 5000:
        raise HTTPException(413, "Envie no máximo 5000 linhas por chamada")
    _verificar_demo(any(l.fonte in {"demo", "simulado"} for l in linhas))
    bairros = {b["id"]: b for b in db.consultar("SELECT id,sensibilidade FROM bairros")}
    desconhecidos = sorted({l.bairro_id for l in linhas} - bairros.keys())
    if desconhecidos:
        raise HTTPException(404, f"Bairros inexistentes: {desconhecidos}")
    with db.transacao() as conn:
        for l in linhas:
            score = round(l.chuva_mm * bairros[l.bairro_id]["sensibilidade"], 1)
            nivel = l.nivel or nivel_por_score(score)
            conn.execute(
                "INSERT OR REPLACE INTO risco_bairro_hora VALUES (?,?,?,?,?,?)",
                (l.bairro_id, iso(hora_cheia(parse(l.hora))), l.chuva_mm, score, nivel, l.fonte),
            )
    INTEGRACOES.labels("bigdata").inc()
    return {"gravadas": len(linhas)}


@app.post(
    "/alertas", tags=["componentes"], status_code=201, dependencies=[Depends(exigir_chave)],
    responses={200: {"description": "Alerta ativo já registrado"}},
)
def gravar_alerta(a: AlertaEntrada, resposta: Response) -> dict:
    """RPA registra cada alerta disparado (Telegram/WhatsApp)."""
    _verificar_demo(a.origem in {"demo", "simulado"})
    _bairro_existe(a.bairro_id)
    criado = _quando(a.criado_em)
    valido = _iso_valido(a.valido_ate) if a.valido_ate else iso(parse(criado) + timedelta(hours=3))
    if valido <= criado:
        raise HTTPException(422, "valido_ate precisa ser depois de criado_em")
    with db.transacao(imediata=True) as conn:
        existente = conn.execute(
            "SELECT id, criado_em, valido_ate FROM alertas"
            " WHERE bairro_id=? AND nivel=? AND origem=? AND criado_em <= ? AND valido_ate >= ?"
            " ORDER BY criado_em DESC, id DESC LIMIT 1",
            (a.bairro_id, a.nivel, a.origem, criado, criado),
        ).fetchone()
        if existente:
            resposta.status_code = 200
            return {**dict(existente), "duplicado": True}
        cur = conn.execute(
            "INSERT INTO alertas (bairro_id,nivel,mensagem,criado_em,valido_ate,origem,canais)"
            " VALUES (?,?,?,?,?,?,?)",
            (a.bairro_id, a.nivel, a.mensagem, criado, valido, a.origem, a.canais),
        )
    INTEGRACOES.labels("rpa").inc()
    return {"id": cur.lastrowid, "criado_em": criado, "valido_ate": valido, "duplicado": False}


@app.post("/ocorrencias", tags=["componentes"], status_code=201, dependencies=[Depends(exigir_chave)])
def gravar_ocorrencia(o: OcorrenciaEntrada) -> dict:
    """Boletins do CGE/Defesa Civil coletados pelo RPA ou pelo Big Data."""
    _verificar_demo("demonstração" in o.detalhe or o.detalhe == "histórico simulado")
    _bairro_existe(o.bairro_id)
    with db.transacao() as conn:
        cur = conn.execute(
            "INSERT INTO ocorrencias (bairro_id,tipo,fonte,status,confianca,criado_em,detalhe)"
            " VALUES (?,?,?,?,?,?,?)",
            (o.bairro_id, o.tipo, o.fonte, o.status, o.confianca, _quando(o.criado_em), o.detalhe),
        )
    INTEGRACOES.labels("ocorrencias").inc()
    return {"id": cur.lastrowid}


@app.post("/leituras", tags=["componentes"], status_code=201, dependencies=[Depends(exigir_chave)])
def gravar_leitura(l: LeituraEntrada) -> dict:
    """Robô ESP32 envia nível da água + classificação da IA embarcada."""
    _verificar_demo(l.sensor_id.startswith("demo-"))
    _bairro_existe(l.bairro_id)
    with db.transacao() as conn:
        cur = conn.execute(
            "INSERT INTO leituras (sensor_id,bairro_id,nivel_cm,classificacao,medido_em,recebido_em)"
            " VALUES (?,?,?,?,?,?)",
            (l.sensor_id, l.bairro_id, l.nivel_cm, l.classificacao, _quando(l.medido_em), iso(agora())),
        )
    INTEGRACOES.labels("robo").inc()
    return {"id": cur.lastrowid}


@app.post("/deteccoes", tags=["componentes"], status_code=201, dependencies=[Depends(exigir_chave)])
def gravar_deteccoes(d: DeteccoesEntrada) -> dict:
    """Serviço de visão grava detecções (imagem já anonimizada)."""
    _verificar_demo(d.simulada)
    _bairro_existe(d.bairro_id)
    if not d.imagem_anonimizada:
        raise HTTPException(422, "LGPD: borre rostos e placas antes de enviar (imagem_anonimizada=true)")
    registradas = _registrar_deteccoes(d.bairro_id, d.deteccoes, _quando(d.criado_em), d.simulada)
    INTEGRACOES.labels("visao").inc()
    return {"registradas": registradas}


# ---------------------------------------------------------------- site
app.mount("/", StaticFiles(directory=BASE_DIR / "static", html=True), name="site")
