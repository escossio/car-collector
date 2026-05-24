#!/usr/bin/env python3
import json, os, time, uuid
from datetime import datetime, timezone
from pathlib import Path
from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware

try:
    from db import create_trip, finish_trip, get_trip as get_db_trip, insert_telemetry, list_trips as list_db_trips
except Exception as e:
    print("DB INIT ERROR:", e)
    def create_trip(logical_trip_id: str, started_ts: float | None = None, vehicle_id: int = 1):
        return None
    def finish_trip(db_trip_id: int | None, ended_ts: float | None, summary: dict):
        return None
    def get_db_trip(trip_id):
        return None
    def insert_telemetry(sample: dict):
        return None
    def list_db_trips(limit: int = 50):
        return None

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

DATA_DIR = Path(os.getenv("CAR_COLLECTOR_DATA_DIR", os.getenv("CAR_DATA_DIR", "/var/lib/car-collector")))
TRIPS_DIR = DATA_DIR / "trips"
NDJSON_PATH = DATA_DIR / "torque-requests.ndjson"
IDLE_OFF_TIMEOUT_SECONDS = 90

def new_trip_state():
    return {
        "active": False,
        "id": None,
        "db_trip_id": None,
        "start_time": None,
        "start_ts": None,
        "last_movement": None,
        "last_sample_ts": None,
        "last_speed": None,
        "idle_off_since": None,
        "track": [],
        "stats": {
            "speed_values": [],
            "rpm_values": [],
            "coolant_temp_values": [],
            "intake_temp_values": [],
            "stft_b1_values": [],
            "ltft_b1_values": [],
            "fuel_trim_total_values": [],
            "rich_event_count": 0,
            "lean_event_count": 0,
            "distance": 0,
            "sample_count": 0,
        },
    }


# Estado da viagem atual (em memoria)
current_trip = new_trip_state()

PID_MAP = {
    "k5": "temp_motor", "kf": "temp_admissao", "k46": "temp_ambiente",
    "k3c": "temp_catalisador_b1s1", "kc": "rpm", "kd": "velocidade_obd",
    "k4": "carga_motor", "ke": "avanco_ignicao", "k11": "posicao_acelerador",
    "kb": "pressao_map", "k33": "pressao_barometrica", "k6": "stft_b1",
    "k7": "ltft_b1", "k44": "afr_comandado", "k14": "o2_b1s1_volt",
    "k42": "voltagem_bateria", "kff1005": "gps_lon", "kff1006": "gps_lat",
    "kff1007": "gps_velocidade", "kff1001": "rpm_torque"
}

def get_val(d, *keys):
    for k in keys:
        if k in d and d[k] is not None:
            try: return float(d[k])
            except: pass
    return None

def add_numeric(values, value):
    if value is not None:
        values.append(value)

def avg(values):
    return sum(values) / len(values) if values else None

def max_or_none(values):
    return max(values) if values else None

def min_or_none(values):
    return min(values) if values else None

def parse_record_ts(record):
    ts = record.get("ts")
    if ts is not None:
        try:
            return float(ts)
        except Exception:
            pass

    ts_iso = record.get("ts_iso")
    if ts_iso:
        try:
            return datetime.fromisoformat(str(ts_iso).replace("Z", "+00:00")).timestamp()
        except Exception:
            pass

    return None

def read_latest_record():
    p = DATA_DIR / "latest_creta.json"
    if not p.exists():
        return None
    return json.loads(p.read_text())

def write_latest_record(record):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(DATA_DIR / "latest_creta.json", "w") as f:
        f.write(json.dumps(record))

def latest_idle_off(record):
    data = record.get("data", {}) if isinstance(record, dict) else {}
    speed = get_val(data, "velocidade_filtrada")
    rpm_raw = get_val(data, "rpm", "rpm_torque", "kc", "kff1001")
    speed = speed if speed is not None else 0
    return speed <= 0 and (rpm_raw is None or rpm_raw <= 0)

def mark_latest_trip_closed(reason, ended_ts):
    record = read_latest_record()
    if not record:
        return None

    data = record.setdefault("data", {})
    data["trip_active"] = False
    data["trip_id"] = None
    data["db_trip_id"] = None
    data["trip_ended_reason"] = reason
    data["trip_ended_at"] = datetime.fromtimestamp(ended_ts).isoformat()
    data.pop("trip_stats", None)
    write_latest_record(record)
    return record

