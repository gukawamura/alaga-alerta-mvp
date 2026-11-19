# Alaga Alerta — MVP (API central + site)

Mostra o risco de alagamento por bairro e orienta moradores e motoristas
sobre como agir.

Global Solution 2026.2 · FIAP · Engenharia de Software 4º ano · CitizenTech

[Abrir o MVP](https://alaga-alerta-mvp.onrender.com/) · [Documentação da API](https://alaga-alerta-mvp.onrender.com/docs)

## Integrantes

| Nome completo | RM |
| --- | --- |
| Felipe Capriotti | RM98460 |
| Gustavo Kawamura | RM99679 |
| Manoella Herrerias Waideman | RM98906 |
| Victor Hugo Andrade | RM550996 |

## Ficha Técnica do MVP

| Campo | Alaga Alerta |
| --- | --- |
| Nome do produto | Alaga Alerta |
| Cidadão e território | Moradores e motoristas de bairros com histórico de alagamento em São Paulo (22 áreas no MVP, incluindo os dez pontos da Ouro, Jabaquara e Santo Amaro) |
| Problema, em uma frase | Alertas de chuva são genéricos e chegam tarde para quem precisa decidir sair ou desviar |
| Proposta de valor | Risco de alagamento por bairro, em tempo útil, com orientação do que fazer |
| Arquitetura | API central FastAPI, SQLite e site. O diagrama abaixo mostra os contratos dos componentes. |
| Fontes de dados | Open-Meteo para previsão horária, DWD MOSMIX para previsão regional de contingência, IDAP para avisos oficiais da Defesa Civil e catálogo de bairros para população estimada. O cenário de demonstração está descrito em [Dados simulados](docs/DADOS_SIMULADOS.md). |
| Modelo de IA validado | Llama 3.2 3B no Ollama, com RAG e citação de fontes. Validação pela API do MVP local. |
| URL do MVP e repositório | [MVP público](https://alaga-alerta-mvp.onrender.com/) · [Código no GitHub](https://github.com/gukawamura/alaga-alerta-mvp) |
| Indicadores de impacto | Antecedência média do alerta, taxa de acerto, cobertura de ocorrências, população monitorada (`GET /indicadores`) |
| ODS conectados | **11.5** · Apoia decisões de deslocamento durante alagamentos. **13.1** · Combina previsão e avisos para apoiar a preparação para chuvas intensas. **3.d** · Orienta sobre riscos à saúde em enchentes. **9.1** · Ajuda a identificar áreas onde o monitoramento da drenagem é relevante. |

## Usar o painel

- **Meu bairro e mapa.** Escolha uma das 22 áreas monitoradas para ver o risco, as orientações e a fonte da previsão. O mapa considera as próximas três horas e os sinais disponíveis. A tabela de bairros oferece a mesma informação em texto.
- **Avisos e alertas.** Abra a lista de avisos oficiais da Defesa Civil para ler os detalhes. Os alertas registrados no Alaga Alerta aparecem em uma lista própria.
- **Ocorrências.** O cartão conta os registros das últimas 24 horas e lista até os 10 mais recentes quando aberto. Registros mais antigos continuam no banco enquanto o armazenamento os preservar. A API aceita consultas de até 60 dias, e os indicadores usam o histórico disponível.
- **Assistente.** Consulte orientações sobre alagamentos pelo chat. Evite incluir dados pessoais na pergunta.

## Arquitetura

```
Open-Meteo / IBGE ──► Big Data (Airflow → Databricks Ouro) ──────POST /risco───┐
Boletins CGE ──► RPA ──POST /alertas, /ocorrencias──────────────────────────────┤
Robô ESP32 (sensor de nível + IA) ──POST /leituras──────────────────────────────┤
Foto do cidadão ──► site ──POST /fotos──► API ──► serviço de visão (VISAO_URL) ─┤
Pergunta no chat ──► API ──► LLM com RAG (ASSISTENTE_URL) ──────────────────────┤
                                                                                ▼
                                       API central (FastAPI + SQLite) ──► site (URL pública)
                                                    │
                                     /metrics ──► Prometheus/Grafana (DevOps)
```

Os caminhos, os campos e os exemplos de integração estão nos [contratos da API](docs/CONTRATOS.md).

| Componente | Situação da integração |
| --- | --- |
| Defesa Civil | A API consulta o feed IDAP e disponibiliza os avisos em `GET /alertas/oficiais`. |
| Big Data | CSV da previsão Ouro importado via `POST /risco` e exibido no MVP local. A importação demonstrada foi manual. [Pipeline de Big Data](https://github.com/gukawamura/alaga-big-data) |
| GenAI | A API do MVP local chamou o RAG com Ollama via `ASSISTENTE_URL`. No Render, o chat usa a base de contingência. [Implementação e avaliação de GenAI](https://github.com/gukawamura/alaga-genai) |
| RPA | `POST /alertas` e `POST /ocorrencias` disponíveis. O MVP evita alertas duplicados e considera alertas ativos do RPA no mapa. O teste com o robô externo fica com a equipe de RPA. |
| Visão computacional | `POST /fotos` chama o serviço configurado em `VISAO_URL`. `POST /deteccoes` recebe resultados. A validação do modelo externo fica com a equipe de visão. |
| ESP32 | `POST /leituras` recebe leituras reais. A validação do hardware fica com a equipe de Maker Lab. |
| Operação | O MVP está publicado no Render com `GET /health` e `GET /metrics`. |

## Rodar localmente

O mapa, o chat e os alertas usam a API local. Inicie o servidor e abra
`http://127.0.0.1:8000/` no navegador.

Com Docker:

```bash
cp .env.example .env        # edite API_KEY
docker compose up --build
# abra http://localhost:8000
```

Sem Docker, no Windows PowerShell (Python 3.11+):

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
$env:API_KEY = "dev"
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Sem Docker, no Linux ou macOS (Python 3.11+):

```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
export API_KEY=dev DB_PATH=./data/alaga.db         # Windows PowerShell: $env:API_KEY="dev"
uvicorn app.main:app --reload
```

Testes: `pytest -q` (inclui o fluxo de ponta a ponta).

Para ligar o GenAI local, inicie o Ollama e a API da pasta `genai` na
porta 8001. Antes de iniciar o MVP pelo PowerShell, defina:

```powershell
$env:ASSISTENTE_URL = "http://127.0.0.1:8001/assistente"
$env:TIMEOUT_SERVICOS = "75"
```

Na hospedagem, a URL do GenAI precisa ser acessível pelo servidor do MVP.

## Publicação com GitHub e Render

Use o GitHub como repositório e o Render como serviço web Docker. A imagem
serve o site e a API na mesma URL HTTPS. Em **New → Blueprint** no Render,
conecte o repositório do MVP e aplique o arquivo `render.yaml`. O Blueprint
configura o health check `/health` e gera uma `API_KEY` aleatória no
ambiente do serviço. No plano gratuito, o SQLite usa o armazenamento efêmero.
Os dados são perdidos em reinícios, novos deploys e pausas por inatividade.
Em serviço pago com [disco persistente](https://render.com/docs/disks),
monte o disco em `/data` e use `DB_PATH=/data/alaga.db`.

No ambiente privado do RPA, configure `MVP_URL` com a URL do Render e
`MVP_API_KEY` com o valor da `API_KEY` do servidor. O robô envia esse valor
no cabeçalho `X-API-Key`. Visitantes do site usam a URL
pública, e a credencial fica no servidor e nas automações autorizadas.

Depois do deploy, verifique `GET /health`, `GET /bairros` e o mapa pela URL
pública. A equipe do RPA pode testar um envio e um reenvio em ambiente de
teste com a mesma chave do servidor.

Por padrão, `FONTES_PUBLICAS=1`, `DADOS_DEMO=0` e `SEED_AUTOMATICO=0`.
Na inicialização, a API agenda a coleta da previsão do Open-Meteo a cada
30 minutos e a dos avisos do IDAP a cada 10 minutos. O recorte dos avisos usa
o município indicado ou os polígonos que cobrem pontos do catálogo de bairros.
Quando o IDAP falha, a API tenta de novo após dois minutos. O painel sinaliza
a falha e exibe apenas os avisos da última consulta que ainda estiverem vigentes.

Quando o Open-Meteo limita a coleta, o mapa usa a previsão regional do
[DWD MOSMIX](https://opendata.dwd.de/weather/local_forecasts/mos/MOSMIX_L/).
Cada bairro usa o ponto de previsão disponível mais próximo entre São Paulo e
Guarulhos. O mapa identifica essa origem, e previsões já disponíveis da
Ouro ou do Open-Meteo têm prioridade.

Em Aricanduva, Penha e Vila Formosa, o painel pode exibir uma simulação
de bueiro conforme a chuva horária prevista pelo Open-Meteo. Sem previsão
vigente, ou com uma leitura real recebida na última hora para o bairro,
a simulação não aparece. Ela não é gravada no banco e não entra no risco,
nos indicadores ou nos alertas. Desative com `SIMULAR_BUEIROS=0`.
O ESP32 pode enviar leituras reais em `POST /leituras`.

Com `DADOS_DEMO=0`, os registros simulados identificados ficam ocultos,
inclusive em bancos criados antes da mudança. Use `FONTES_PUBLICAS=0`
para desativar as coletas automáticas do Open-Meteo e do IDAP nessa instância.

Para simular um temporal, inicialize uma instância de demonstração com
`DADOS_DEMO=1`, `SEED_AUTOMATICO=1` e um `DB_PATH` separado.

```bash
python scripts/simular_evento.py --url http://localhost:8000 --chave dev
python scripts/simular_evento.py --url http://localhost:8000 --chave dev --painel  # alertas e bueiros simulados
python scripts/simular_evento.py --url http://localhost:8000 --chave dev --calmo   # volta ao normal
```

## Segurança, LGPD e acessibilidade

- Credenciais só por variável de ambiente (`.env` fora do Git, GitHub Secrets na nuvem). Rotas de escrita exigem `X-API-Key`; sem chave configurada, ficam bloqueadas.
- O cidadão escolhe o bairro. A API central retém o resultado da detecção. Pelo contrato, o serviço de visão deve anonimizar rostos e placas. `POST /deteccoes` exige a confirmação `imagem_anonimizada=true`.
- A API filtra padrões de CPF, telefone e e-mail antes de encaminhar perguntas ao LLM. O chat não grava as perguntas no SQLite.
- Limite de requisições por IP no chat e no envio de fotos; cabeçalhos de segurança (CSP, nosniff, no-referrer).
- Acessibilidade: nível de risco com texto e símbolo, tabela equivalente ao mapa, foco visível, link "pular para o conteúdo" e layout responsivo. Em caso de falha na atualização do risco, o site sinaliza o problema e pode manter os dados já carregados na página.
- O banco guarda risco por bairro, alertas, registros de ocorrências e leituras de sensores.

## Estrutura

```
app/            API (main.py), regras de risco, assistente, indicadores, dados simulados
static/         site (HTML, CSS, JS) + Leaflet embutido
data/           bairros.csv e base_conhecimento.json
scripts/        simular_evento.py, coletar_previsao.py (Open-Meteo), importar_ouro.py (CSV da Ouro)
tests/          pytest
docs/           contratos de integração, dados simulados, prints
```
