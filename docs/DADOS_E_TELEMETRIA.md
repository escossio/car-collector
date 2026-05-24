# Dados e Telemetria

## Fluxo

O fluxo operacional atual e:

```text
Torque -> /car/torque -> FastAPI -> NDJSON + PostgreSQL -> dashboard
```

O Torque envia parametros OBD/GPS para o endpoint publico `/car/torque`. A publicacao encaminha a requisicao para o FastAPI interno. O backend normaliza campos conhecidos, grava uma linha em NDJSON, atualiza o estado live e tenta inserir a amostra no PostgreSQL.

## Conceitos

### Telemetria ao vivo

Telemetria ao vivo e a ultima visao conhecida do carro. Ela alimenta o dashboard live e pode incluir dados com o carro parado, ligando, desligando ou aguardando GPS estabilizar.

No PostgreSQL, essas amostras podem ser persistidas em `car.telemetry` com `trip_id NULL`. Isso e esperado quando nao ha viagem ativa.

### Viagem/trip

Trip e o contexto tecnico de uma corrida. Ela deve representar um periodo coerente de uso do carro, com movimento real e dados suficientes para analise de motor, combustivel, temperatura, mistura e comportamento.

GPS sozinho nao deve abrir viagem. Velocidade GPS pode vir suja, atrasada ou absurda; a regra de trip deve priorizar velocidade OBD filtrada e outros sinais de motor.

A regra operacional atual abre uma trip quando a velocidade filtrada ou OBD passa de 5 km/h. Velocidade GPS acima de 200 km/h e tratada como suspeita e nao entra como velocidade filtrada. Quando a trip esta ativa, cada nova amostra em `car.telemetry` recebe `trip_id` apontando para `car.trip.id`.

A trip encerra quando ha indicacao continua de motor desligado/parado por 90 segundos: `rpm <= 0` ou RPM ausente, e velocidade filtrada `<= 0`. Paradas curtas de semaforo ou transito, com RPM presente, nao encerram a viagem.

### Historico

Historico e o conjunto de trips e amostras consolidadas para consulta posterior. Dados parados podem alimentar o dashboard live, mas nao devem necessariamente compor historico de corrida.

### Resumo tecnico

Resumo tecnico e uma camada derivada por trip. Ele deve agrupar estatisticas e eventos relevantes, como temperatura maxima, RPM maximo, velocidade media, estabilidade da mistura, anomalias de GPS e possiveis alertas.

No encerramento da trip, o backend atualiza `car.trip` com `ended_at`, `duration_s`, `distance_km`, medias e maximos de velocidade/RPM/temperaturas, estatisticas STFT/LTFT, media de `stft_b1 + ltft_b1`, contagem de eventos ricos (`fuel_trim_total < -10`), contagem de eventos pobres (`fuel_trim_total > 10`) e `sample_count`.

O historico visual usa o PostgreSQL como fonte principal. A listagem de `/api/trips` traz uma linha tecnica por viagem, e o detalhe de `/api/trips/{id}` combina metadados de `car.trip` com amostras de `car.telemetry`, rota derivada de latitude/longitude e observacoes automaticas simples.

### Fuel trim total

`fuel_trim_total` e a soma de `stft_b1 + ltft_b1` para a amostra. Na consolidacao por viagem, `fuel_trim_total_avg` e a media dessa soma nas amostras que possuem os dois campos.

A classificacao inicial do historico e simples e nao substitui diagnostico mecanico:

- `rich_tendency`: `fuel_trim_total_avg < -10`;
- `lean_tendency`: `fuel_trim_total_avg > 10`;
- `normal`: media entre -10 e +10;
- `unknown`: dados insuficientes.

Eventos ricos e pobres sao contagens de amostras individuais em que `stft_b1 + ltft_b1` ficou abaixo de -10 ou acima de +10.

## Campos principais observados

- `rpm`
- `velocidade_obd`
- `velocidade_filtrada`
- `gps_velocidade`
- `gps_lat`
- `gps_lon`
- `temp_motor`
- `temp_admissao`
- `temp_ambiente`
- `carga_motor`
- `avanco_ignicao`
- `stft_b1`
- `ltft_b1`
- `afr_comandado`
- `o2_b1s1_volt`
- `voltagem_bateria`
- `trip_active`
- `trip_id`

## Qualidade do GPS

O GPS pode produzir valores inconsistentes, especialmente no inicio da sessao, em perda de sinal, em areas com reflexao ou quando o app reaproveita amostras antigas. Por isso:

- velocidade GPS nao deve abrir viagem sozinha;
- coordenadas ausentes ou absurdas devem ser descartadas do trajeto;
- pontos GPS devem ser avaliados junto com velocidade OBD, RPM e tempo;
- rota visual deve tolerar lacunas e pontos rejeitados.

## Trip como contexto tecnico

A viagem nao deve ser apenas uma rota. Ela precisa ser o contexto de interpretacao da telemetria:

- motor frio versus motor quente;
- marcha lenta versus carga;
- aceleracao, cruzeiro e parada;
- diferencas entre velocidade OBD e GPS;
- comportamento de combustivel e mistura durante a corrida.

## Mistura rica/pobre

Mistura rica ou pobre deve ser inferida por contexto, nao por um campo isolado. Indicadores como `stft_b1`, `ltft_b1`, `afr_comandado` e `o2_b1s1_volt` precisam ser lidos junto com carga, RPM, temperatura e fase da viagem.

Diretrizes iniciais:

- STFT/LTFT persistentemente positivos podem indicar correcao para mistura pobre.
- STFT/LTFT persistentemente negativos podem indicar correcao para mistura rica.
- AFR/O2 ajudam a qualificar o evento, mas dependem do regime do motor.
- Alertas devem considerar janela temporal e nao apenas uma amostra isolada.

## Live versus historico

Nem toda amostra live deve virar dado de corrida. Amostras parado, sem RPM confiavel, sem velocidade OBD ou com GPS incoerente podem ser uteis para o dashboard, mas devem ser filtradas ou classificadas antes de entrar no historico tecnico.

Essa separacao evita que dashboards historicos sejam poluidos por ruido de app, testes manuais ou periodos sem movimento real.

Na pratica atual, telemetria live pode existir em `car.telemetry` com `trip_id NULL`; ja o historico de viagem depende de uma linha em `car.trip` e amostras vinculadas por `car.telemetry.trip_id`.
