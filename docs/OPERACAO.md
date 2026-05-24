# Operacao

## Visao geral

O `car-collector` e um servico FastAPI em producao para receber telemetria automotiva do Torque, persistir os dados localmente em arquivos NDJSON e gravar amostras no PostgreSQL para consulta tecnica e dashboard.

O codigo esta no GitHub privado:

```text
https://github.com/escossio/car-collector
```

## Ambiente de producao

- Host: `debian2-1`
- Projeto: `/srv/car-collector`
- Servico systemd: `car-collector.service`
- Backend interno: `uvicorn car_collector:app`
- Porta interna: `127.0.0.1:8088`
- Publicacao publica: `https://www.escossio.com/car/`
- Dashboard: `https://www.escossio.com/car/dashboard/`
- Ingestao Torque: `https://www.escossio.com/car/torque`

## Endpoints principais

- `GET /` - status simples do backend.
- `GET|POST /torque` - ingestao de telemetria enviada pelo Torque.
- `GET /api/car/latest` - ultima amostra salva para o dashboard live.
- `GET /api/trips` - lista viagens salvas.
- `GET /api/trips/{trip_id}` - detalha uma viagem especifica.
- `POST /api/trips/end` - encerra a viagem atual em memoria.

## Diretorios importantes

- `/srv/car-collector` - checkout Git e codigo da aplicacao.
- `/srv/car/public/dashboard` - arquivos publicados do dashboard.
- `/var/lib/car-collector` - runtime local com NDJSON, `latest_creta.json` e trips.
- `/etc/car-collector/car-collector.env` - configuracao operacional local com variaveis sensiveis.

## Validar saude do servico

```bash
systemctl status car-collector.service --no-pager
systemctl is-active car-collector.service
```

O estado esperado e `active`.

## Validar API

Valide localmente pela porta interna:

```bash
curl -fsS http://127.0.0.1:8088/
curl -fsS http://127.0.0.1:8088/api/car/latest
```

Valide publicamente pelo caminho publicado:

```bash
curl -fsS https://www.escossio.com/car/
curl -fsS https://www.escossio.com/car/dashboard/
```

## Validar ingestao

Para uma validacao controlada, envie uma amostra minima sem dados pessoais e confira se o backend responde `OK!`:

```bash
curl -fsS 'http://127.0.0.1:8088/torque?kd=0&kc=0&k5=80'
```

Depois confira se o arquivo NDJSON foi atualizado:

```bash
wc -l /var/lib/car-collector/torque-requests.ndjson
tail -1 /var/lib/car-collector/torque-requests.ndjson
```

Evite usar amostras com velocidade positiva em teste manual, pois isso pode abrir uma viagem em memoria.

## Validar PostgreSQL

A conexao real fica fora do Git em `/etc/car-collector/car-collector.env`. Para validar contagem sem expor segredo:

```bash
set -a
. /etc/car-collector/car-collector.env
set +a

/srv/car-collector/venv/bin/python - <<'PY'
import os
import psycopg

with psycopg.connect(os.environ["CAR_DB_DSN"]) as conn:
    with conn.cursor() as cur:
        cur.execute("select count(*) from car.telemetry")
        print(cur.fetchone()[0])
PY
```

Tambem e possivel comparar a contagem antes/depois de uma ingestao controlada.

## Seguranca operacional

Nunca versionar:

- senhas, tokens, DSN real ou chaves privadas;
- `.env` ou arquivos em `/etc/car-collector`;
- NDJSON, reports, backups, venv ou caches;
- dados reais de `/var/lib/car-collector`;
- amostras com localizacao, email, IP ou identificadores pessoais.

Antes de qualquer publicacao fora do GitHub privado, rotacione credenciais e faca nova auditoria de historico.
