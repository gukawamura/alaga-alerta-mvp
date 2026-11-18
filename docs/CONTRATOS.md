# Contratos da API central — para cada disciplina integrar

Todos os componentes falam com a mesma API. Rotas de escrita exigem o
cabeçalho `X-API-Key` com o valor de `API_KEY` do servidor (peça ao
responsável pelo deploy; nunca coloque a chave no código, use variável de
ambiente ou GitHub Secrets). Datas em ISO 8601 (`2026-11-19T18:00:00-03:00`
ou `...Z`); a API guarda tudo em UTC. A documentação interativa fica em
`https://SEU-MVP/docs`.

Use `GET /bairros` para conhecer os `bairro_id` válidos (ex.: `vila-formosa`,
`penha`, `se-anhangabau`).

## Big Data → `POST /risco` (tabela Ouro de risco por bairro e hora)

Corpo: lista (até 5000 linhas por chamada). Upsert por `bairro_id` + `hora`.

```json
[
  {"bairro_id": "vila-formosa", "hora": "2026-11-19T18:00:00-03:00", "chuva_mm": 28.5},
  {"bairro_id": "penha", "hora": "2026-11-19T18:00:00-03:00", "chuva_mm": 4.0, "nivel": "baixo", "fonte": "ouro"}
]
```

`nivel` é opcional (`baixo`, `atencao`, `alto`). Se omitido, a API calcula:
score = chuva_mm × sensibilidade do bairro; ≥ 10 atenção, ≥ 20 alto.
Exporte a visão de previsão vigente `workspace.gs.fato_previsao_bairro_hora`
usando o notebook `04_previsao_mvp.py`. O CSV contém as colunas
`bairro_id,data_hora,precipitacao_mm,nivel_risco`. O importador mapeia
`SP001` a `SP010` para os bairros da API e converte `normal` em `baixo`
e `critico` em `alto`. Horários explícitos preservam seu fuso. No CSV
nativo, horários sem fuso são interpretados como São Paulo (UTC−03 para a coleta de 2026).
Confirme o fuso dos valores na exportação. O CSV no contrato da API
(`bairro_id,hora,chuva_mm[,nivel]`) continua aceito.

Para publicar:
`python scripts/importar_ouro.py --url ... --csv ouro.csv --vigente`,
com `API_KEY` no ambiente.

A coleta horária de previsão e a coleta diária do arquivo histórico do
Open-Meteo têm DAGs próprias. A tela de risco atual exibe apenas a janela
de três horas. Para demonstrar a Ouro nessa tela, publique a previsão vigente
e confira `Ouro (Databricks)` no
card e na tabela, e `fonte: ouro` em `GET /risco/{bairro_id}`.
A API combina a previsão com os sinais de campo. A coleta direta automática
preserva os registros já publicados pela Ouro para a mesma hora e bairro.

## RPA → `POST /alertas` e `POST /ocorrencias`

Alerta disparado (Telegram/WhatsApp) — resposta `201`:

```json
{"bairro_id": "vila-formosa", "nivel": "alto",
 "mensagem": "Risco alto de alagamento na Vila Formosa na próxima hora...",
 "canais": "telegram", "origem": "rpa"}
```

`criado_em` (padrão: agora) e `valido_ate` (padrão: +3 h) são opcionais.
O envio novo retorna `201` e `duplicado: false`. Enquanto o alerta
equivalente (mesmo bairro, nível e origem) estiver vigente no horário do
envio, a repetição retorna `200`, `duplicado: true` e o ID original.
O RPA pode enviar alertas para `jabaquara` e `santo-amaro`.
O risco em `GET /risco/agora` inclui alertas vigentes com `origem: "rpa"`.
Para decidir se precisa emitir um novo alerta a partir da previsão, consulte
`GET /risco/{bairro_id}`, pois o risco agregado já inclui os alertas anteriores.

Boletim do CGE/Defesa Civil — resposta `201`:

```json
{"bairro_id": "aricanduva", "tipo": "rua_alagada", "fonte": "cge", "status": "confirmada",
 "detalhe": "Av. Aricanduva, intransitável"}
```

