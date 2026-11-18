# PROMPT — Colocar no ar o MVP do Alaga Alerta (GS FIAP 2026.2)

> **Para quem recebeu este arquivo (humano):** descompacte o `alaga-alerta-mvp.zip`,
> abra a pasta `alaga-alerta-mvp` na sua IA de código (Claude Code, Cursor,
> Copilot, Codex etc.) e mande: **"Leia o arquivo PROMPT_MVP.md inteiro e
> execute as fases na ordem, parando onde ele pedir confirmação."**
> Você vai precisar de: Python 3.11+ (ou Docker), Git, uma conta no GitHub e
> uma conta gratuita no Render (render.com) **ou** acesso à nuvem que o
> responsável por DevOps do grupo configurou. Leva cerca de 1 hora.

---

## 0. Instruções para a IA que vai executar

Você é a engenheira responsável por publicar e integrar o MVP do Alaga
Alerta. **O código já está pronto e testado (29 testes passando).** Seu
trabalho é: verificar, publicar numa URL pública, ligar a fonte real de
previsão, ajudar a integrar os componentes das outras disciplinas e deixar
tudo pronto para gravar os vídeos.

Regras que você deve seguir o tempo todo:

1. **Não reescreva o projeto do zero** e não troque a stack (FastAPI +
   SQLite + HTML/JS puro). Ajustes pontuais, sim; refatoração grande, não.
2. **Nunca coloque segredos no código nem no Git.** `API_KEY` só em `.env`
   (que está no `.gitignore`), em GitHub Secrets ou nas variáveis do provedor.
   Antes de cada commit, rode `git status` e confirme que `.env` e `*.db` não
   aparecem. Chave commitada desconta nota em duas disciplinas.
3. **Mantenha `pytest -q` passando.** Toda mudança de comportamento ganha um
   teste em `tests/test_api.py`.
4. **Não remova nada de acessibilidade, LGPD ou segurança** listado no
   `README.md`. Eles valem nota.
5. Textos visíveis ao cidadão em português simples.
6. Ao final de cada fase, rode o "Teste de aceite" da fase e mostre o
   resultado ao humano. Se algo falhar, conserte antes de seguir.
7. Quando precisar de algo que só o humano pode fazer (criar conta, clicar
   num painel, informar nomes e RMs), pare e peça em uma lista curta e clara.

---

## 1. Contexto do trabalho (leia antes de mexer)

- **Faculdade:** FIAP, Engenharia de Software, 4º ano. Global Solution
  2026.2, tema "CitizenTech". Uma mesma equipe (até 5 alunos) entrega um
  único produto avaliado em 7 disciplinas.
- **Produto:** Alaga Alerta, que avisa moradores e motoristas, por bairro e
  antes de alagar, qual é o risco e o que fazer.
- **Prazo:** entrega em **19/11/2026 às 23h55**. O MVP, os repositórios e os
  vídeos precisam **continuar públicos e funcionando até 26/11/2026**
  (semana de correção). MVP fora do ar = itens zerados.
- **Exigências gerais do enunciado que o MVP cobre:**
  - MVP navegável em **URL pública**, usável sem explicação;
  - dados reais (públicos) **ou simulados com geração justificada e
    documentada** (`docs/DADOS_SIMULADOS.md`);
  - componentes integrados por **API**, não por prints;
  - LGPD, credenciais fora do código, acessibilidade (contraste, leitor de
    tela, linguagem simples), resiliência a pouca conectividade;
  - ODS 11 e 13 (secundários 3 e 9).
- **Quem usa o MVP em cada disciplina:**

| Disciplina | Como usa o MVP |
| --- | --- |
| BI & Startup (pitch de 5 min) | Demonstração ao vivo na URL pública (vale 2,5 de 10): previsão → risco no mapa → alerta → pergunta ao assistente → foto analisada → leitura do robô |
| Big Data | Ouro publicada em `POST /risco`; print da tela do MVP com esses dados (requisito 08) |
| Robotic Process Automation | Robô grava alertas e boletins na API; vídeo mostra o alerta aparecendo no MVP |
| Applied Computer Vision | Foto enviada pelo MVP, detecção aparece no mapa |
| Generative AI | Chat do MVP chama o LLM pela API |
| Maker Lab | ESP32 envia leitura para `POST /leituras` e ela aparece no mapa |
| Secure DevOps & Cloud | Containeriza e publica esta API, com pipeline e monitoramento (`/metrics`) |

