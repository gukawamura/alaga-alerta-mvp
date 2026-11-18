"""Previsão do Open-Meteo e avisos públicos da Defesa Civil (IDAP)."""
import asyncio
import logging
import re
import unicodedata
from urllib.parse import urlparse
from xml.etree import ElementTree

import httpx

from . import db
from .risco import agora, hora_cheia, iso, nivel_por_score, parse
from scripts.coletar_previsao import OPEN_METEO, montar_linhas

IDAP_URL = "https://idapfile.mdr.gov.br/idap/api/rss/cap"
CAP = "{urn:oasis:names:tc:emergency:cap:1.2}"
ATOM = "{http://www.w3.org/2005/Atom}"
log = logging.getLogger(__name__)


def _texto(elemento, nome):
    return (elemento.findtext(CAP + nome) or "").strip()


def _area_capital(area, pontos):
    tem_poligono = False
    for poligono in area.findall(CAP + "polygon"):
        try:
            vertices = [tuple(map(float, par.split(","))) for par in (poligono.text or "").split()]
            if len(vertices) < 3 or any(len(par) != 2 for par in vertices):
                continue
        except ValueError:
            continue
        tem_poligono = True
        for lat, lon in pontos:
            dentro = False
            for (y1, x1), (y2, x2) in zip(vertices, vertices[1:] + vertices[:1]):
                if (y1 > lat) != (y2 > lat) and lon < x1 + (x2 - x1) * (lat - y1) / (y2 - y1):
                    dentro = not dentro
            if dentro:
                return True
    if tem_poligono and pontos:
        return False
    if any(_texto(g, "value") == "3550308" for g in area.findall(CAP + "geocode")):
        return True
    nome = unicodedata.normalize("NFKD", _texto(area, "areaDesc")).encode("ascii", "ignore").decode().casefold()
    return any(re.fullmatch(r"(?:municipio de )?sao paulo\s*(?:[/\-]\s*sp|\(sp\))?", parte.strip())
               for parte in re.split(r"[;,\n]", nome))


def ler_avisos(dados, referencia, pontos=()):
    raiz = ElementTree.fromstring(dados)
    if raiz.tag != ATOM + "feed":
        raise ValueError("Formato inesperado no feed IDAP")
    descartados = set()
    avisos = {}
    for alerta in raiz.iter(CAP + "alert"):
        if _texto(alerta, "status") != "Actual" or _texto(alerta, "scope") != "Public":
            continue
        try:
            enviado = parse(_texto(alerta, "sent"))
        except ValueError:
            continue
        if enviado > referencia:
            continue
        tipo = _texto(alerta, "msgType")
        if tipo in {"Update", "Cancel"}:
            for ref in _texto(alerta, "references").split():
                campos = ref.split(",", 2)
                if len(campos) == 3:
                    descartados.add(tuple(campos[:2]))
        if tipo not in {"Alert", "Update"}:
            continue
        chave = (_texto(alerta, "sender"), _texto(alerta, "identifier"))
        for info in alerta.findall(CAP + "info"):
            if not _texto(info, "language").lower().startswith("pt"):
                continue
            try:
                inicio = parse(_texto(info, "onset") or _texto(info, "effective") or iso(enviado))
                fim = parse(_texto(info, "expires"))
            except ValueError:
                continue
            if not inicio <= referencia < fim:
                continue
            areas = [_texto(a, "areaDesc") for a in info.findall(CAP + "area") if _area_capital(a, pontos)]
            if not areas:
                continue
            link = _texto(info, "web")
            try:
                url = urlparse(link)
                link = link if url.scheme == "https" and url.hostname else None
            except ValueError:
                link = None
            avisos[chave] = {
                "id": chave[1], "emissor": _texto(info, "senderName") or chave[0],
                "areas": areas, "titulo": _texto(info, "headline") or _texto(info, "event"),
                "mensagem": _texto(info, "description"), "orientacao": _texto(info, "instruction"),
                "emitido_em": iso(enviado), "valido_ate": iso(fim),
                "url": link,
            }
    return sorted((aviso for chave, aviso in avisos.items() if chave not in descartados),
                  key=lambda aviso: aviso["emitido_em"], reverse=True)


async def coletar_idap(cliente, estado):
    dados = bytearray()
    async with cliente.stream("GET", IDAP_URL) as resposta:
        resposta.raise_for_status()
        async for bloco in resposta.aiter_bytes():
            dados.extend(bloco)
            if len(dados) > 64 * 1024 * 1024:
                raise ValueError("Feed IDAP acima do tamanho esperado")
    referencia = agora()
    pontos = [(b["lat"], b["lon"]) for b in db.consultar("SELECT lat,lon FROM bairros")]
    avisos = await asyncio.to_thread(ler_avisos, dados, referencia, pontos)
    estado.update(status="ok", atualizado_em=iso(referencia), avisos=avisos)


async def coletar_previsao(cliente):
    bairros = db.consultar("SELECT id,lat,lon,sensibilidade FROM bairros ORDER BY id")
    referencia = agora()
    resposta = await cliente.get(OPEN_METEO, params={
        "latitude": ",".join(str(b["lat"]) for b in bairros),
        "longitude": ",".join(str(b["lon"]) for b in bairros),
        "hourly": "precipitation", "forecast_hours": 12, "timezone": "GMT",
    })
    resposta.raise_for_status()
    lotes = resposta.json()
    if not isinstance(lotes, list) or len(lotes) != len(bairros):
        raise ValueError("Número de locais diferente do solicitado ao Open-Meteo")
    linhas = []
    for bairro, lote in zip(bairros, lotes, strict=True):
        for item in montar_linhas(bairro["id"], lote, referencia=hora_cheia(referencia)):
            score = round(item["chuva_mm"] * bairro["sensibilidade"], 1)
            linhas.append((bairro["id"], item["hora"], item["chuva_mm"], score, nivel_por_score(score)))
    if not linhas:
        raise ValueError("Open-Meteo não retornou previsão vigente")
    with db.transacao() as conn:
        conn.executemany(
            "INSERT INTO risco_bairro_hora VALUES (?,?,?,?,?,'open-meteo')"
            " ON CONFLICT(bairro_id,hora) DO UPDATE SET chuva_mm=excluded.chuva_mm,"
            " score=excluded.score,nivel=excluded.nivel,fonte=excluded.fonte"
            " WHERE risco_bairro_hora.fonte!='ouro'",
            linhas,
        )


async def atualizar_periodicamente(nome, segundos, atualizar, falhou=None):
    async with httpx.AsyncClient(timeout=35, follow_redirects=True) as cliente:
        while True:
            try:
                await atualizar(cliente)
            except (httpx.HTTPError, ValueError, KeyError, TypeError, ElementTree.ParseError) as erro:
                log.warning("Falha na coleta de %s (%s)", nome, type(erro).__name__)
                if falhou:
                    falhou()
            await asyncio.sleep(segundos)