def build_trip_summary(end_ts=None):
    s = current_trip["stats"]
    end_ts = end_ts or time.time()
    duration_s = None
    if current_trip.get("start_ts"):
        duration_s = int(max(0, end_ts - current_trip["start_ts"]))

    return {
        "duration_s": duration_s,
        "distance_km": s["distance"] or None,
        "speed_max": max_or_none(s["speed_values"]),
        "speed_avg": avg(s["speed_values"]),
        "rpm_max": max_or_none(s["rpm_values"]),
        "rpm_avg": avg(s["rpm_values"]),
        "coolant_temp_max": max_or_none(s["coolant_temp_values"]),
        "coolant_temp_avg": avg(s["coolant_temp_values"]),
        "intake_temp_max": max_or_none(s["intake_temp_values"]),
        "intake_temp_avg": avg(s["intake_temp_values"]),
        "stft_b1_avg": avg(s["stft_b1_values"]),
        "stft_b1_min": min_or_none(s["stft_b1_values"]),
        "stft_b1_max": max_or_none(s["stft_b1_values"]),
        "ltft_b1_avg": avg(s["ltft_b1_values"]),
        "ltft_b1_min": min_or_none(s["ltft_b1_values"]),
        "ltft_b1_max": max_or_none(s["ltft_b1_values"]),
        "fuel_trim_total_avg": avg(s["fuel_trim_total_values"]),
        "rich_event_count": s["rich_event_count"],
        "lean_event_count": s["lean_event_count"],
        "sample_count": s["sample_count"],
    }

def summary_from_latest(record, end_ts=None):
    data = record.get("data", {}) if isinstance(record, dict) else {}
    trip_stats = data.get("trip_stats") or {}
    end_ts = end_ts or time.time()
    start_ts = current_trip.get("start_ts")
    if start_ts is not None:
        duration_s = int(max(0, end_ts - start_ts))
    else:
        duration_s = trip_stats.get("duration")

    return {
        "duration_s": duration_s,
        "distance_km": None,
        "speed_max": trip_stats.get("speed_max"),
        "speed_avg": trip_stats.get("speed_avg"),
        "rpm_max": trip_stats.get("rpm_max"),
        "rpm_avg": trip_stats.get("rpm_avg"),
        "coolant_temp_max": trip_stats.get("coolant_temp_max"),
        "coolant_temp_avg": trip_stats.get("coolant_temp_avg"),
        "intake_temp_max": trip_stats.get("intake_temp_max"),
        "intake_temp_avg": trip_stats.get("intake_temp_avg"),
        "stft_b1_avg": None,
        "stft_b1_min": None,
        "stft_b1_max": None,
        "ltft_b1_avg": None,
        "ltft_b1_min": None,
        "ltft_b1_max": None,
        "fuel_trim_total_avg": None,
        "rich_event_count": 0,
        "lean_event_count": 0,
        "sample_count": None,
    }

def restore_current_trip_from_latest(record):
    if current_trip["active"]:
        return False

    data = record.get("data", {}) if isinstance(record, dict) else {}
    if not data.get("trip_active") or not data.get("trip_id"):
        return False

    record_ts = parse_record_ts(record) or time.time()
    duration = (data.get("trip_stats") or {}).get("duration")
    try:
        start_ts = record_ts - float(duration) if duration is not None else None
    except Exception:
        start_ts = None

    current_trip["active"] = True
    current_trip["id"] = data.get("trip_id")
    current_trip["db_trip_id"] = data.get("db_trip_id")
    current_trip["start_ts"] = start_ts
    current_trip["start_time"] = (
        datetime.fromtimestamp(start_ts).isoformat() if start_ts is not None else None
    )
    current_trip["last_sample_ts"] = record_ts
    current_trip["last_speed"] = get_val(data, "velocidade_filtrada") or 0
    if latest_idle_off(record):
        current_trip["idle_off_since"] = record_ts

    return True

def start_trip(now):
    current_trip["active"] = True
    current_trip["id"] = str(uuid.uuid4())[:8]
    current_trip["start_time"] = datetime.now().isoformat()
    current_trip["start_ts"] = now
    current_trip["idle_off_since"] = None
    current_trip["db_trip_id"] = create_trip(current_trip["id"], now)
    print(f"🚗 Nova viagem iniciada: {current_trip['id']} db_id={current_trip['db_trip_id']}")

