#!/usr/bin/env python3
import json
from pathlib import Path
from collections import Counter
from datetime import datetime

LOG = Path("/var/lib/car-collector/torque-requests.ndjson")
OUT = Path("/srv/car-collector/reports/torque_log_analysis.json")

total = 0
bad_json = 0
keys = Counter()
vehicles = Counter()
methods = Counter()
paths = Counter()
timestamps = []
samples = []
latest_records = []

def parse_ts(v):
    if not v:
        return None
    try:
        return datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except Exception:
        return None

with LOG.open("r", errors="replace") as f:
    for line in f:
        line = line.strip()
        if not line:
            continue
        total += 1
        try:
            obj = json.loads(line)
        except Exception:
            bad_json += 1
            continue

        if len(samples) < 10:
            samples.append(obj)

        latest_records.append(obj)
        if len(latest_records) > 10:
            latest_records.pop(0)

        for k in obj.keys():
            keys[k] += 1

        method = obj.get("method") or obj.get("_method")
        path = obj.get("path") or obj.get("_path")
        vehicle = obj.get("vehicle") or obj.get("profile") or obj.get("car") or obj.get("name")

        if method:
            methods[str(method)] += 1
        if path:
            paths[str(path)] += 1
        if vehicle:
            vehicles[str(vehicle)] += 1

        for candidate in ["timestamp", "ts", "time", "server_time", "received_at", "_received_at"]:
            dt = parse_ts(obj.get(candidate))
            if dt:
                timestamps.append(dt.isoformat())
                break

analysis = {
    "source": str(LOG),
    "total_lines": total,
    "bad_json_lines": bad_json,
    "top_level_keys": keys.most_common(),
    "methods": methods.most_common(),
    "paths": paths.most_common(),
    "vehicles": vehicles.most_common(),
    "first_timestamp_detected": min(timestamps) if timestamps else None,
    "last_timestamp_detected": max(timestamps) if timestamps else None,
    "sample_records": samples,
    "latest_records": latest_records,
}

OUT.write_text(json.dumps(analysis, indent=2, ensure_ascii=False))
print(json.dumps(analysis, indent=2, ensure_ascii=False))
