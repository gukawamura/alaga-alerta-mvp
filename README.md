# Alaga Alerta — MVP (API central + site)

Avisa moradores e motoristas, por bairro e em tempo útil, quando uma rua
está prestes a alagar e o que fazer.

Global Solution 2026.2 · FIAP · Engenharia de Software 4º ano · CitizenTech

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
| Arquitetura: componentes | API central (FastAPI) + site acessível; Big Data publica a Ouro em `POST /risco`; RPA grava alertas e boletins; robô ESP32 envia leituras; visão computacional confirma fotos; LLM com RAG responde no chat. Ver diagrama abaixo |
| Fontes de dados | Open-Meteo (previsão horária), boletins CGE/Defesa Civil, IBGE (população), sensores, fotos de cidadãos; histórico simulado documentado em `docs/DADOS_SIMULADOS.md` |
| Modelos de IA utilizados | YOLO ajustado (rua alagada, bueiro entupido, veículo submerso); LLM local com RAG sobre manuais da Defesa Civil; IA embarcada no ESP32 (normal/atenção/perigo) |
| URL do MVP e repositório | PREENCHER (URL pública) · PREENCHER (link deste repositório) |
| Indicadores de impacto | Antecedência média do alerta, taxa de acerto, cobertura de ocorrências, população monitorada (`GET /indicadores`) |
| ODS conectados | 11 (meta 11.5) e 13 (meta 13.1); secundários 3 (3.d) e 9 (9.1) |

## Arquitetura

```
Open-Meteo / CGE / IBGE ──► Big Data (Airflow → Databricks Ouro) ──POST /risco──┐
Boletins CGE ──► RPA ──POST /alertas, /ocorrencias──────────────────────────────┤
Robô ESP32 (sensor de nível + IA) ──POST /leituras──────────────────────────────┤
Foto do cidadão ──► site ──POST /fotos──► API ──► serviço de visão (VISAO_URL) ─┤
Pergunta no chat ──► API ──► LLM com RAG (ASSISTENTE_URL) ──────────────────────┤
                                                                                ▼
                                       API central (FastAPI + SQLite) ──► site (URL pública)
                                                    │
                                     /metrics ──► Prometheus/Grafana (DevOps)
```

Contratos de cada integração: [`docs/CONTRATOS.md`](docs/CONTRATOS.md).
Andamento da entrega: [`docs/PLANO_ENTREGA.md`](docs/PLANO_ENTREGA.md).
Documentação interativa da API: `/docs` na URL do MVP.

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
ambiente do serviço. O plano gratuito usa um SQLite novo; os dados escritos
podem ser perdidos em reinícios e novos deploys. Se a equipe contratar um
disco persistente, monte-o em `/data` e mantenha `DB_PATH=/data/alaga.db`.

Se a coleta agendada do GitHub Actions for usada, configure `MVP_URL` e
`MVP_API_KEY` em **Settings → Secrets and variables → Actions**. A operação
normal do MVP já coleta a previsão diretamente. Ative o workflow apenas se
for necessário disparar a coleta pelo GitHub.

No ambiente privado do RPA, configure `MVP_URL` com a URL do Render e
`MVP_API_KEY` com a mesma chave do servidor. Visitantes do site usam a URL
pública, e a credencial fica no servidor e nas automações autorizadas.

Depois do deploy, verifique `GET /health`, `GET /bairros` e o mapa pela URL
pública. A equipe do RPA pode testar um envio e um reenvio em ambiente de
teste com a mesma chave do servidor.

Por padrão, `FONTES_PUBLICAS=1`, `DADOS_DEMO=0` e `SEED_AUTOMATICO=0`.
Na inicialização, a API consulta a previsão do Open-Meteo e os avisos
da Defesa Civil pelo IDAP, com atualizações a cada 30 e 10 minutos,
respectivamente. O risco calculado pelo MVP e os avisos oficiais aparecem
em áreas próprias. O recorte do IDAP usa o município indicado no aviso
ou polígonos que cobrem pontos do catálogo de bairros.

Em Aricanduva, Penha e Vila Formosa, o painel pode exibir uma simulação
de bueiro conforme a chuva horária prevista pelo Open-Meteo. Sem previsão
vigente, ou com uma leitura real recebida na última hora para o bairro,
a simulação não aparece. Ela não é gravada no banco e não entra no risco,
nos indicadores ou nos alertas. Desative com `SIMULAR_BUEIROS=0`.
O ESP32 pode enviar leituras reais em `POST /leituras`. A API de
estações do Cemaden é uma fonte hidrológica a avaliar para estações com
cobertura conhecida. O nível em uma estação de rio tem seu próprio ponto
de medição e não representa a altura da água em um bueiro.

Com `DADOS_DEMO=0`, os registros simulados identificados ficam ocultos,
inclusive em bancos criados antes da mudança. Use `FONTES_PUBLICAS=0`
se a publicação da previsão for responsabilidade da infraestrutura externa.

Para simular um temporal, inicialize uma instância de demonstração com
`DADOS_DEMO=1`, `SEED_AUTOMATICO=1` e um `DB_PATH` separado.

```bash
python scripts/simular_evento.py --url http://localhost:8000 --chave dev
python scripts/simular_evento.py --url http://localhost:8000 --chave dev --painel  # alertas e bueiros simulados
python scripts/simular_evento.py --url http://localhost:8000 --chave dev --calmo   # volta ao normal
```

## Segurança, LGPD e acessibilidade

- Credenciais só por variável de ambiente (`.env` fora do Git, GitHub Secrets na nuvem). Rotas de escrita exigem `X-API-Key`; sem chave configurada, ficam bloqueadas.
- O cidadão não informa nome, telefone nem GPS: escolhe o bairro. A foto não é gravada pela API; só o resultado da detecção. O serviço de visão borra rostos e placas e a API recusa detecções sem `imagem_anonimizada=true`.
- Perguntas do chat passam por remoção de CPF, telefone e e-mail antes de ir ao LLM e não são armazenadas.
- Limite de requisições por IP no chat e no envio de fotos; cabeçalhos de segurança (CSP, nosniff, no-referrer).
- Acessibilidade: contraste AA, nível de risco com texto e símbolo (não só cor), tabela equivalente ao mapa para leitor de tela, navegação por teclado com foco visível, link "pular para o conteúdo", linguagem simples, funciona em celular de entrada. Sem conexão com a API, o site mostra os últimos dados e avisa.
- Dados pessoais armazenados: nenhum. Dados guardados: risco por bairro, alertas, ocorrências (tipo, bairro, horário, confiança) e leituras de sensores.

## Estrutura

```
app/            API (main.py), regras de risco, assistente, indicadores, dados simulados
static/         site (HTML, CSS, JS) + Leaflet embutido
data/           bairros.csv e base_conhecimento.json
scripts/        simular_evento.py, coletar_previsao.py (Open-Meteo), importar_ouro.py (CSV da Ouro)
tests/          pytest
docs/           contratos de integração, dados simulados, prints
```

## Repositórios das outras disciplinas

| Disciplina | Repositório |
| --- | --- |
| Big Data | PREENCHER |
| Generative AI | PREENCHER |
| Applied Computer Vision | PREENCHER |
| Robotic Process Automation | PREENCHER |
| Secure DevOps & Cloud | PREENCHER |
| Project-Based Maker Lab | PREENCHER |