def update_trip_stats(now, speed, rpm, coolant_temp, intake_temp, stft, ltft, lat, lon):
    s = current_trip["stats"]
    s["sample_count"] += 1

    if current_trip.get("last_sample_ts") is not None and current_trip.get("last_speed") is not None:
        dt = now - current_trip["last_sample_ts"]
        if 0 < dt <= 300:
            s["distance"] += ((current_trip["last_speed"] + speed) / 2) * dt / 3600
    current_trip["last_sample_ts"] = now
    current_trip["last_speed"] = speed

    add_numeric(s["speed_values"], speed)
    add_numeric(s["rpm_values"], rpm)
    if coolant_temp and coolant_temp > 0:
        add_numeric(s["coolant_temp_values"], coolant_temp)
    if intake_temp and intake_temp > 0:
        add_numeric(s["intake_temp_values"], intake_temp)
    if stft is not None:
        add_numeric(s["stft_b1_values"], stft)
    if ltft is not None:
        add_numeric(s["ltft_b1_values"], ltft)
    if stft is not None and ltft is not None:
        fuel_trim_total = stft + ltft
        add_numeric(s["fuel_trim_total_values"], fuel_trim_total)
        if fuel_trim_total < -10:
            s["rich_event_count"] += 1
        elif fuel_trim_total > 10:
            s["lean_event_count"] += 1

    if lat and lon:
        current_trip["track"].append({"lat": lat, "lon": lon, "ts": now, "spd": speed})

def save_trip(reason=None, end_ts=None):
    global current_trip
    if not current_trip["active"] or not current_trip["id"]:
        return None

    end_ts = end_ts or time.time()
    latest_record = read_latest_record()
    if current_trip["stats"]["sample_count"] > 0:
        summary = build_trip_summary(end_ts)
    elif latest_record:
        summary = summary_from_latest(latest_record, end_ts)
    else:
        summary = build_trip_summary(end_ts)
    
    TRIPS_DIR.mkdir(parents=True, exist_ok=True)
    trip_data = {
        "id": current_trip["id"],
        "db_trip_id": current_trip["db_trip_id"],
        "start_time": current_trip["start_time"],
        "end_time": datetime.now().isoformat(),
        "duration_seconds": summary["duration_s"],
        "track": current_trip["track"][-500:],
        "stats": summary,
    }
    
    filename = f"trip_{current_trip['id']}.json"
    with open(TRIPS_DIR / filename, "w") as f:
        json.dump(trip_data, f, indent=2)
    
    if reason:
        print(reason)
    print(f"💾 Viagem {current_trip['id']} salva!")
    finish_trip(current_trip["db_trip_id"], end_ts, summary)
    mark_latest_trip_closed(reason or "trip ended", end_ts)
    reset_trip()
    return trip_data

def reset_trip():
    global current_trip
    current_trip = new_trip_state()

def evaluate_idle_off_timeout(speed, rpm_raw, now, observed_ts=None, reason="trip ended by idle/off timeout"):
    if not current_trip["active"]:
        return None

    speed = speed if speed is not None else 0
    idle_off = speed <= 0 and (rpm_raw is None or rpm_raw <= 0)
    if not idle_off:
        current_trip["idle_off_since"] = None
        return None

    if current_trip.get("idle_off_since") is None:
        current_trip["idle_off_since"] = observed_ts or now

    if now - current_trip["idle_off_since"] >= IDLE_OFF_TIMEOUT_SECONDS:
        return save_trip(reason, end_ts=now)

    return None

@app.get("/")
def root(): return {"status": "online", "version": "trips-v2"}

