#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
car-collector (FastAPI)
- Ingest: recebe telemetria (Torque/OBD/GPS) e grava em NDJSON
- Latest/Track/Events: API para o dashboard (LIVE)

Contratos:
  POST /api/car/ingest?token=...   Body: JSON (obj) ou NDJSON (várias linhas)
  GET  /api/car/latest?vehicle=creta[&token=...]
  GET  /api/car/track?vehicle=creta&minutes=30[&token=...]
  GET  /api/car/events?vehicle=creta&limit=20[&token=...]
"""

from __future__ import annotations

import os
import json
import time
import glob
from typing import Any, Dict, List, Optional, Tuple
from datetime import datetime, timezone

from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse, PlainTextResponse
from fastapi.middleware.cors import CORSMiddleware

APP_NAME = "car-collector"

# ===== Config =====
DATA_DIR = os.environ.get("CAR_DATA_DIR", "/var/lib/car-collector")
TOKEN = os.environ.get("CAR_TOKEN", "")  # se vazio, sem auth
MAX_LATEST_SCAN = int(os.environ.get("CAR_MAX_LATEST_SCAN", "5000"))  # linhas para trás no NDJSON

os.makedirs(DATA_DIR, exist_ok=True)

app = FastAPI(title=APP_NAME)

# Se o dashboard estiver em outro host/origem, libera CORS.
# Como você usa mesmo domínio, isso não é crítico, mas não atrapalha.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # se quiser travar, troque pra ["https://car.escossio.dev.br"]
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)

# ===== Helpers =====

def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")

def _get_token_from_request(request: Request) -> str:
    # token por querystring: ?token=...
    t = request.query_params.get("token") or ""
    if t:
        return t
    # token por header: X-Token: ...
    t = request.headers.get("x-token") or request.headers.get("X-Token") or ""
    return t

def require_token(request: Request) -> None:
    if not TOKEN:
        return
    got = _get_token_from_request(request)
    if got != TOKEN:
        raise HTTPException(status_code=401, detail="unauthorized")

def safe_float(x: Any) -> Optional[float]:
    try:
        if x is None:
            return None
        return float(x)
    except Exception:
        return None

def safe_int(x: Any) -> Optional[int]:
    try:
        if x is None:
            return None
        return int(float(x))
    except Exception:
        return None

def read_ndjson_last_record(vehicle: str) -> Optional[Dict[str, Any]]:
    """
    Lê o último registro do veículo varrendo o arquivo NDJSON de trás pra frente.
    Arquivos esperados: torque-requests.ndjson, ingest.ndjson, etc.
    """
    patterns = [
        os.path.join(DATA_DIR, "torque-requests.ndjson"),
        os.path.join(DATA_DIR, "ingest.ndjson"),
        os.path.join(DATA_DIR, "*.ndjson"),
    ]

    files: List[str] = []
    for p in patterns:
        files.extend(glob.glob(p))

    # Ordena por mtime (mais recente primeiro)
    files = sorted(set(files), key=lambda f: os.path.getmtime(f), reverse=True)

    for fpath in files:
        try:
            with open(fpath, "rb") as f:
                # Estratégia simples: lê as últimas N linhas (scan reverso leve)
                f.seek(0, os.SEEK_END)
                size = f.tell()
                if size == 0:
                    continue

                # lê blocos do final
                block = b""
                pos = size
                lines_checked = 0

                while pos > 0 and lines_checked < MAX_LATEST_SCAN:
                    step = min(8192, pos)
                    pos -= step
                    f.seek(pos)
                    chunk = f.read(step)
                    block = chunk + block

                    # quebra em linhas
                    parts = block.split(b"\n")
                    # guarda a primeira parte (pode estar incompleta) pro próximo loop
                    block = parts[0]
                    # processa as linhas completas do fim pro começo
                    for raw in reversed(parts[1:]):
                        if not raw.strip():
                            continue
                        lines_checked += 1
                        try:
                            obj = json.loads(raw.decode("utf-8", errors="replace"))
                        except Exception:
                            continue
                        if str(obj.get("vehicle", "")).lower() == vehicle.lower():
                            return obj

                # fallback: tenta block se for linha completa
                if block.strip():
                    try:
                        obj = json.loads(block.decode("utf-8", errors="replace"))
                        if str(obj.get("vehicle", "")).lower() == vehicle.lower():
                            return obj
                    except Exception:
                        pass

        except Exception:
            continue

    return None

def normalize_latest(payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Normaliza o payload ingerido para o contrato do dashboard.
    Se vier campos faltando, devolve None/— do lado do front.
    """
    gps = payload.get("gps") or {}
    eng = payload.get("engine") or {}
    fuel = payload.get("fuel") or {}
    trip = payload.get("trip") or {}

    out = {
        "ok": True,
        "ts_utc": payload.get("ts_utc") or payload.get("ts") or utc_now_iso(),
        "session": payload.get("session") or payload.get("session_id") or "—",
        "vehicle": payload.get("vehicle") or "unknown",
        "gps": {
            "lat": safe_float(gps.get("lat")),
            "lon": safe_float(gps.get("lon")),
            "alt": safe_float(gps.get("alt")),
            "acc": safe_float(gps.get("acc")),
            "bearing": safe_float(gps.get("bearing")),
            "sats": safe_int(gps.get("sats")),
            "speed_kmh": safe_float(gps.get("speed_kmh")),
        },
        "engine": {
            "rpm": safe_int(eng.get("rpm")),
            "load_pct": safe_float(eng.get("load_pct")),
            "temp_c": safe_float(eng.get("temp_c")),
            "volt": safe_float(eng.get("volt")),
        },
        "fuel": {
            "km_l": safe_float(fuel.get("km_l")),
            "km_l_avg": safe_float(fuel.get("km_l_avg")),
            "afr": safe_float(fuel.get("afr")),
            "stft": safe_float(fuel.get("stft")),
            "ltft": safe_float(fuel.get("ltft")),
        },
        "trip": {
            "dist_km": safe_float(trip.get("dist_km")),
            "time_s": safe_int(trip.get("time_s")),
            "spd_kmh": safe_float(trip.get("spd_kmh")),
            "spd_avg": safe_float(trip.get("spd_avg")),
            "spd_max": safe_float(trip.get("spd_max")),
        },
    }
    return out