`tipo`: `rua_alagada` | `veiculo_submerso` | `bueiro_entupido`.
Entradas úteis para o robô de RPA: `GET /risco/agora` (nível por bairro),
`GET /leituras` (classificação `perigo` do sensor como gatilho),
`GET /alertas?ativos=true` (para não duplicar alerta).
Se a API responder 5xx ou não responder, o RPA deve registrar a falha no log
e tentar de novo (exigência da disciplina).

## Robô ESP32 (Maker Lab) → `POST /leituras`

```json
{"sensor_id": "esp32-vf-01", "bairro_id": "vila-formosa", "nivel_cm": 42.0,
 "classificacao": "perigo", "medido_em": "2026-11-19T18:05:00-03:00"}
```

`classificacao`: `normal` | `atencao` | `perigo`. Leitura `perigo` com até
60 minutos deixa o bairro em risco alto no mapa. Sem Wi-Fi, o robô guarda
as leituras e reenvia com o `medido_em` original.

Exemplo Arduino (ESP32, HTTPClient):

```cpp
HTTPClient http;
http.begin(String(API_URL) + "/leituras");
http.addHeader("Content-Type", "application/json");
http.addHeader("X-API-Key", API_KEY);   // definido em secrets.h, fora do Git
int code = http.POST("{\"sensor_id\":\"esp32-vf-01\",\"bairro_id\":\"vila-formosa\",\"nivel_cm\":42,\"classificacao\":\"perigo\"}");
http.end();
```

## Visão computacional → dois jeitos de integrar

**Jeito A (recomendado):** subir o modelo como serviço HTTP e configurar
`VISAO_URL` na API. O cidadão envia a foto pelo MVP, a API repassa e grava
só o resultado. O serviço recebe `multipart/form-data` com `arquivo` (imagem)
e `bairro_id`, e responde:

```json
{"deteccoes": [{"classe": "rua_alagada", "confianca": 0.87}]}
```

O serviço deve borrar rostos e placas antes de salvar qualquer imagem.
Se `VISAO_URL` estiver vazia, `POST /fotos` responde `503` sem criar uma
ocorrência. Falhas no serviço configurado retornam `502`.

**Jeito B:** o notebook/serviço de visão grava direto em `POST /deteccoes`:

```json
{"bairro_id": "penha", "imagem_anonimizada": true,
 "deteccoes": [{"classe": "rua_alagada", "confianca": 0.87}]}
```

`imagem_anonimizada: false` é recusado (LGPD). Detecções com confiança
≥ `LIMIAR_CONFIANCA` (0,60) viram ocorrência confirmada no mapa; abaixo
disso aparecem como "não confirmadas" na lista.

## Generative AI → `ASSISTENTE_URL`

A API recebe `POST /assistente {"pergunta": "..."}` do chat, remove dados
pessoais (CPF, telefone, e-mail) e repassa para `ASSISTENTE_URL` com o
mesmo corpo. O serviço da disciplina deve responder:

```json
{"resposta": "Saia do carro e vá para um lugar alto...", "fontes": ["Manual Defesa Civil SP, p. 12"], "consta": true}
```

Quando não souber: `"consta": false` e a resposta "não consta". Se o
serviço cair, a API responde com a base local (`data/base_conhecimento.json`)
e marca `"modo": "local (LLM indisponível)"`.

## Leitura (front, BI, DevOps)

| Rota | Para quê |
| --- | --- |
| `GET /risco/agora` | Nível final por bairro (previsão 3 h + sensor + ocorrências), motivos, orientação e `fontes_previsao`. Sem previsão, `sem_previsao=true` e `chuva_prevista_mm=null`. O nível será `indisponivel` se também faltarem sinais de atenção ou perigo. |
| `GET /risco/{bairro_id}?horas=12` | Linha do tempo da previsão de um bairro |
| `GET /alertas?ativos=true` | Alertas válidos agora |
| `GET /ocorrencias?horas=24` | Ocorrências recentes |
| `GET /leituras?limite=20` | Últimas leituras dos sensores |
| `GET /indicadores` | Indicadores de impacto do pitch, calculados dos dados |
| `GET /health` | Health check |
| `GET /metrics` | Métricas Prometheus (latência, tráfego, erros, chamadas por componente) |