---

## 2. O que já está pronto (não refazer)

```
app/main.py          API central: rotas públicas, rotas dos componentes (X-API-Key),
                     limite por IP, cabeçalhos de segurança, métricas Prometheus
app/risco.py         Regras: score = chuva × sensibilidade; ≥10 atenção, ≥20 alto;
                     sensor "perigo" ou alagamento confirmado → alto
app/assistente.py    Chat: chama ASSISTENTE_URL (LLM) ou responde pela base local,
                     cita a fonte, diz "não consta", remove CPF/telefone/e-mail
app/indicadores.py   Antecedência média, taxa de acerto, cobertura, população monitorada
app/seed.py          Histórico simulado de jan/2026 (semente fixa) + janela calma atual
static/              Site acessível: meu bairro, alertas, mapa + tabela, chat, foto,
                     sensores, ocorrências, indicadores. Leaflet embutido (sem CDN)
scripts/simular_evento.py   Temporal de demonstração em 5 passos, pela API
scripts/coletar_previsao.py Previsão real do Open-Meteo → POST /risco
scripts/importar_ouro.py    CSV exportado da Ouro (Databricks) → POST /risco
tests/test_api.py    29 testes, incluindo o fluxo de ponta a ponta
Dockerfile           python:3.12-slim, usuário não root, healthcheck, sem segredos
docker-compose.yml   Sobe a API com volume para o banco
.github/workflows/ci.yml        Testes + build da imagem a cada push
.github/workflows/previsao.yml  Coleta Open-Meteo de hora em hora (precisa de secrets)
docs/CONTRATOS.md    Contrato de cada integração (para os colegas)
docs/DADOS_SIMULADOS.md  Justificativa dos dados simulados
docs/tela-*.png      Prints do site funcionando
```

O que **ainda não** foi feito e é a sua missão: rodar na máquina real,
publicar na URL pública, ligar o Open-Meteo de verdade (o ambiente onde o
código foi escrito não tinha acesso à internet), preencher nomes/RMs/links e
apoiar a integração dos colegas.

---

## FASE 1 — Rodar e testar localmente

1. Crie o ambiente e instale:
   ```bash
   python -m venv .venv
   source .venv/bin/activate        # Windows: .venv\Scripts\activate
   pip install -r requirements-dev.txt
   ```
2. Rode os testes: `pytest -q` → esperado: **29 passed**.
3. Suba o servidor:
   ```bash
   export API_KEY=dev DB_PATH=./data/alaga.db     # PowerShell: $env:API_KEY="dev"; $env:DB_PATH="./data/alaga.db"
   uvicorn app.main:app --reload
   ```
4. Em outro terminal, rode o temporal de demonstração:
   ```bash
   python scripts/simular_evento.py --url http://localhost:8000 --chave dev --pausa 2
   ```
5. Abra `http://localhost:8000` no navegador.

**Teste de aceite da fase 1:**
- [ ] `pytest -q` com 29 testes passando
- [ ] `http://localhost:8000/health` responde `{"status":"ok",...}`
- [ ] No site: faixa vermelha "Risco alto de alagamento agora em: Aricanduva, Penha, Vila Formosa"
- [ ] Mapa com tiles do OpenStreetMap e círculos vermelhos na zona leste
- [ ] "Alertas ativos" mostra o alerta da Vila Formosa
- [ ] Chat: clicar em "Carro preso na água" retorna resposta com "Fonte:"
- [ ] Chat: perguntar "qual a capital da França?" retorna "Não consta..."
- [ ] "Sensores nos bueiros" mostra Vila Formosa, 42 cm, perigo
- [ ] "Indicadores de impacto" mostra números (não "—")
- [ ] `http://localhost:8000/docs` abre a documentação da API

Opcional (se tiver Docker): `cp .env.example .env`, editar `API_KEY`, e
`docker compose up --build`. Mesmo teste de aceite em `http://localhost:8000`.

---

## FASE 2 — Repositório público no GitHub

1. **Peça ao humano:** nome completo e RM de todos os integrantes, e o nome
   desejado do repositório (sugestão: `alaga-alerta`).
