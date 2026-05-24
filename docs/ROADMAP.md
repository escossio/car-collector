# Roadmap

## Fase atual concluida

- Dashboard restaurado.
- Endpoint de ingestao corrigido.
- PostgreSQL integrado e recebendo dados em `car.telemetry`.
- GitHub privado criado para o projeto.
- Configuracao real de banco mantida fora do Git.
- Ciclo basico de trip no PostgreSQL concluido: inicio por movimento real, amostras vinculadas a `car.trip`, encerramento com resumo tecnico minimo.
- Historico tecnico iniciado/concluido nesta rodada: `/api/trips` e `/api/trips/{id}` leem `car.trip`/`car.telemetry` e o dashboard de historico exibe cards tecnicos.

## Proximas fases

### 1. Consolidar regra de inicio/fim de viagem

Objetivo: tornar a deteccao de viagem mais resistente a ruido de GPS, marcha lenta e testes manuais.

Critérios de aceite:

- velocidade GPS sozinha nao inicia trip;
- inicio considera velocidade OBD filtrada e sinais de motor;
- fim considera tempo parado, RPM e ausencia de movimento real;
- testes manuais com velocidade zero nao criam trips indevidas.

### 2. Separar telemetria live de telemetria de trip

Objetivo: permitir dashboard live sem poluir historico de corrida.

Critérios de aceite:

- amostras live continuam sendo gravadas;
- somente amostras qualificadas entram no contexto de trip;
- dados parados ficam classificados como live/estado, nao como corrida;
- API deixa claro o que e live e o que e historico.

### 3. Gerar resumo tecnico por corrida

Objetivo: produzir uma visao consolidada por trip para analise posterior.

Status: concluido para o resumo minimo gravado em `car.trip`.

Critérios de aceite:

- cada trip possui inicio, fim, duracao e contagem de amostras;
- resumo inclui velocidade, RPM, temperatura e tensao;
- resumo registra qualidade do GPS e pontos rejeitados;
- trips curtas ou invalidas sao descartadas ou marcadas como invalidas.

### 4. Enriquecer historico com motor, combustivel e mistura

Objetivo: transformar o historico em ferramenta tecnica, nao apenas rota.

Status: concluido na primeira versao visual com cards tecnicos, classificacao simples de mistura/temperatura/conducao e detalhe por viagem baseado em PostgreSQL.

Critérios de aceite:

- historico inclui carga, avancos, temperaturas, trims e AFR/O2;
- metricas sao agregadas por fase da viagem quando possivel;
- dados ausentes sao representados explicitamente;
- consultas ao PostgreSQL conseguem reconstruir uma trip sem depender do NDJSON.

### 5. Criar alertas de mistura rica/pobre

Objetivo: detectar eventos relevantes de mistura com base em janela temporal e contexto.

Critérios de aceite:

- regra considera STFT, LTFT, AFR/O2, RPM, carga e temperatura;
- alertas exigem persistencia minima, nao uma amostra isolada;
- alertas ficam associados a trip e timestamp;
- dashboard diferencia alerta informativo de alerta critico.

### 6. Melhorar dashboard com graficos temporais

Objetivo: visualizar comportamento do carro durante a trip.

Critérios de aceite:

- graficos mostram RPM, velocidade, temperatura e tensao no tempo;
- mistura/trims aparecem em grafico proprio;
- usuario consegue alternar entre live e historico;
- dashboard permanece leve para uso em celular.

### 7. Preparar migracao historica controlada, se necessario

Objetivo: importar dados antigos para PostgreSQL sem duplicar, vazar ou corromper historico.

Critérios de aceite:

- migracao roda em lote controlado e idempotente;
- arquivo NDJSON antigo e tratado como fonte sensivel;
- duplicidades sao detectadas;
- migracao gera relatorio sem expor dados reais no Git.

## Riscos conhecidos

- Arquivo NDJSON antigo pode estar muito grande.
- GPS pode enviar velocidade absurda ou pontos inconsistentes.
- Campos OBD nem sempre estao disponiveis em todas as amostras.
- Segredo de banco deve permanecer fora do Git.
- Senha do `car_user` deve ser rotacionada antes de qualquer abertura publica.
- Testes manuais podem criar trips se usarem velocidade positiva.
- Historico bruto pode conter localizacao e identificadores sensiveis.