# ===== Routes =====

@app.get("/health")
def health():
    return {"ok": True, "service": APP_NAME, "ts_utc": utc_now_iso()}

@app.post("/api/car/ingest")
async def ingest(request: Request):
    require_token(request)

    raw = await request.body()
    if not raw:
        return JSONResponse({"ok": False, "error": "empty_body" }, status_code=400)

    text = raw.decode("utf-8", errors="replace").strip()

    # aceita JSON único OU NDJSON
    objs: List[Dict[str, Any]] = []
    if text.startswith("{"):
        try:
            objs = [json.loads(text)]
        except Exception as e:
            return JSONResponse({"ok": False, "error": "invalid_json", "detail": str(e)}, status_code=400)
    else:
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                objs.append(json.loads(line))
            except Exception:
                # se vier lixo no meio, ignora linha
                continue

    if not objs:
        return JSONResponse({"ok": False, "error": "no_valid_records" }, status_code=400)

    # grava NDJSON
    out_path = os.path.join(DATA_DIR, "ingest.ndjson")
    with open(out_path, "a", encoding="utf-8") as f:
        for obj in objs:
            # reforça timestamp
            obj.setdefault("ts_utc", utc_now_iso())
            f.write(json.dumps(obj, ensure_ascii=False) + "\n")

    return {"ok": True, "count": len(objs)}

@app.get("/api/car/latest")
def latest(request: Request, vehicle: str = "creta"):
    require_token(request)

    rec = read_ndjson_last_record(vehicle)
    if not rec:
        return JSONResponse({"ok": False, "error": "no_data", "vehicle": vehicle}, status_code=404)

    return JSONResponse(normalize_latest(rec))

@app.get("/api/car/track")
def track(request: Request, vehicle: str = "creta", minutes: int = 30):
    require_token(request)

    # implementação simples: varre últimas linhas e pega pontos recentes
    # (pra ficar leve, não vamos varrer histórico gigante agora)
    minutes = max(1, min(minutes, 24 * 60))

    recs: List[Dict[str, Any]] = []
    # Reaproveita a lógica lendo arquivos, mas aqui é uma versão "quick & dirty"
    patterns = [
        os.path.join(DATA_DIR, "torque-requests.ndjson"),
        os.path.join(DATA_DIR, "ingest.ndjson"),
        os.path.join(DATA_DIR, "*.ndjson"),
    ]
    files: List[str] = []
    for p in patterns:
        files.extend(glob.glob(p))
    files = sorted(set(files), key=lambda f: os.path.getmtime(f), reverse=True)

    cutoff = time.time() - (minutes * 60)

    points: List[Dict[str, Any]] = []
    for fpath in files:
        try:
            with open(fpath, "r", encoding="utf-8", errors="replace") as f:
                # lê só as últimas ~2000 linhas pra não matar o servidor
                lines = f.readlines()[-2000:]
                for line in lines:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        obj = json.loads(line)
                    except Exception:
                        continue
                    if str(obj.get("vehicle", "")).lower() != vehicle.lower():
                        continue

                    ts = obj.get("ts_utc") or obj.get("ts")
                    # tenta converter ISO → epoch
                    try:
                        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                        epoch = dt.timestamp()
                    except Exception:
                        epoch = None

                    if epoch is not None and epoch < cutoff:
                        continue

                    gps = obj.get("gps") or {}
                    lat = safe_float(gps.get("lat"))
                    lon = safe_float(gps.get("lon"))
                    if lat is None or lon is None:
                        continue

                    points.append({"lat": lat, "lon": lon, "ts_utc": ts})
        except Exception:
            continue

        # se já temos pontos suficientes, para
        if len(points) >= 500:
            break

    # ordena por timestamp (se der)
    def _key(p):
        t = p.get("ts_utc") or ""
        return t
    points = sorted(points, key=_key)

    return {"ok": True, "vehicle": vehicle, "minutes": minutes, "points": points[-500:]}

@app.get("/api/car/events")
def events(request: Request, vehicle: str = "creta", limit: int = 20):
    require_token(request)
    limit = max(1, min(limit, 200))

    # placeholder: por enquanto sem engine de eventos.
    # Vamos devolver lista vazia JSON válida pro dashboard não quebrar.
    return {"ok": True, "vehicle": vehicle, "events": []}
