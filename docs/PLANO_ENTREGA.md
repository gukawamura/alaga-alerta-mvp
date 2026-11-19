# Alaga Alerta · Plano de entrega

## O que já existe

| Área | Disponível no workspace |
| --- | --- |
| Aplicação | API FastAPI, SQLite, mapa e tabela por bairro, alertas, ocorrências, sensores e indicadores. |
| GenAI | API RAG na pasta `genai`. O MVP usa `ASSISTENTE_URL` para chamar o serviço e mantém a base local para quando ele estiver indisponível. |
| Previsão | O mapa e a tabela identificam a origem da previsão. O MVP público foi validado com previsão do DWD MOSMIX nas 22 áreas do catálogo. Leituras de perigo e ocorrências confirmadas também contribuem para o risco. |
| Importação da Ouro | O importador aceita o CSV nativo e o formato anterior. Os dez bairros do Big Data têm correspondência na API. O catálogo agora tem 22 áreas. |
| RPA | Jabaquara e Santo Amaro aceitam o envio de alertas. Reenvios equivalentes enquanto vigentes retornam o alerta existente. Alertas ativos da origem RPA contribuem para o risco exibido no mapa. |
| Visão | A API solicita análise durante o envio. Se o serviço estiver ausente, informa indisponibilidade. Resultados confirmados aparecem na lista e no mapa na posição de referência do bairro. |
| Infraestrutura | Dockerfile, Compose, endpoints de saúde e métricas, e [MVP publicado no Render](https://alaga-alerta-mvp.onrender.com/). |
| Entrega de Big Data | Relatório finalizado. As evidências incluem coletas simultâneas no Airflow, ingestão incremental, consultas da Ouro e integração com o MVP local. [Repositório de Big Data](https://github.com/gukawamura/alaga-big-data). |
| Entrega de GenAI | Relatório, notebook com saídas e avaliação publicados. A integração com a API central foi validada no MVP local. [Repositório de GenAI](https://github.com/gukawamura/alaga-genai). |

## O que falta e como validar

| Ordem | Etapa | Critério de aceite |
| --- | --- | --- |
| 1 | Manter a API do GenAI acessível ao ambiente hospedado. | Chat responde com fonte pelo LLM quando acessado pela URL pública. |
| 2 | Validar a interface em navegador, celular e leitor de tela. Testar a imagem Docker e a partida pelo Compose. | Mapa e tabela exibem o mesmo estado, a interação por teclado funciona, erros têm mensagem clara, `/health` responde e o SQLite preserva o estado após reinício do Compose com volume. |
| 3 | Confirmar a infraestrutura Terraform da equipe e preparar os workflows de DevOps. | Banco em volume persistente, pipeline com evidências de falha e recuperação, dashboard com as quatro métricas de ouro e um alerta disparado. |
| 4 | Reunir os links e evidências dos outros componentes. | Links confirmados pela equipe e evidências conforme o enunciado de cada disciplina. |

Visão Computacional e RPA ficam com os responsáveis pelas respectivas
disciplinas. A integração ao MVP pode ser validada quando eles entregarem
os serviços e executarem os fluxos previstos nos contratos da API.

## Reprodução das evidências de Big Data

| Ordem | Ação | Evidência a salvar |
| --- | --- | --- |
| 1 | Abra o MVP e selecione Penha em **Meu bairro**. Se a previsão da Ouro tiver expirado, gere e publique um lote atual usando o notebook 04. | Captura do card mostrando o bairro e `Previsão: Ouro (Databricks)`. Guarde o CSV publicado e o horário da importação. |
| 2 | No Airflow, execute `gs_coleta_alaga` para datas históricas distintas. Identifique os JSONs produzidos por cada execução e prepare dois lotes. | Prints de **Graph** com tarefas e dependências e **Grid** com as execuções concluídas. Registre as datas e os arquivos integrantes de cada lote. |
| 3 | Para documentar a Bronze desde o zero, use um esquema e Volume de evidência com checkpoints próprios. Envie o lote 1 e rode 01, envie o lote 2 e rode 01, depois rode 01 sem enviar mais arquivos. | Contagens por fonte nas três rodadas, com `antes`, `depois` e `novos`. Na terceira, confirme `novos=0` para todas as fontes. |
| 4 | Execute 02 com os dois lotes e consulte a estrutura de `prata_ocorrencias`. | Saídas com total bruto, registros barrados por regra e total válido. Capture as colunas com hash e evite mostrar dados pessoais em claro. |
| 5 | Execute 03 e as cinco consultas de `consultas_ouro.sql`. | Nome da tabela fato e das duas dimensões, consulta, resultado e uma frase de interpretação para cada SQL. Destaque a população potencialmente exposta na consulta de impacto. |
| 6 | Monte o PDF seguindo a ordem dos requisitos 01 a 09. | Integrantes e RMs, diagrama da arquitetura, tabela de fontes, capturas legendadas e link do repositório público. Confirme o link em janela anônima. |

A publicação de 120 linhas provou a integração técnica da Ouro com o MVP.
Ela não substitui as evidências das duas execuções históricas do Airflow
nem as contagens do processamento incremental no Databricks.
