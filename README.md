# car-collector

`car-collector` e um servico FastAPI para receber telemetria automotiva do Torque/OBD/GPS, gravar amostras locais e expor dados para dashboard.

O projeto esta em producao neste host. Evite reiniciar servicos ou alterar o backend sem revisar o impacto operacional.

## Como roda

O processo de producao observado esta rodando via `uvicorn`:

```bash
/srv/car-collector/venv/bin/python3 /srv/car/app/venv/bin/uvicorn car_collector:app --host 127.0.0.1 --port 8088
```

Existe tambem uma unidade systemd em `/etc/systemd/system/car-collector.service`, com dados em `/var/lib/car-collector`.

Para desenvolvimento local, crie um ambiente virtual, instale as dependencias usadas pelo app (`fastapi`, `uvicorn`, `psycopg`) e configure variaveis a partir de `.env.example`.

Exemplo local:

```bash
python3 -m venv venv
. venv/bin/activate
pip install fastapi uvicorn psycopg
uvicorn car_collector:app --host 127.0.0.1 --port 8088
```

## Endpoints principais

Implementacao ativa em `car_collector.py`:

- `GET /` - status simples do servico.
- `GET|POST /torque` - ingestao de parametros enviados pelo Torque.
- `GET /api/car/latest` - ultimo registro salvo em `latest_creta.json`.
- `GET /api/trips` - lista viagens salvas.
- `GET /api/trips/{trip_id}` - detalhes de uma viagem.
- `POST /api/trips/end` - encerra a viagem atual em memoria.

Existe tambem `app.py`, com uma API alternativa baseada em NDJSON:

- `GET /health`
- `POST /api/car/ingest`
- `GET /api/car/latest`
- `GET /api/car/track`
- `GET /api/car/events`

## Onde ficam os dados

Os dados reais de producao ficam fora do repositorio. O diretorio de runtime local usado em producao e:

```text
/var/lib/car-collector
```

Arquivos gerados incluem NDJSON de requisicoes, `latest_creta.json` e viagens em `trips/`. Esses arquivos contem dados reais de telemetria, possiveis tokens, IPs, email e localizacao; por isso nao entram no Git.

## Integracao PostgreSQL

A integracao PostgreSQL existe via `insert_telemetry()` importado por `car_collector.py`. A conexao e lida exclusivamente da variavel de ambiente `CAR_DB_DSN`.

Configure localmente com um DSN real fora do Git:

```bash
export CAR_DB_DSN='postgresql://car_user:CHANGE_ME@127.0.0.1:5432/car_collector'
```

O arquivo `.env.example` mostra o formato esperado com placeholder. Nao grave senha real em `.env.example`, README ou codigo.

Se `CAR_DB_DSN` nao estiver definida, a API continua recebendo telemetria e gravando os arquivos locais; apenas o insert no PostgreSQL e ignorado.

Migrations versionadas ficam em `migrations/`. A migration `20260427_001_trip_technical_summary.sql` adiciona colunas tecnicas em `car.trip` para vincular o `logical_trip_id` usado pelo backend e gravar o resumo calculado no encerramento da viagem. Ela usa `ALTER TABLE IF EXISTS` e `ADD COLUMN IF NOT EXISTS`, sem recriar tabelas ou apagar dados.

## Politica de versionamento inicial

Este repositorio deve excluir:

- ambientes virtuais (`venv/`, `.venv/`);
- caches Python (`__pycache__/`, `*.pyc`);
- `.env` e arquivos de segredo;
- logs, reports, NDJSON, backups e exports;
- dados reais de `/var/lib/car-collector`;
- configuracoes locais com credenciais.

## Documentacao

- [Operacao](docs/OPERACAO.md)
- [Dados e telemetria](docs/DADOS_E_TELEMETRIA.md)
- [Roadmap](docs/ROADMAP.md)

## Licenca

Este projeto e publicado sob a licenca MIT. Veja o arquivo [LICENSE](LICENSE).