2. Preencha a tabela "Integrantes" do `README.md` (todas as entregas exigem
   nome e RM; no Maker Lab, falta de nome deixa o grupo sem nota).
3. Gere uma chave forte e guarde **fora do Git** (vai para o Render/nuvem e
   para os colegas por mensagem privada):
   ```bash
   python -c "import secrets; print(secrets.token_urlsafe(32))"
   ```
4. Inicialize e publique:
   ```bash
   git init && git add . && git status     # confirme: sem .env, sem *.db
   git commit -m "MVP Alaga Alerta: API central e site"
   git branch -M main
   git remote add origin https://github.com/USUARIO/alaga-alerta.git
   git push -u origin main
   ```
5. No GitHub, confirme que o repositório é **público** e que o workflow
   **CI** ficou verde (aba Actions).

**Teste de aceite da fase 2:** repositório público abre numa janela anônima;
CI verde; `README.md` com nomes e RMs; nenhum `.env` ou `.db` no repositório.

---

## FASE 3 — URL pública

**Pergunte ao humano qual caminho usar:**

### Opção A — Nuvem do grupo (preferida, se o colega de DevOps já tem Terraform)

A disciplina de Secure DevOps exige Terraform, pipeline com Gitleaks,
Semgrep e Trivy, e monitoramento. Se o colega já tem uma VM criada:

1. Na VM: instalar Docker, clonar o repositório, criar `.env` a partir do
   `.env.example` com a `API_KEY` forte e `DB_PATH=/data/alaga.db`.
2. `docker compose up -d --build`.
3. Expor a porta 8000 (ou colocar um proxy na 80/443). Nunca abrir a porta
   de administração (SSH 22) para `0.0.0.0/0`: só o IP de quem administra.
4. Prometheus deve raspar `https://URL/metrics` (já expõe latência, tráfego,
   erros por status e falhas de serviços externos). Alerta sugerido para a
   demo: taxa de erro alta ou `alaga_servico_externo_falhas_total` subindo.
5. O pipeline do DevOps deve adicionar ao `.github/workflows/ci.yml` os jobs
   de Gitleaks, Semgrep e Trivy e o deploy automático. Não remova o job de
   testes existente.

### Opção B — Render (mais rápida, grátis, sem Terraform)

1. **Humano:** criar conta em render.com com o GitHub.
2. New → **Web Service** → conectar o repositório → Runtime **Docker**
   (ele detecta o `Dockerfile`) → plano **Free**.
3. Variáveis de ambiente (Environment):
   - `API_KEY` = a chave forte da fase 2
   - `SEED_AUTOMATICO` = `1`
   - `DB_PATH` = `/data/alaga.db`
4. Health Check Path: `/health`. O Render injeta `PORT`; o `Dockerfile` já usa.
5. Deploy. A URL fica como `https://alaga-alerta-XXXX.onrender.com`.

Limitações do plano gratuito que você deve explicar ao humano:
- **O serviço dorme sem acesso** e leva cerca de 1 minuto para acordar.
  Abra a URL 2 minutos antes de gravar e antes do horário de correção.
- **O disco é temporário:** a cada novo deploy ou reinício, o banco volta
  ao histórico simulado. Isso não quebra nada: os indicadores são
  reproduzíveis (semente fixa) e o temporal da demo se recria com
  `scripts/simular_evento.py`.

**Teste de aceite da fase 3 (em janela anônima e no celular):**
- [ ] `https://URL/health` responde ok
- [ ] `https://URL/` abre o site com mapa e tabela
- [ ] `python scripts/simular_evento.py --url https://URL --chave CHAVE` roda os 5 passos sem erro
- [ ] O site público mostra o evento (faixa vermelha, alerta, sensor, ocorrências)
- [ ] `curl -X POST https://URL/leituras -H "Content-Type: application/json" -d '{}'` responde **401** (escrita protegida)
- [ ] Preencher a URL na Ficha Técnica do `README.md` e fazer commit

---

## FASE 4 — Previsão real do Open-Meteo

1. Teste manual:
   ```bash
   python scripts/coletar_previsao.py --url https://URL --chave CHAVE
   ```
   Esperado: "Jardim Pantanal (Jardim Helena): 12 horas publicadas" para os
   15 bairros. Se o formato da resposta do Open-Meteo for diferente do
   esperado, ajuste `montar_linhas()` e o teste `test_montar_linhas_open_meteo`.
