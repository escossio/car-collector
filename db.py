import os
from datetime import date, datetime
from decimal import Decimal


def get_dsn():
    return os.getenv("CAR_DB_DSN")


def get_conn():
    dsn = get_dsn()
    if not dsn:
        return None
    import psycopg

    return psycopg.connect(dsn)


TRIP_FIELDS = (
    "id",
    "logical_trip_id",
    "started_at",
    "ended_at",
    "duration_s",
    "distance_km",
    "sample_count",
    "speed_max",
    "speed_avg",
    "rpm_max",
    "rpm_avg",
    "coolant_temp_max",
    "coolant_temp_avg",
    "intake_temp_max",
    "intake_temp_avg",
    "stft_b1_avg",
    "stft_b1_min",
    "stft_b1_max",
    "ltft_b1_avg",
    "ltft_b1_min",
    "ltft_b1_max",
    "fuel_trim_total_avg",
    "rich_event_count",
    "lean_event_count",
)


def json_value(value):
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return value


def json_row(row):
    return {key: json_value(value) for key, value in row.items()}


def fuel_trim_status(value):
    if value is None:
        return "unknown"
    if value < -10:
        return "rich_tendency"
    if value > 10:
        return "lean_tendency"
    return "normal"


def thermal_status(coolant_temp_max):
    if coolant_temp_max is None:
        return "unknown"
    if coolant_temp_max >= 105:
        return "hot"
    return "normal"


def driving_status(rpm_max, speed_max):
    if rpm_max is None and speed_max is None:
        return "unknown"
    if (rpm_max is not None and rpm_max >= 4500) or (speed_max is not None and speed_max >= 140):
        return "aggressive"
    return "normal"


def classify_trip(trip):
    return {
        "fuel_trim_status": fuel_trim_status(trip.get("fuel_trim_total_avg")),
        "thermal_status": thermal_status(trip.get("coolant_temp_max")),
        "driving_status": driving_status(trip.get("rpm_max"), trip.get("speed_max")),
    }


def trip_observations(trip):
    statuses = classify_trip(trip)
    observations = []
    if statuses["fuel_trim_status"] == "rich_tendency":
        observations.append("Fuel trim total medio abaixo de -10: tendencia rica durante a viagem.")
    elif statuses["fuel_trim_status"] == "lean_tendency":
        observations.append("Fuel trim total medio acima de +10: tendencia pobre durante a viagem.")
    elif statuses["fuel_trim_status"] == "normal":
        observations.append("Fuel trim total medio dentro da faixa simples de normalidade.")
    else:
        observations.append("Sem dados suficientes de STFT/LTFT para classificar mistura.")

    if statuses["thermal_status"] == "hot":
        observations.append("Temperatura maxima do motor atingiu faixa quente.")
    elif statuses["thermal_status"] == "normal":
        observations.append("Temperatura maxima do motor ficou abaixo de 105 C.")

    if statuses["driving_status"] == "aggressive":
        observations.append("RPM maximo ou velocidade maxima indicam conducao agressiva.")
    elif statuses["driving_status"] == "normal":
        observations.append("RPM maximo e velocidade maxima ficaram em faixa normal.")

    return observations


def attach_trip_derived(trip):
    trip["classification"] = classify_trip(trip)
    trip["observations"] = trip_observations(trip)
    return trip


def list_trips(limit: int = 50):
    if not get_dsn():
        return None

    try:
        from psycopg.rows import dict_row

        conn = get_conn()
        if conn is None:
            return None

        limit = max(1, min(int(limit or 50), 200))
        fields = ", ".join(TRIP_FIELDS)
        with conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    f"""
                    SELECT {fields}
                      FROM car.trip
                     ORDER BY started_at DESC NULLS LAST, id DESC
                     LIMIT %s
                    """,
                    (limit,),
                )
                return [attach_trip_derived(json_row(row)) for row in cur.fetchall()]
    except Exception as e:
        print("DB TRIP LIST ERROR:", e)
        return None


def get_trip(trip_id):
    if not get_dsn():
        return None

    try:
        from psycopg.rows import dict_row

        conn = get_conn()
        if conn is None:
            return None

        fields = ", ".join(TRIP_FIELDS)
        with conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    f"""
                    SELECT {fields}
                      FROM car.trip
                     WHERE id::text = %s OR logical_trip_id = %s
                     ORDER BY id DESC
                     LIMIT 1
                    """,
                    (str(trip_id), str(trip_id)),
                )
                row = cur.fetchone()
                if not row:
                    return None

                trip = attach_trip_derived(json_row(row))
                cur.execute(
                    """
                    SELECT id,
                           sample_time,
                           latitude,
                           longitude,
                           obd_speed,
                           gps_speed,
                           filtered_speed,
                           rpm,
                           engine_load,
                           ignition_advance,
                           coolant_temp,
                           intake_temp,
                           ambient_temp,
                           stft_b1,
                           ltft_b1,
                           (stft_b1 + ltft_b1) AS fuel_trim_total,
                           afr_commanded,
                           o2_b1s1_voltage,
                           battery_voltage
                      FROM car.telemetry
                     WHERE trip_id = %s
                     ORDER BY sample_time ASC NULLS LAST, id ASC
                     LIMIT 500
                    """,
                    (trip["id"],),
                )
                samples = [json_row(sample) for sample in cur.fetchall()]
                trip["samples"] = samples
                trip["route"] = [
                    {
                        "lat": sample["latitude"],
                        "lon": sample["longitude"],
                        "sample_time": sample["sample_time"],
                        "speed": sample["filtered_speed"],
                    }
                    for sample in samples
                    if sample.get("latitude") is not None and sample.get("longitude") is not None
                ]
                trip["summary"] = {key: trip.get(key) for key in TRIP_FIELDS}
                return trip
    except Exception as e:
        print("DB TRIP DETAIL ERROR:", e)
        return None


