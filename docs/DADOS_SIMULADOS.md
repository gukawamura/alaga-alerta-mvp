# Dados simulados: o que são e como são gerados

O enunciado aceita "dados simulados com geração justificada e documentada".
Este arquivo é essa documentação. Os dados simulados existem para que o MVP
funcione e mostre indicadores mesmo antes de as fontes reais (Ouro do Big
Data, RPA, robô, visão) estarem integradas. Toda linha simulada é marcada
(`fonte = 'simulado'` no risco, `origem = 'simulado'` nos alertas,
`detalhe = 'histórico simulado'` nas ocorrências) e a tela de indicadores
avisa quando eles entram no cálculo.

## Bairros (`data/bairros.csv`)

O catálogo cobre 22 áreas de São Paulo. Inclui as 15 áreas originais do MVP,
seis pontos do catálogo do Big Data e Jabaquara, monitorada pelo RPA. As coordenadas são
referências aproximadas do bairro ou do ponto monitorado.

- `populacao`: aproximação da população do distrito. **Substituir pelos
  números do IBGE carregados pelo Big Data** antes da entrega final.
- `sensibilidade` (0,9 a 1,4): quanto o bairro alaga com a mesma chuva,
  definida pela equipe a partir da recorrência de pontos de alagamento nos
  boletins do CGE (ex.: Jardim Pantanal 1,40, várzea do Tietê; Pinheiros
  1,00). É um peso explícito, ajustável, e não um dado oficial.

## Histórico de janeiro de 2026 (gerado em `app/seed.py`)

Semente aleatória fixa (2026): o mesmo histórico sai em qualquer máquina.

1. Para cada dia, 45% de chance de temporal (janeiro é o mês mais chuvoso
   em SP). O temporal começa entre 14h e 18h no horário local e dura de 1 a
   3 horas, padrão típico das chuvas de verão.
2. Intensidade de pico sorteada entre 6 e 34 mm/h, multiplicada por um fator
   por zona (0,35 a 1,3), porque temporais de verão são localizados.
3. Fora do temporal, garoa ocasional de 0 a 1,5 mm/h.
4. Risco previsto = chuva × sensibilidade; atenção a partir de 10, alto a
   partir de 20.
5. Chuva observada = prevista × erro log-normal (σ = 0,3), porque previsão
   erra. Se o score observado passa de 24, há registro de alagamento entre
   5 e 45 minutos depois do início da hora (75% boletim CGE, 25% foto de
   morador).
6. Alerta: na primeira hora de risco alto do temporal, o "RPA simulado"
   dispara um alerta entre 30 e 90 minutos antes, válido por 3 horas.

Com isso, a taxa de acerto e a antecedência medidas vêm do encontro entre
dois processos com erro, e não de números escolhidos.

## Janela atual

Ao iniciar com banco vazio, a API cria previsão sem chuva relevante de 3 h
atrás até 12 h à frente, para o mapa abrir "calmo". O script
`scripts/simular_evento.py` cria o temporal da demonstração; quando os
componentes reais estiverem no ar, eles substituem cada passo.