2. Coleta automática: no GitHub, Settings → Secrets and variables → Actions →
   criar `MVP_URL` (sem barra no final) e `MVP_API_KEY`. O workflow
   `previsao.yml` passa a rodar de hora em hora. Rode uma vez manualmente
   (Actions → "Coletar previsão Open-Meteo" → Run workflow).
3. **Durante a gravação da demo**, desative esse workflow para ele não
   sobrescrever o temporal simulado, e reative depois.

**Teste de aceite da fase 4:** `GET https://URL/risco/vila-formosa` mostra
linhas com `"fonte": "open-meteo"`.

---

## FASE 5 — Integração com os componentes das outras disciplinas

Todos os contratos estão em `docs/CONTRATOS.md`. Envie esse arquivo, a URL
e a `API_KEY` (por mensagem privada, nunca no Git) para cada colega. Para
cada integração, teste com `curl` antes de o colega plugar o código:

```bash
URL=https://SUA-URL; K=SUA_CHAVE

# Big Data (Ouro)
curl -s -X POST $URL/risco -H "X-API-Key: $K" -H "Content-Type: application/json" \
  -d '[{"bairro_id":"lapa","hora":"2026-11-19T18:00:00-03:00","chuva_mm":22}]'

# RPA (alerta)
curl -s -X POST $URL/alertas -H "X-API-Key: $K" -H "Content-Type: application/json" \
  -d '{"bairro_id":"lapa","nivel":"alto","mensagem":"Teste de alerta do RPA","canais":"telegram"}'

# Robô ESP32
curl -s -X POST $URL/leituras -H "X-API-Key: $K" -H "Content-Type: application/json" \
  -d '{"sensor_id":"esp32-teste","bairro_id":"lapa","nivel_cm":12,"classificacao":"normal"}'

# Visão (jeito B)
curl -s -X POST $URL/deteccoes -H "X-API-Key: $K" -H "Content-Type: application/json" \
  -d '{"bairro_id":"lapa","imagem_anonimizada":true,"deteccoes":[{"classe":"bueiro_entupido","confianca":0.8}]}'
```

Checklist de integração (marque conforme cada colega confirmar):

- [ ] **Big Data:** Ouro publicada via `POST /risco` ou `scripts/importar_ouro.py`; nome da tabela Ouro anotado no `README.md`; usar os mesmos `bairro_id` de `GET /bairros`. Se o Big Data tiver população do IBGE por distrito, atualizar `data/bairros.csv` (coluna `populacao`) e fazer commit.
- [ ] **RPA:** grava `POST /alertas` a cada disparo e `POST /ocorrencias` para boletins do CGE; lê `GET /risco/agora` e `GET /leituras` como entrada; retenta quando a API falha.
- [ ] **Maker Lab (ESP32):** `POST /leituras` com `X-API-Key` guardada em `secrets.h` fora do Git; leitura aparece em "Sensores nos bueiros".
- [ ] **Visão:** se o modelo virar serviço HTTP, configurar `VISAO_URL` no Render/nuvem (contrato em `docs/CONTRATOS.md`); senão, gravar em `POST /deteccoes`.
- [ ] **Generative AI:** se o LLM ficar acessível por HTTP, configurar `ASSISTENTE_URL`. Se o LLM for local e não couber na nuvem, documentar onde roda; o chat continua respondendo com a base local (`modo: "local"`), que já cita fontes e diz "não consta".
- [ ] **DevOps:** README principal com links para todos os repositórios (tabela no fim do `README.md`).

Se um colega precisar de um campo novo, **acrescente sem quebrar** o
contrato atual (campos opcionais) e adicione teste.

---

## FASE 6 — Gravação de ponta a ponta (serve para 4 vídeos)

O pitch de BI pede o **MVP real na tela, na URL pública**, sem slides
simulando telas. Roteiro de gravação (cerca de 90 s):

1. Desativar o workflow `previsao.yml`. Rodar `simular_evento.py --calmo`.
2. Abrir a URL pública em tela cheia, barra de endereço visível. Escolher
   "Vila Formosa" em "Meu bairro" (aparece risco baixo).