@app.get("/torque")
@app.post("/torque")
async def ingest(request: Request):
    global current_trip
    
    params = dict(request.query_params)
    if request.method == "POST":
        body = await request.body()
        try:
            from urllib.parse import parse_qs
            params.update({k: v[0] for k, v in parse_qs(body.decode()).items()})
        except: pass
    
    if not params: return PlainTextResponse("OK!")

    processed = {}
    for k, v in params.items():
        try: val = float(v)
        except: val = v
        key_lower = k.lower()
        if key_lower in PID_MAP:
            processed[PID_MAP[key_lower]] = val
        processed[k] = val

    # Extrair valores importantes
    # PRIORIZAR velocidade OBD (kd) sobre GPS - é mais confiável
    speed_obd = get_val(processed, "velocidade_obd", "kd")
    speed_gps = get_val(processed, "gps_velocidade", "kff1007")
    
    # Usar OBD se disponível, senão GPS (mas filtrar valores absurdos)
    if speed_obd is not None and 0 <= speed_obd <= 200:
        speed = speed_obd
    elif speed_gps is not None and 0 <= speed_gps <= 200:
        speed = speed_gps
    else:
        speed = 0
    
    temp = get_val(processed, "temp_motor", "k5") or 0
    intake_temp = get_val(processed, "temp_admissao", "kf") or 0
    rpm_raw = get_val(processed, "rpm", "rpm_torque", "kc", "kff1001")
    rpm = rpm_raw if rpm_raw is not None else 0
    lat = get_val(processed, "gps_lat", "kff1006")
    lon = get_val(processed, "gps_lon", "kff1005")
    stft = get_val(processed, "stft_b1", "k6")
    ltft = get_val(processed, "ltft_b1", "k7")

    now = time.time()
    movement_detected = speed > 5

    # Lógica de viagem - USAR VELOCIDADE OBD FILTRADA
    # Iniciar viagem apenas se velocidade > 5 km/h (velocidade real do veículo)
    if movement_detected:
        if not current_trip["active"]:
            start_trip(now)
        
        current_trip["last_movement"] = now
        current_trip["idle_off_since"] = None
    
    elif current_trip["active"]:
        # Encerrar apenas quando o carro estiver parado e o motor desligado por timeout contínuo.
        evaluate_idle_off_timeout(speed, rpm_raw, now, observed_ts=now)

    if current_trip["active"]:
        update_trip_stats(now, speed, rpm, temp, intake_temp, stft, ltft, lat, lon)

    # Adicionar info da viagem ao registro
    processed["trip_active"] = current_trip["active"]
    processed["trip_id"] = current_trip["id"]
    processed["db_trip_id"] = current_trip["db_trip_id"] if current_trip["active"] else None
    processed["velocidade_filtrada"] = speed  # Velocidade que usamos para lógica
    
    if current_trip["active"]:
        summary = build_trip_summary(now)
        processed["trip_stats"] = {
            "speed_max": summary["speed_max"],
            "speed_avg": summary["speed_avg"],
            "rpm_max": summary["rpm_max"],
            "rpm_avg": summary["rpm_avg"],
            "coolant_temp_max": summary["coolant_temp_max"],
            "coolant_temp_avg": summary["coolant_temp_avg"],
            "intake_temp_max": summary["intake_temp_max"],
            "intake_temp_avg": summary["intake_temp_avg"],
            "duration": summary["duration_s"],
            "points": len(current_trip["track"])
        }

    record = {"ts": now, "ts_iso": datetime.now().isoformat(), "data": processed}
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    
    with open(NDJSON_PATH, "a") as f: f.write(json.dumps(record) + "\n")
    write_latest_record(record)
    insert_telemetry(record)
    
    return PlainTextResponse("OK!")

@app.get("/api/car/latest")
def latest():
    record = read_latest_record()
    if not record:
        return JSONResponse({"data": {}})

    data = record.get("data", {})
    restore_current_trip_from_latest(record)
    if current_trip["active"] and latest_idle_off(record):
        now = time.time()
        observed_ts = parse_record_ts(record) or now
        speed = get_val(data, "velocidade_filtrada") or 0
        rpm_raw = get_val(data, "rpm", "rpm_torque", "kc", "kff1001")
        evaluate_idle_off_timeout(
            speed,
            rpm_raw,
            now,
            observed_ts=observed_ts,
            reason="trip ended by latest idle/off timeout",
        )
        record = read_latest_record() or record

    return record

@app.get("/api/trips")
def list_trips(limit: int = 50):
    db_trips = list_db_trips(limit)
    if db_trips is not None:
        return {"source": "postgres", "trips": db_trips}

    TRIPS_DIR.mkdir(parents=True, exist_ok=True)
    trips = []
    for f in sorted(TRIPS_DIR.glob("trip_*.json"), reverse=True)[:limit]:
        try:
            trips.append(json.loads(f.read_text()))
        except: pass
    return {"trips": trips}

@app.get("/api/trips/{trip_id}")
def get_trip(trip_id: str):
    db_trip = get_db_trip(trip_id)
    if db_trip is not None:
        return {"source": "postgres", "trip": db_trip}

    p = TRIPS_DIR / f"trip_{trip_id}.json"
    if not p.exists(): return JSONResponse({"error": "Trip not found"}, status_code=404)
    return json.loads(p.read_text())

@app.post("/api/trips/end")
def force_end_trip():
    trip = save_trip("trip ended by api")
    return {"status": "ok", "message": "Viagem encerrada", "trip": trip}
