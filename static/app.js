/* Alaga Alerta — front do MVP.
   Sem framework, para carregar rápido em celular de entrada.
   Todo texto vindo da API é inserido com textContent (nada de innerHTML). */
(function () {
  "use strict";

  const NOMES = { baixo: "Baixo", atencao: "Atenção", alto: "Alto", indisponivel: "Previsão indisponível" };
  const CORES = { baixo: "#1b6e35", atencao: "#b07400", alto: "#a8201a", indisponivel: "#475569" };
  const FONTES_PREVISAO = { ouro: "Ouro (Databricks)", "open-meteo": "Open-Meteo", "dwd-mosmix": "DWD MOSMIX (previsão regional)", simulado: "Simulação", demo: "Simulação" };
  const TIPOS = {
    rua_alagada: "Rua alagada",
    veiculo_submerso: "Veículo submerso",
    bueiro_entupido: "Bueiro entupido",
  };
  const FONTES = { cge: "CGE / Defesa Civil", cidadao: "Foto de morador", sensor: "Sensor" };
  const fmtHora = new Intl.DateTimeFormat("pt-BR", {
    timeZone: "America/Sao_Paulo", day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit",
  });

  let mapa = null;
  let camadaRisco = null;
  let camadaOcorrencias = null;
  let mapaEnquadrado = false;
  let riscoAtual = [];
  let bairrosCarregados = false;

  // ------------------------------------------------------------ utilitários
  function el(tag, attrs, ...filhos) {
    const n = document.createElement(tag);
    if (attrs) for (const [k, v] of Object.entries(attrs)) {
      if (k === "class") n.className = v; else if (v !== undefined && v !== null) n.setAttribute(k, v);
    }
    for (const f of filhos) if (f !== null && f !== undefined) n.append(f instanceof Node ? f : String(f));
    return n;
  }
  function selo(nivel) { return el("span", { class: "selo selo-" + nivel }, NOMES[nivel] || nivel); }
  function quando(iso) { try { return fmtHora.format(new Date(iso)); } catch (e) { return iso; } }
  function limpar(n) { while (n.firstChild) n.removeChild(n.firstChild); }

  function guardar(chave, valor) { try { localStorage.setItem(chave, valor); } catch (e) { /* sem storage */ } }
  function ler(chave) { try { return localStorage.getItem(chave); } catch (e) { return null; } }

  async function api(caminho, opcoes) {
    const r = await fetch(caminho, opcoes);
    let corpo = null;
    try { corpo = await r.json(); } catch (e) { /* sem corpo */ }
    if (!r.ok) {
      const msg = corpo && corpo.detail ? (typeof corpo.detail === "string" ? corpo.detail : "Dados inválidos") : "Falha de conexão";
      throw new Error(msg);
    }
    return corpo;
  }

  // ------------------------------------------------------------ bairros
  async function carregarBairros() {
    if (bairrosCarregados) return;
    const bairros = await api("bairros");
    const sel = document.getElementById("sel-bairro");
    const selFoto = document.getElementById("foto-bairro");
    for (const s of [sel, selFoto]) {
      limpar(s);
      s.append(el("option", { value: "" }, "Selecione…"));
      for (const b of bairros) s.append(el("option", { value: b.id }, b.nome + " (" + b.zona + ")"));
    }
    const salvo = ler("alaga-bairro");
    if (salvo) { sel.value = salvo; selFoto.value = salvo; }
    sel.addEventListener("change", () => {
      guardar("alaga-bairro", sel.value);
      if (sel.value) selFoto.value = sel.value;
      renderMeuBairro();
    });
    bairrosCarregados = true;
    renderMeuBairro();
  }

  // ------------------------------------------------------------ risco
  function textoRisco(nivel) {
    return nivel === "indisponivel" ? NOMES[nivel] : "Risco " + NOMES[nivel].toLowerCase();
  }

  function fontePrevisao(r) {
    if (r.sem_previsao) return "Previsão indisponível";
    const fontes = new Set(r.fontes_previsao.map((fonte) => FONTES_PREVISAO[fonte] || fonte));
    return "Previsão: " + [...fontes].join(", ");
  }

  function seloDemo() {
    return el("span", { class: "selo selo-indisponivel" }, "Simulação");
  }

  function renderMeuBairro() {
    const alvo = document.getElementById("meu-risco");
    const id = document.getElementById("sel-bairro").value;
    limpar(alvo);
    alvo.className = "meu-risco";
    if (!id) { alvo.append(el("p", null, "Escolha um bairro para ver o risco e o que fazer.")); return; }
    const r = riscoAtual.find((x) => x.bairro_id === id);
    if (!r) return;
    alvo.classList.add(r.nivel);
    alvo.append(el("p", { class: "nivel" }, textoRisco(r.nivel)));
    if (r.sensor_simulado) alvo.append(seloDemo());
    alvo.append(el("p", null, r.orientacao));
    if (r.nivel !== "indisponivel") alvo.append(el("p", { class: "mudo" }, fontePrevisao(r)));
    if (r.motivos.length) {
      const ul = el("ul");
      r.motivos.forEach((m) => ul.append(el("li", null, m)));
      alvo.append(el("p", { class: "mudo" }, "Por quê:"), ul);
    }
  }

  function renderTabela() {
    const tb = document.getElementById("tabela-risco");
    limpar(tb);
    const ordem = { alto: 0, atencao: 1, indisponivel: 2, baixo: 3 };
    const lista = riscoAtual.slice().sort((a, b) => ordem[a.nivel] - ordem[b.nivel] || a.nome.localeCompare(b.nome));
    for (const r of lista) {
      tb.append(el("tr", null,
        el("th", { scope: "row" }, r.nome),
        el("td", null, r.zona),
        el("td", null, selo(r.nivel), r.sensor_simulado ? seloDemo() : null),
        el("td", null, r.motivos.join(". "),
          r.nivel !== "indisponivel" ? el("span", { class: "quando" }, fontePrevisao(r)) : null)));
    }
  }

  function iniciarMapa() {
    const div = document.getElementById("mapa");
    if (typeof L === "undefined") { div.classList.add("sem-mapa"); return; }
    try {
      mapa = L.map(div, { scrollWheelZoom: false }).setView([-23.53, -46.6], 11);
      const estado = document.getElementById("mapa-status");
      L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
        maxZoom: 17, attribution: "© OpenStreetMap contributors",
      }).on("loading", () => { estado.hidden = true; })
        .on("tileerror", () => { estado.hidden = false; }).addTo(mapa);
      camadaRisco = L.layerGroup().addTo(mapa);
      camadaOcorrencias = L.layerGroup().addTo(mapa);
    } catch (e) { div.classList.add("sem-mapa"); }
  }

  function renderMapa() {
    if (!mapa || !camadaRisco) return;
    if (!mapaEnquadrado && riscoAtual.length) {
      const limites = L.latLngBounds(riscoAtual.map((bairro) => [bairro.lat, bairro.lon]));
      mapa.fitBounds(limites, { padding: [28, 28], maxZoom: 12, animate: false });
      mapaEnquadrado = true;
    }
    camadaRisco.clearLayers();
    for (const r of riscoAtual) {
      const raio = r.nivel === "alto" ? 1400 : r.nivel === "atencao" ? 1100 : 800;
      L.circle([r.lat, r.lon], {
        radius: raio, color: CORES[r.nivel], weight: 2, fillColor: CORES[r.nivel], fillOpacity: 0.35,
      }).bindTooltip(el("span", null, r.nome + " · " + textoRisco(r.nivel))).addTo(camadaRisco);
    }
  }

  async function atualizarRisco() {
    riscoAtual = await api("risco/agora");
    const totais = { alto: 0, atencao: 0, baixo: 0, indisponivel: 0 };
    for (const r of riscoAtual) totais[r.nivel]++;
    for (const [nivel, total] of Object.entries(totais)) {
      document.getElementById("total-" + nivel).textContent = total;
    }
    const sincronizado = new Date();
    const carimbo = document.getElementById("mapa-atualizado");
    carimbo.dateTime = sincronizado.toISOString();
    carimbo.textContent = "Atualizado às " + new Intl.DateTimeFormat("pt-BR", {
      timeZone: "America/Sao_Paulo", hour: "2-digit", minute: "2-digit",
    }).format(sincronizado);
    carimbo.hidden = false;
    renderMeuBairro(); renderTabela(); renderMapa();
    const altos = riscoAtual.filter((r) => r.nivel === "alto");
    const aviso = document.getElementById("aviso-geral");
    if (altos.length) {
      aviso.hidden = false;
      const simulado = altos.some((r) => r.sensor_simulado || r.fontes_previsao.some((f) => f === "demo" || f === "simulado"));
      aviso.textContent = (simulado ? "A lista inclui dados simulados. " : "") +
        "Risco alto de alagamento agora em: " + altos.map((r) => r.nome).join(", ") +
        ". Evite essas regiões e nunca atravesse água.";
    } else { aviso.hidden = true; }
  }

  // ------------------------------------------------------------ listas
  async function atualizarAlertas() {
    const lista = await api("alertas?ativos=true");
    const ul = document.getElementById("lista-alertas");
    limpar(ul);
    if (!lista.length) { ul.append(el("li", null, "Nenhum alerta ativo agora.")); return; }
    for (const a of lista) {
      ul.append(el("li", null, selo(a.nivel), " ", el("strong", null, a.bairro_nome), " — ", a.mensagem,
        ["demo", "simulado"].includes(a.origem) ? seloDemo() : null,
        el("span", { class: "quando" }, "Emitido " + quando(a.criado_em) + " · válido até " + quando(a.valido_ate))));
    }
  }

  async function atualizarAvisosOficiais() {
    const status = document.getElementById("avisos-oficiais-status");
    const painel = document.getElementById("painel-avisos-oficiais");
    const lista = document.getElementById("avisos-oficiais");
    let dados;
    try {
      dados = await api("alertas/oficiais");
    } catch {
      status.textContent = "Consulta à Defesa Civil indisponível.";
      painel.hidden = true;
      limpar(lista);
      return;
    }
    const mensagens = {
      carregando: "Consultando avisos oficiais…",
      desativado: "Consulta a avisos oficiais desativada nesta instalação.",
      indisponivel: "Consulta à Defesa Civil indisponível.",
      desatualizado: dados.avisos.length
        ? "Falha na atualização. Avisos ainda vigentes da consulta de " + quando(dados.atualizado_em) + "."
        : "Falha na atualização. Última consulta concluída em " + quando(dados.atualizado_em) + ".",
    };
    const total = dados.avisos.length;
    painel.hidden = total === 0;
    painel.querySelector("summary").textContent = total === 1 ? "Ver 1 aviso oficial" : "Ver " + total + " avisos oficiais";
    limpar(lista);
    status.textContent = mensagens[dados.status] || (total
      ? "Última consulta: " + quando(dados.atualizado_em)
      : "Nenhum aviso vigente para a capital encontrado na consulta ao IDAP de " + quando(dados.atualizado_em) + ".");
    for (const aviso of dados.avisos) {
      lista.append(el("li", null, el("strong", null, aviso.titulo),
        el("p", null, aviso.mensagem),
        aviso.orientacao ? el("p", null, aviso.orientacao) : null,
        el("span", { class: "quando" }, aviso.emissor + " · " + aviso.areas.join(", ") +
          " · válido até " + quando(aviso.valido_ate)),
        aviso.url ? el("a", { href: aviso.url, rel: "noreferrer" }, "Orientações da fonte") : null));
    }
  }

  async function atualizarLeituras() {
    const lista = await api("leituras?limite=8");
    const ul = document.getElementById("lista-leituras");
    limpar(ul);
    if (!lista.length) { ul.append(el("li", null, "Nenhuma leitura de bueiro recebida nesta instalação.")); return; }
    const mapaNivel = { normal: "baixo", atencao: "atencao", perigo: "alto" };
    for (const l of lista) {
      ul.append(el("li", null, selo(mapaNivel[l.classificacao]), " ",
        el("strong", null, l.bairro_nome), " — água a " + Math.round(l.nivel_cm) + " cm (" + l.classificacao + ")",
        l.sensor_id.startsWith("demo-") ? seloDemo() : null,
        el("span", { class: "quando" }, "Sensor " + l.sensor_id + " · " + quando(l.medido_em))));
    }
  }

  async function atualizarSimulacaoBueiros() {
    const lista = await api("leituras/simuladas");
    const ul = document.getElementById("lista-leituras-simuladas");
    limpar(ul);
    const classificacoes = { normal: "Normal", atencao: "Atenção", perigo: "Perigo" };
    const mm = new Intl.NumberFormat("pt-BR", { maximumFractionDigits: 1 });
    for (const l of lista) {
      ul.append(el("li", null, el("strong", null, l.bairro_nome), " ", seloDemo(),
        el("span", { class: "quando" }, "Cenário: " + l.nivel_cm + " cm · " + classificacoes[l.classificacao]),
        el("span", { class: "quando" }, "Maior chuva horária prevista na janela: " + mm.format(l.chuva_prevista_mm) + " mm")));
    }
    document.getElementById("simulacao-bueiros").hidden = !lista.length;
  }

  async function atualizarOcorrencias() {
    const lista = await api("ocorrencias?horas=24");
    if (camadaOcorrencias) {
      camadaOcorrencias.clearLayers();
      for (const o of lista.filter((item) => item.status === "confirmada").slice(0, 100)) {
        L.circleMarker([o.lat, o.lon], { pane: "markerPane", radius: 6, color: "#172554", fillOpacity: 0.85 })
          .bindTooltip(el("span", null, (TIPOS[o.tipo] || o.tipo) + " · " + o.bairro_nome))
          .addTo(camadaOcorrencias);
      }
    }
    const ul = document.getElementById("lista-ocorrencias");
    limpar(ul);
    if (!lista.length) { ul.append(el("li", null, "Nenhuma ocorrência nas últimas 24 horas.")); return; }
    for (const o of lista.slice(0, 10)) {
      const st = o.status === "confirmada" ? "confirmada" : o.status === "pendente" ? "não confirmada" : "descartada";
      const conf = o.confianca != null ? " · confiança " + Math.round(o.confianca * 100) + "%" : "";
      ul.append(el("li", null, el("strong", null, TIPOS[o.tipo] || o.tipo), " em " + o.bairro_nome + " (" + st + ")",
        el("span", { class: "quando" }, (FONTES[o.fonte] || o.fonte) + conf + " · " + quando(o.criado_em))));
    }
  }

  async function atualizarIndicadores() {
    const i = await api("indicadores");
    const dl = document.getElementById("indicadores");
    limpar(dl);
    const num = (v, suf) => (v === null || v === undefined ? "—" : v.toLocaleString("pt-BR") + (suf || ""));
    const itens = [
      ["Antecedência média do alerta", num(i.antecedencia_media_min, " min")],
      ["Alertas que se confirmaram", num(i.taxa_acerto_pct, "%")],
      ["Alagamentos avisados antes", num(i.cobertura_ocorrencias_pct, "%")],
      ["Moradores em bairros monitorados", num(i.populacao_monitorada)],
      ["Fotos de moradores confirmadas", num(i.ocorrencias_cidadaos_confirmadas)],
      ["Leituras de perigo nos sensores", num(i.leituras_perigo)],
    ];
    for (const [rot, val] of itens) dl.append(el("div", null, el("dt", null, rot), el("dd", null, val)));
    const nota = document.getElementById("ind-nota");
    nota.textContent = "Calculado a partir de " + i.alertas_total + " alertas e " + i.ocorrencias_confirmadas +
      " ocorrências confirmadas" + (i.periodo.inicio ? ", de " + quando(i.periodo.inicio) + " a " + quando(i.periodo.fim) : "") +
      "." + (i.inclui_dados_simulados ? " Inclui histórico simulado documentado (janeiro de 2026)." : "");
  }

  // ------------------------------------------------------------ assistente
  function adicionarMsg(quem, texto, fontes) {
    const chat = document.getElementById("chat");
    const div = el("div", { class: "msg " + quem }, texto);
    if (fontes && fontes.length) div.append(el("span", { class: "fonte" }, "Fonte: " + fontes.join("; ")));
    chat.append(div);
    chat.scrollTop = chat.scrollHeight;
  }

  async function perguntar(texto) {
    const botao = document.querySelector("#form-pergunta button");
    adicionarMsg("eu", texto);
    botao.disabled = true;
    try {
      const r = await api("assistente", {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ pergunta: texto }),
      });
      adicionarMsg("bot", r.resposta, r.fontes);
    } catch (e) {
      adicionarMsg("bot", "Não consegui responder agora (" + e.message + "). Em emergência, ligue 199.");
    } finally { botao.disabled = false; }
  }

  function iniciarAssistente() {
    const form = document.getElementById("form-pergunta");
    const campo = document.getElementById("pergunta");
    form.addEventListener("submit", (ev) => {
      ev.preventDefault();
      const t = campo.value.trim();
      if (t.length < 2) return;
      campo.value = "";
      perguntar(t);
    });
    document.querySelectorAll(".chip").forEach((b) => b.addEventListener("click", () => perguntar(b.dataset.pergunta)));
  }

  // ------------------------------------------------------------ foto
  function iniciarFoto() {
    const form = document.getElementById("form-foto");
    const status = document.getElementById("foto-status");
    form.addEventListener("submit", async (ev) => {
      ev.preventDefault();
      const botao = form.querySelector("button");
      botao.disabled = true;
      status.textContent = "Enviando e analisando a foto…";
      try {
        const r = await api("fotos", { method: "POST", body: new FormData(form) });
        status.textContent = r.mensagem;
        form.reset();
        const salvo = ler("alaga-bairro"); if (salvo) document.getElementById("foto-bairro").value = salvo;
        atualizarTudo();
      } catch (e) {
        status.textContent = e.message;
      } finally { botao.disabled = false; }
    });
  }

  // ------------------------------------------------------------ ciclo
  function iniciarLayout() {
    const painel = document.querySelector(".painel-principal");
    const cartoes = Array.from(painel.children);
    const esquerda = el("div", { class: "coluna-painel" });
    const direita = el("div", { class: "coluna-painel" });
    const desktop = window.matchMedia("(min-width: 921px)");

    function organizar() {
      const foco = document.activeElement;
      painel.classList.toggle("com-colunas", desktop.matches);
      if (desktop.matches) {
        painel.append(esquerda, direita);
        for (const cartao of cartoes) {
          const coluna = cartao.dataset.coluna === "esquerda" ? esquerda : direita;
          coluna.append(cartao);
        }
      } else {
        painel.append(...cartoes);
        esquerda.remove();
        direita.remove();
      }
      if (painel.contains(foco) && foco !== document.activeElement) {
        foco.focus({ preventScroll: true });
      }
      if (mapa) mapa.invalidateSize({ pan: false });
    }

    desktop.addEventListener("change", organizar);
    organizar();
  }

  async function atualizarTudo() {
    const tarefas = [atualizarRisco, carregarBairros, atualizarAlertas, atualizarAvisosOficiais,
      atualizarLeituras, atualizarSimulacaoBueiros, atualizarOcorrencias, atualizarIndicadores];
    const res = await Promise.allSettled(tarefas.map((f) => f()));
    const falhou = res.some((r) => r.status === "rejected");
    const aviso = document.getElementById("aviso-geral");
    if (falhou && aviso.hidden) {
      aviso.hidden = false;
      aviso.textContent = riscoAtual.length
        ? "Alguns dados não puderam ser atualizados. A página mantém os últimos dados recebidos."
        : "Não foi possível carregar os dados de risco. Confira se o servidor do MVP está rodando.";
    }
  }

  async function iniciar() {
    if (location.protocol === "file:") {
      const aviso = document.getElementById("aviso-geral");
      aviso.hidden = false;
      aviso.append("Abra o MVP pelo servidor local para usar o mapa, o chat e os alertas. ",
        el("a", { href: "http://127.0.0.1:8000/" }, "Abrir o Alaga Alerta"));
      document.querySelectorAll("main section:not(.introducao)").forEach((secao) => { secao.hidden = true; });
      return;
    }
    iniciarLayout();
    iniciarMapa(); iniciarAssistente(); iniciarFoto();
    await atualizarTudo();
    setInterval(atualizarTudo, 30000);
  }

  document.addEventListener("DOMContentLoaded", iniciar);
})();