3. Começar a gravar. Rodar `simular_evento.py --passo 1` → recarregar: mapa
   com zona leste em alto/atenção; card "Meu bairro" vira "Risco alto" com motivo.
4. `--passo 2` → "Alertas ativos" mostra o alerta (se o RPA real estiver
   pronto, use o RPA de verdade e mostre a mensagem no Telegram).
5. No chat, clicar "Carro preso na água" → resposta com fonte.
6. Enviar uma foto de rua alagada escolhendo "Penha" (com o serviço de visão
   ligado) ou rodar `--passo 4` → ocorrência confirmada aparece.
7. `--passo 3` (ou o ESP32 real) → leitura de perigo em "Sensores nos bueiros".
8. Rolar até "Indicadores de impacto".
9. Reativar o workflow `previsao.yml`.

Dica: o site atualiza sozinho a cada 30 s; para a gravação, recarregue a
página (F5) depois de cada passo.

---

## FASE 7 — Checklist final (até 19/11)

- [ ] URL pública funcionando em janela anônima e no celular
- [ ] Repositório público, CI verde, sem segredos (rodar `git log -p | grep -i api_key` e conferir que só aparece o nome da variável)
- [ ] `README.md` com nomes, RMs, URL, links dos outros repositórios e Ficha Técnica completa
- [ ] `data/bairros.csv` com população do IBGE (ou nota mantida em `docs/DADOS_SIMULADOS.md`)
- [ ] Gravação de ponta a ponta feita
- [ ] Serviço vai continuar no ar até 26/11 (no Render, abrir a URL antes do horário de correção; na nuvem do grupo, conferir créditos)

---

## Referência rápida

### Variáveis de ambiente

| Variável | Padrão | Para quê |
| --- | --- | --- |
| `API_KEY` | (vazio = escrita bloqueada) | Chave das rotas de escrita dos componentes |
| `DB_PATH` | `data/alaga.db` | Arquivo SQLite |
| `SEED_AUTOMATICO` | `1` | Popular com histórico simulado se o banco estiver vazio |
| `ASSISTENTE_URL` | vazio | Endpoint do LLM (GenAI) |
| `VISAO_URL` | vazio | Endpoint do modelo de visão |
| `TIMEOUT_SERVICOS` | `20` | Segundos de espera pelos serviços externos |
| `LIMIAR_CONFIANCA` | `0.60` | Confiança mínima para confirmar detecção |
| `CORS_ORIGINS` | vazio | Origens extras autorizadas (separadas por vírgula) |
| `LIMITE_ASSISTENTE` / `LIMITE_FOTOS` | `20` / `6` | Requisições por minuto por IP |

### Rotas

| Método e rota | Quem chama | Chave? |
| --- | --- | --- |
| `GET /` | cidadão (site) | não |
| `GET /bairros`, `/risco/agora`, `/risco/{id}`, `/alertas`, `/ocorrencias`, `/leituras`, `/indicadores` | site, BI, RPA | não |
| `POST /assistente` | site (chat) | não (limite por IP) |
| `POST /fotos` | site (foto do cidadão) | não (limite por IP) |
| `POST /risco` | Big Data | sim |
| `POST /alertas`, `POST /ocorrencias` | RPA | sim |
| `POST /leituras` | robô ESP32 | sim |
| `POST /deteccoes` | Visão | sim |
| `GET /health`, `GET /metrics` | DevOps | não |

### Problemas comuns

| Sintoma | Causa provável e solução |
| --- | --- |
| `503 API_KEY não configurada` | Falta a variável `API_KEY` no servidor |
| `401` nas rotas de escrita | Cabeçalho `X-API-Key` ausente ou diferente da chave do servidor |
| `404 Bairro ... não existe` | Use os ids de `GET /bairros` (minúsculas, com hífen) |
| Mapa cinza, sem ruas | Rede bloqueando `tile.openstreetmap.org`; a tabela abaixo do mapa continua funcionando |
| Indicadores com "—" | Banco sem alertas: confira `SEED_AUTOMATICO=1` ou rode a demo |
| Site demora no primeiro acesso (Render) | Serviço estava dormindo; espere ~1 min |
| Temporal da demo sumiu | Workflow `previsao.yml` sobrescreveu as horas: desative e rode `simular_evento.py` de novo |
| `429` | Limite por IP no chat ou nas fotos; espere 1 minuto |