def create_trip(logical_trip_id: str, started_ts: float | None = None, vehicle_id: int = 1):
    if not get_dsn():
        return None

    try:
        conn = get_conn()
        if conn is None:
            return None

        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO car.trip (vehicle_id, started_at, logical_trip_id)
                    VALUES (%s, COALESCE(to_timestamp(%s), now()), %s)
                    RETURNING id
                    """,
                    (vehicle_id, started_ts, logical_trip_id),
                )
                row = cur.fetchone()
                return row[0] if row else None
    except Exception as e:
        print("DB TRIP START ERROR:", e)
        return None


def finish_trip(db_trip_id: int | None, ended_ts: float | None, summary: dict):
    if not db_trip_id or not get_dsn():
        return None

    try:
        conn = get_conn()
        if conn is None:
            return None

        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE car.trip
                       SET ended_at = COALESCE(to_timestamp(%s), now()),
                           duration_s = %s,
                           distance_km = %s,
                           speed_max = %s,
                           speed_avg = %s,
                           rpm_max = %s,
                           rpm_avg = %s,
                           coolant_temp_max = %s,
                           coolant_temp_avg = %s,
                           intake_temp_max = %s,
                           intake_temp_avg = %s,
                           stft_b1_avg = %s,
                           stft_b1_min = %s,
                           stft_b1_max = %s,
                           ltft_b1_avg = %s,
                           ltft_b1_min = %s,
                           ltft_b1_max = %s,
                           fuel_trim_total_avg = %s,
                           rich_event_count = %s,
                           lean_event_count = %s,
                           sample_count = %s
                     WHERE id = %s
                    """,
                    (
                        ended_ts,
                        summary.get("duration_s"),
                        summary.get("distance_km"),
                        summary.get("speed_max"),
                        summary.get("speed_avg"),
                        summary.get("rpm_max"),
                        summary.get("rpm_avg"),
                        summary.get("coolant_temp_max"),
                        summary.get("coolant_temp_avg"),
                        summary.get("intake_temp_max"),
                        summary.get("intake_temp_avg"),
                        summary.get("stft_b1_avg"),
                        summary.get("stft_b1_min"),
                        summary.get("stft_b1_max"),
                        summary.get("ltft_b1_avg"),
                        summary.get("ltft_b1_min"),
                        summary.get("ltft_b1_max"),
                        summary.get("fuel_trim_total_avg"),
                        summary.get("rich_event_count"),
                        summary.get("lean_event_count"),
                        summary.get("sample_count"),
                        db_trip_id,
                    ),
                )
                return cur.rowcount
    except Exception as e:
        print("DB TRIP FINISH ERROR:", e)
        return None


def insert_telemetry(sample: dict):
    if not get_dsn():
        return None

    try:
        from psycopg.types.json import Json

        conn = get_conn()
        if conn is None:
            return None

        with conn:
            with conn.cursor() as cur:
                data = sample.get("data", {})

                cur.execute(
                    """
                    INSERT INTO car.telemetry (
                        vehicle_id,
                        trip_id,
                        sample_time,
                        latitude,
                        longitude,
                        obd_speed,
                        gps_speed,
                        filtered_speed,
                        rpm,
                        engine_load,
                        ignition_advance,
                        coolant_temp,
                        intake_temp,
                        ambient_temp,
                        stft_b1,
                        ltft_b1,
                        afr_commanded,
                        o2_b1s1_voltage,
                        battery_voltage,
                        raw_payload
                    )
                    VALUES (
                        1,
                        %s,
                        to_timestamp(%s),
                        %s, %s,
                        %s, %s, %s,
                        %s, %s, %s,
                        %s, %s, %s,
                        %s, %s, %s, %s,
                        %s,
                        %s
                    )
                    """,
                    (
                        data.get("db_trip_id"),
                        sample.get("ts"),
                        data.get("gps_lat"),
                        data.get("gps_lon"),
                        data.get("velocidade_obd"),
                        data.get("gps_velocidade"),
                        data.get("velocidade_filtrada"),
                        data.get("rpm"),
                        data.get("carga_motor"),
                        data.get("avanco_ignicao"),
                        data.get("temp_motor"),
                        data.get("temp_admissao"),
                        data.get("temp_ambiente"),
                        data.get("stft_b1"),
                        data.get("ltft_b1"),
                        data.get("afr_comandado"),
                        data.get("o2_b1s1_volt"),
                        data.get("voltagem_bateria"),
                        Json(sample),
                    ),
                )

    except Exception as e:
        print("DB ERROR:", e)
        return None
